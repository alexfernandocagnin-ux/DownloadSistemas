import base64
import io
import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch
from catalogs import _common, bpa_portal, ciha_portal, cnes_portal
from catalogs.state import normalize_catalog
from scripts import publish_catalog


class TransportTests(unittest.TestCase):
    def response(self, data, length):
        response = io.BytesIO(data)
        response.headers = {"Content-Length": str(length)}
        return response

    def test_partial_http_download_is_rejected(self):
        with patch.object(_common, "urlopen", return_value=self.response(b"MZ123", 20)):
            with self.assertRaises(ValueError):
                _common.download_via_http("https://example/file", "file.exe", max_size=100)

    def test_oversized_http_is_rejected_before_reading(self):
        response = self.response(b"MZ123", 200)
        with patch.object(_common, "urlopen", return_value=response):
            with self.assertRaises(ValueError):
                _common.download_via_http("https://example/file", "file.exe", max_size=100)

    def test_zip_signature_without_directory_is_rejected(self):
        self.assertFalse(_common.looks_like_zip(b"PK" + b"0" * 100_000, min_size=100_000))

    def test_partial_ftp_download_is_rejected(self):
        ftp = MagicMock()
        ftp.size.return_value = 20
        ftp.retrbinary.side_effect = lambda command, callback, **kwargs: callback(b"MZ123")
        with patch.object(_common, "FTP") as opening:
            opening.return_value.__enter__.return_value = ftp
            with self.assertRaises(ValueError):
                _common.download_via_ftp("example", "/files", "file.exe", max_size=100)

    def test_invalid_ftp_payload_uses_alternate_host(self):
        good = b"MZ" + b"x" * 100
        with patch.object(_common, "download_via_ftp", side_effect=[b"HTML", good]) as download:
            self.assertEqual(_common.download_release("ftp://a.example/files/file.exe", "file.exe",
                             safe_url_fn=lambda url, name: True, max_size=1000, min_size=100,
                             ftp_hosts=frozenset({"b.example"})), good)
        self.assertEqual(download.call_count, 2)


class CatalogRecoveryTests(unittest.TestCase):
    def test_empty_bpa_page_uses_ftp(self):
        with patch.object(bpa_portal, "_entries_from_index", return_value=[]), patch.object(bpa_portal, "_entries_from_ftp", return_value=[{"name": "BPAMAG0500.exe", "url": "ftp://arpoador.datasus.gov.br/siasus/BPA/BPAMAG0500.exe"}]):
            self.assertEqual(bpa_portal.fetch_bpa_catalog()[0]["name"], "BPAMAG0500.exe")

    def test_ciha_uses_ftp_when_both_pages_fail(self):
        with patch.object(ciha_portal, "fetch_index_entries", side_effect=OSError("offline")), patch.object(ciha_portal, "fetch_ftp_names", return_value=["CIHA02_VER2034.exe"]):
            self.assertEqual(ciha_portal.fetch_ciha02_catalog()[0]["name"], "CIHA02_VER2034.exe")

    def test_empty_cnes_api_uses_ftp(self):
        with patch.object(cnes_portal, "_fetch_json", return_value=[]), patch.object(cnes_portal, "fetch_ftp_names", return_value=["SCNES4850-COMPLETA.ZIP"]):
            self.assertEqual(cnes_portal.fetch_cnes_complete_catalog()[0]["name"], "SCNES4850-COMPLETA.ZIP")

    def test_sihd_version_takes_priority_over_competence(self):
        old = {"name": "SIHD2_2340.exe", "url": "ftp://example/old", "competence": "202608"}
        new = {"name": "SIHD2_2350.exe", "url": "ftp://example/new", "competence": "202607"}
        self.assertEqual(normalize_catalog({"latest": old}, [new])[0]["name"], new["name"])

    def test_withdrawn_sihd_release_is_not_restored_from_saved_catalog(self):
        old = {"name": "SIHD2_2340.exe", "url": "ftp://example/old"}
        valid = {"name": "SIHD2_2330.exe", "url": "ftp://example/valid", "withdrawn_names": [old["name"]]}
        self.assertEqual(normalize_catalog({"latest": old}, [valid])[0]["name"], valid["name"])


class PublicationTests(unittest.TestCase):
    def test_stale_run_keeps_newer_version_and_all_monthly_copies(self):
        old = {"name": "SIA0604.exe", "url": "ftp://example/old"}
        new = {"name": "SIA0605.exe", "url": "ftp://example/new"}
        remote = {"systems": {"sia": {"latest": new}, "bdsia": {"competences": {"202609": {"name": "BDSIA202609b.exe", "url": "ftp://example/new"}}}}}
        local = {"systems": {"sia": {"latest": old}, "bdsia": {"competences": {"201001": {"name": "BDSIA201001b.exe", "url": "ftp://example/old"}}}}}
        result = publish_catalog.merge_catalogs(remote, local)
        self.assertEqual(result["systems"]["sia"]["latest"]["name"], new["name"])
        self.assertEqual(set(result["systems"]["bdsia"]["competences"]), {"202609", "201001"})

    def test_conflicting_publication_reads_new_revision_and_retries(self):
        remote = {"systems": {}}
        current = {"sha": "old", "encoding": "base64", "content": base64.b64encode(json.dumps(remote).encode()).decode()}
        conflict = subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 409")
        local = {"updated_at": "2026-10-01", "systems": {"sia": {"latest": {"name": "SIA0605.exe", "url": "ftp://example/new"}}}}
        with patch.object(publish_catalog, "gh_api", side_effect=[current, conflict, {**current, "sha": "new"}, {}]) as api, patch.object(publish_catalog.time, "sleep"):
            publish_catalog.publish(local, "owner/repo")
        self.assertEqual(api.call_count, 4)
        self.assertEqual(api.call_args.args[1]["sha"], "new")
