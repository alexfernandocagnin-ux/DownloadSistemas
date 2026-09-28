"""Regressões: espelhos quebrados, publicação incompleta e DATASUS indisponível."""

import hashlib
import importlib.util
from ftplib import error_perm
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from catalogs import mirrors, _common, bpa_portal
from scripts import sync_catalog as sync


NAME = "BPAMAG0500.exe"
URL = "ftp://arpoador.datasus.gov.br/siasus/BPA/" + NAME
MIRROR = {"tag": "bpa-latest", "asset_name": NAME,
          "asset_url": f"https://github.com/{mirrors.REPOSITORY}/releases/download/bpa-latest/{NAME}"}
PACKAGE = b"MZ" + b"0" * 100_000


class MirrorTests(unittest.TestCase):
    def test_old_mirror_is_not_used_for_new_version(self):
        self.assertIsNone(mirrors.matching_mirror("BPAMAG0501.exe", MIRROR))

    def test_foreign_repository_is_rejected(self):
        foreign = {**MIRROR, "asset_url": MIRROR["asset_url"].replace(mirrors.REPOSITORY, "other/repository")}
        self.assertIsNone(mirrors.matching_mirror(NAME, foreign))

    def test_error_page_is_not_offered_as_installer(self):
        with patch.object(mirrors, "download_via_http", return_value=b"<html>404</html>"):
            with self.assertRaises(ValueError):
                mirrors.download_mirror(NAME, MIRROR)

    def test_truncated_download_is_rejected(self):
        with patch.object(mirrors, "download_via_http", return_value=PACKAGE):
            with self.assertRaises(ValueError):
                mirrors.download_mirror(NAME, {**MIRROR, "size": len(PACKAGE) + 1})

    def test_corrupt_download_is_rejected(self):
        with patch.object(mirrors, "download_via_http", return_value=PACKAGE):
            with self.assertRaises(ValueError):
                mirrors.download_mirror(NAME, {**MIRROR, "sha256": "0" * 64})

    def test_valid_download_is_returned(self):
        with patch.object(mirrors, "download_via_http", return_value=PACKAGE):
            result = mirrors.download_mirror(NAME, {**MIRROR, "size": len(PACKAGE), "sha256": hashlib.sha256(PACKAGE).hexdigest()})
        self.assertEqual(result, PACKAGE)


class FtpRecoveryTests(unittest.TestCase):
    def test_download_uses_another_official_host_after_outage(self):
        package = b"MZ" + b"0" * 1_000_000
        with patch.object(_common, "download_via_ftp", side_effect=[OSError("offline"), package]) as download:
            self.assertEqual(bpa_portal.download_release({"name": NAME, "url": URL}), package)
        self.assertEqual(download.call_count, 2)
        self.assertNotEqual(download.call_args_list[0].args[0], download.call_args_list[1].args[0])

    def test_ftp_protocol_errors_become_recoverable_errors(self):
        with patch.object(_common, "FTP") as ftp:
            ftp.return_value.__enter__.return_value.retrbinary.side_effect = error_perm("550 not available")
            with self.assertRaises(OSError):
                _common.download_via_ftp("official", "/folder", NAME, max_size=2_000_000)


class SynchronizationTests(unittest.TestCase):
    def setUp(self):
        self.old = {"current": {"name": NAME, "url": URL}, "mirror": MIRROR,
                    "checked_at": "2026-09-20T12:00:00+00:00", "official_reachable": True}
        self.previous = {"systems": {"bpa": self.old}}
        self.config = {**sync.SINGLE_VERSION_SYSTEMS["bpa"], "fetch": lambda: [{"name": NAME, "url": URL}],
                       "download": lambda release: PACKAGE}

    def test_offline_source_preserves_copy_and_confirmation_date(self):
        self.config["fetch"] = lambda: (_ for _ in ()).throw(OSError("offline"))
        result = sync.sync_single_version_system("bpa", self.config, self.previous)
        self.assertEqual(result["mirror"], MIRROR)
        self.assertEqual(result["current"], self.old["current"])
        self.assertEqual(result["last_success_at"], self.old["checked_at"])
        self.assertFalse(result["official_reachable"])

    def test_missing_remote_asset_is_downloaded_again(self):
        with patch.object(sync, "PUBLISH", True), patch.object(sync, "remote_asset", return_value=None), patch.object(sync, "store_package", return_value={**MIRROR, "verified_at": "now"}) as store:
            result = sync.sync_single_version_system("bpa", self.config, self.previous)
        store.assert_called_once()
        self.assertEqual(result["mirror"]["verified_at"], "now")

    def test_failed_upload_never_replaces_previous_version(self):
        self.config["fetch"] = lambda: [{"name": "BPAMAG0501.exe", "url": URL}]
        with patch.object(sync, "store_package", side_effect=ValueError("upload missing")):
            result = sync.sync_single_version_system("bpa", self.config, self.previous)
        self.assertEqual(result["current"], self.old["current"])
        self.assertEqual(result["mirror"], MIRROR)

    def test_local_download_does_not_invent_published_link(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sync, "DIST_DIR", Path(directory)), patch.object(sync, "PUBLISH", False):
            mirror = sync.store_package("bpa", {"name": NAME, "url": URL}, self.config, "bpa-latest")
            self.assertTrue((Path(directory) / "bpa" / NAME).is_file())
        self.assertIsNone(mirror)

    def test_month_tag_comes_from_competence_not_filename_guess(self):
        release = {"name": "BASE_DE_DADOS_CNES_202608.ZIP", "url": "official", "competence": "202608"}
        config = {**sync.COMPETENCE_SYSTEMS["cnes_base"], "fetch": lambda: [release]}
        with patch.object(sync, "store_package", return_value=MIRROR) as store:
            sync.sync_competence_system("cnes_base", config, {})
        self.assertEqual(store.call_args.args[3], "cnes-base-202608")

    def test_older_months_survive_new_catalog_and_failed_download(self):
        old_entry = {"name": "old.exe", "url": "old", "mirror": MIRROR}
        previous = {"systems": {"bdsia": {"competences": {"202601": old_entry}}}}
        config = {**sync.COMPETENCE_SYSTEMS["bdsia"], "fetch": lambda: [{"name": "new.exe", "url": "new", "competence": "202609"}]}
        with patch.object(sync, "store_package", side_effect=OSError("offline")):
            result = sync.sync_competence_system("bdsia", config, previous)
        self.assertEqual(result["competences"]["202601"], old_entry)
        self.assertEqual(result["pending_competences"], ["202609"])


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "Requer Streamlit")
class PortalTests(unittest.TestCase):
    def setUp(self):
        import streamlit as st
        st.cache_data.clear()

    def app(self):
        from streamlit.testing.v1 import AppTest
        return AppTest.from_file(str(Path(__file__).parent / "app.py"), default_timeout=20)

    def test_home_opens_without_any_official_request(self):
        with patch("catalogs.bpa_portal.fetch_bpa_catalog", side_effect=AssertionError("official request")):
            app = self.app().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.checkbox[0].value)
        self.assertTrue(app.button)

    def test_broken_mirror_falls_back_without_redirect(self):
        with patch("catalogs.mirrors.download_via_http", side_effect=OSError("404")), patch("catalogs.bpa_portal.download_release", return_value=PACKAGE) as official:
            app = self.app().run()
            app.button[0].click().run()
        self.assertFalse(app.exception)
        official.assert_called_once()
        self.assertTrue(app.get("download_button"))
        self.assertTrue(app.warning)

    def test_both_sources_offline_show_error_without_crashing(self):
        with patch("catalogs.mirrors.download_via_http", side_effect=OSError("404")), patch("catalogs.sia_portal.download_release", side_effect=OSError("offline")):
            app = self.app().run()
            app.button[2].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.error)


if __name__ == "__main__":
    unittest.main()
