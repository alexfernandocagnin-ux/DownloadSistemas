"""Automatic updates: clocks, isolation, transfer limits and catalog recovery."""
import io
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from catalogs import _common, snapshot
from catalogs.mirrors import REPOSITORY
from catalogs.state import merge_catalogs
from scripts import sync_catalog as sync

OLD_TIME = "2026-10-06T10:00:00+00:00"
NEW_TIME = "2026-10-06T12:00:00+00:00"
NAME = "BPAMAG0500.exe"
RELEASE = {"name": NAME, "url": "ftp://example/" + NAME}
MIRROR = {"tag": "bpa-latest", "asset_name": NAME,
          "asset_url": f"https://github.com/{REPOSITORY}/releases/download/bpa-latest/{NAME}",
          "verified_at": NEW_TIME}


class AutomaticRunTests(unittest.TestCase):
    def setUp(self):
        modes = patch.multiple(sync, PUBLISH=False, CATALOG_ONLY=False, MIRROR_ONLY=False)
        modes.start()
        self.addCleanup(modes.stop)

    def run_catalog(self, previous, singles, monthly, arguments):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(previous), encoding="utf-8")
            stack.enter_context(patch.object(sync, "CATALOG_PATH", path))
            stack.enter_context(patch.object(sync, "SINGLE_VERSION_SYSTEMS", singles))
            stack.enter_context(patch.object(sync, "COMPETENCE_SYSTEMS", monthly))
            stack.enter_context(patch.object(sync, "now", return_value=NEW_TIME))
            stack.enter_context(patch("sys.argv", ["sync_catalog.py", *arguments]))
            stack.enter_context(patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""}))
            error = None
            try:
                sync.main()
            except SystemExit as exc:
                error = exc
            return json.loads(path.read_text(encoding="utf-8")), error

    def test_disabled_cnes_base_is_preserved_without_fetch_or_download(self):
        disabled = sync.COMPETENCE_SYSTEMS["cnes_base"]
        self.assertFalse(disabled["enabled"])
        fetch = MagicMock(side_effect=AssertionError("removed dataset"))
        archive = {"latest": {"name": "BASE_DE_DADOS_CNES_202608.ZIP", "url": "old"}}
        config = {"label": "BPA", "official_page": "official", "fetch": lambda: [RELEASE]}
        result, error = self.run_catalog({"systems": {"cnes_base": archive}}, {"bpa": config},
                                         {"cnes_base": {**disabled, "fetch": fetch}}, ["--catalog-only"])
        self.assertIsNone(error)
        fetch.assert_not_called()
        self.assertEqual(result["systems"]["cnes_base"], archive)
        self.assertEqual(result["last_check"]["total"], 1)

    def test_all_sources_offline_records_failure_without_fresh_success_time(self):
        fetch = MagicMock(side_effect=OSError("offline"))
        old = {"latest": RELEASE, "catalog_checked_at": OLD_TIME, "mirror": MIRROR}
        config = {"label": "BPA", "official_page": "official", "fetch": fetch}
        result, error = self.run_catalog({"updated_at": OLD_TIME, "systems": {"bpa": old}},
                                         {"bpa": config}, {}, ["--catalog-only"])
        self.assertIsNotNone(error)
        self.assertEqual(result["updated_at"], OLD_TIME)
        self.assertEqual(result["last_check"]["completed_at"], NEW_TIME)
        self.assertEqual(result["last_check"]["succeeded"], 0)
        self.assertEqual(result["last_check"]["failed_systems"], ["bpa"])
        self.assertEqual(result["systems"]["bpa"]["mirror"], MIRROR)

    def test_first_run_with_no_source_never_claims_successful_verification(self):
        config = {"label": "BPA", "official_page": "official", "fetch": lambda: []}
        result, error = self.run_catalog({"systems": {}}, {"bpa": config}, {}, ["--catalog-only"])
        self.assertIsNotNone(error)
        self.assertEqual(result["updated_at"], "")
        self.assertEqual(result["last_check"]["succeeded"], 0)

    def test_partial_query_keeps_failed_source_and_counts_success(self):
        old = {"latest": RELEASE, "catalog_checked_at": OLD_TIME}
        good = {"label": "BPA", "official_page": "official", "fetch": lambda: [RELEASE]}
        bad = {"label": "SIA", "official_page": "official", "fetch": lambda: []}
        result, error = self.run_catalog({"systems": {"sia": old}}, {"bpa": good, "sia": bad}, {}, ["--catalog-only"])
        self.assertIsNone(error)
        self.assertEqual(result["last_check"]["succeeded"], 1)
        self.assertEqual(result["last_check"]["failed_systems"], ["sia"])
        self.assertEqual(result["systems"]["sia"]["catalog_checked_at"], OLD_TIME)

    def test_mirror_only_never_fetches_or_updates_source_verification_time(self):
        old = {"latest": RELEASE, "current": RELEASE, "mirror": MIRROR,
               "catalog_checked_at": OLD_TIME, "official_reachable": False, "catalog_check_error": "OSError"}
        config = {"label": "BPA", "official_page": "official", "tag": "bpa-latest",
                  "fetch": MagicMock(side_effect=AssertionError("unnecessary source query"))}
        with patch.object(sync, "MIRROR_ONLY", True), patch.object(sync, "confirmed_previous", return_value=MIRROR):
            result = sync.sync_single_version_system("bpa", config, {"systems": {"bpa": old}})
        config["fetch"].assert_not_called()
        self.assertEqual(result["catalog_checked_at"], OLD_TIME)
        self.assertFalse(result["official_reachable"])
        self.assertEqual(result["catalog_check_error"], "OSError")
        self.assertNotIn("_announcements", result)

    def test_missing_saved_catalog_in_mirror_job_does_not_fake_a_source_query(self):
        config = {"label": "BPA", "official_page": "official"}
        with patch.object(sync, "MIRROR_ONLY", True):
            result = sync.sync_single_version_system("bpa", config, {})
        self.assertNotIn("catalog_checked_at", result)
        self.assertNotIn("catalog_attempt_at", result)
        self.assertEqual(result["download_error"], "ValueError")

    def monthly(self, months):
        return [{"name": f"BDSIA{month}a.exe", "url": "official", "competence": month} for month in months]

    def test_missing_historical_file_cooldown_allows_older_files_to_advance(self):
        releases = self.monthly(["202609", "201101", "201001"])
        previous = {"systems": {"bdsia": {"competences": {"202609": releases[0] | {"mirror": {**MIRROR, "asset_name": releases[0]["name"]}}},
                    "download_failures": {"201101": {"name": releases[1]["name"], "retry_after": "2099-01-01"}}}}}
        config = {"label": "BDSIA", "official_page": "official", "fetch": lambda: releases}
        with patch.object(sync, "store_package", return_value=MIRROR) as store:
            result = sync.sync_competence_system("bdsia", config, previous)
        self.assertEqual(store.call_count, 1)
        self.assertEqual(store.call_args.args[1]["competence"], "201001")
        self.assertEqual(len(result["available_releases"]), 3)

    def test_latest_file_retries_even_with_a_historical_cooldown(self):
        releases = self.monthly(["202609"])
        previous = {"systems": {"bdsia": {"download_failures": {"202609": {
                    "name": releases[0]["name"], "retry_after": "2099-01-01"}}}}}
        config = {"label": "BDSIA", "official_page": "official", "fetch": lambda: releases}
        with patch.object(sync, "store_package", return_value=MIRROR) as store:
            result = sync.sync_competence_system("bdsia", config, previous)
        store.assert_called_once()
        self.assertFalse(result["download_failures"])

    def test_time_budget_preserves_index_and_stops_starting_more_packages(self):
        releases = self.monthly(["202609", "201001"])
        config = {"label": "BDSIA", "official_page": "official", "fetch": lambda: releases}
        with patch.object(sync, "monotonic", side_effect=[0, 0, 500]), patch.object(sync, "store_package", return_value=MIRROR) as store:
            result = sync.sync_competence_system("bdsia", config, {})
        store.assert_called_once()
        self.assertEqual(result["available_releases"], releases)

    def test_failed_attempt_is_saved_before_next_package(self):
        release = self.monthly(["202609"])
        config = {"label": "BDSIA", "official_page": "official", "fetch": lambda: release}
        progress = []
        with patch.object(sync, "store_package", side_effect=TimeoutError("slow")):
            sync.sync_competence_system("bdsia", config, {}, lambda key, info: progress.append(info))
        self.assertIn("202609", progress[-1]["download_failures"])


class DeadlineTests(unittest.TestCase):
    def test_http_continuous_transfer_cannot_bypass_total_deadline(self):
        response = io.BytesIO(b"MZ123")
        response.headers = {}
        with patch.object(_common, "urlopen", return_value=response), patch.object(_common, "monotonic", side_effect=[0, 301]):
            with self.assertRaises(TimeoutError):
                _common.download_via_http("https://example/file", NAME, max_size=100)

    def test_ftp_continuous_transfer_cannot_bypass_total_deadline(self):
        ftp = MagicMock()
        ftp.size.return_value = 5
        ftp.retrbinary.side_effect = lambda command, callback, **kwargs: callback(b"MZ123")
        with patch.object(_common, "FTP") as opening, patch.object(_common, "monotonic", side_effect=[0, 301]):
            opening.return_value.__enter__.return_value = ftp
            with self.assertRaises(TimeoutError):
                _common.download_via_ftp("example", "/files", NAME, max_size=100)


class PublishedCatalogTests(unittest.TestCase):
    def test_remote_outage_leaves_a_local_fallback_available(self):
        with patch.object(snapshot, "urlopen", side_effect=OSError("offline")):
            self.assertIsNone(snapshot.read_published_catalog())

    def test_invalid_or_oversized_remote_catalog_is_rejected(self):
        for payload in [b"<html>404</html>", b"[]", b'{"systems":[]}', b'{"systems":{"bpa":[]}}', b'{"systems":{"bpa":{"latest":"bad"}}}', b'{"systems":{},"last_check":[]}', b"x" * (snapshot.MAX_CATALOG_BYTES + 1)]:
            with self.subTest(payload=payload[:35]), patch.object(snapshot, "urlopen", return_value=io.BytesIO(payload)):
                self.assertIsNone(snapshot.read_published_catalog())

    def test_published_catalog_is_read_without_authentication(self):
        catalog = {"systems": {"bpa": {"latest": RELEASE}}}
        with patch.object(snapshot, "urlopen", return_value=io.BytesIO(json.dumps(catalog).encode())) as opening:
            self.assertEqual(snapshot.read_published_catalog(), catalog)
        self.assertEqual(opening.call_args.kwargs["timeout"], 10)
        self.assertNotIn("Authorization", dict(opening.call_args.args[0].header_items()))

    def test_changed_mirror_refreshes_page_even_without_new_source_timestamp(self):
        before = {"updated_at": OLD_TIME, "systems": {"bpa": {"latest": RELEASE}}}
        after = {"updated_at": OLD_TIME, "systems": {"bpa": {"latest": RELEASE, "mirror": MIRROR}}}
        self.assertNotEqual(snapshot.catalog_revision(before), snapshot.catalog_revision(after))

    def test_later_failed_query_preserves_newer_confirmed_version_and_date(self):
        newer_release = {**RELEASE, "name": "BPAMAG0501.exe"}
        remote = {"systems": {"bpa": {"latest": newer_release, "catalog_checked_at": OLD_TIME}}}
        local = {"systems": {"bpa": {"latest": RELEASE, "catalog_checked_at": "2026-10-05T10:00:00+00:00",
                  "catalog_attempt_at": NEW_TIME, "catalog_check_error": "OSError", "official_reachable": False}}}
        merged = merge_catalogs(remote, local)["systems"]["bpa"]
        self.assertEqual(merged["latest"]["name"], newer_release["name"])
        self.assertEqual(merged["catalog_checked_at"], OLD_TIME)
        self.assertFalse(merged["official_reachable"])

    def test_new_source_url_for_the_same_version_survives_stale_local_metadata(self):
        remote = {"systems": {"bpa": {"catalog_checked_at": NEW_TIME, "latest": {**RELEASE, "url": "ftp://new/source"}}}}
        local = {"systems": {"bpa": {"catalog_checked_at": OLD_TIME, "latest": RELEASE}}}
        self.assertEqual(merge_catalogs(remote, local)["systems"]["bpa"]["latest"]["url"], "ftp://new/source")

    def test_newest_manual_or_automatic_check_is_kept_and_merge_is_stable(self):
        remote = {"updated_at": OLD_TIME, "systems": {"bpa": {"latest": RELEASE}},
                  "last_check": {"completed_at": OLD_TIME, "source": "automatic"}}
        local = {"systems": {}, "last_check": {"completed_at": NEW_TIME, "source": "manual"}}
        merged = merge_catalogs(remote, local)
        self.assertEqual(merged["last_check"], local["last_check"])
        self.assertEqual(merge_catalogs(remote, merged), merged)

    def test_mirror_cooldown_is_not_lost_to_a_later_source_only_query(self):
        failure = {"name": "BDSIA201001a.exe", "attempted_at": NEW_TIME, "retry_after": "2026-10-07"}
        remote = {"systems": {"bdsia": {"catalog_checked_at": "2026-10-06T13:00:00+00:00"}}}
        local = {"systems": {"bdsia": {"catalog_checked_at": OLD_TIME, "download_failures": {"201001": failure}}}}
        self.assertEqual(merge_catalogs(remote, local)["systems"]["bdsia"]["download_failures"]["201001"], failure)

    def test_interface_reports_partial_query_or_delayed_automation(self):
        current = datetime(2026, 10, 6, 14, tzinfo=timezone.utc)
        partial = {"last_check": {"completed_at": NEW_TIME, "succeeded": 10, "total": 12}}
        self.assertIn("10 de 12", snapshot.verification_notice(partial, current))
        self.assertIn("atrasada", snapshot.verification_notice({"updated_at": OLD_TIME}, current))
        self.assertIsNone(snapshot.verification_notice({"updated_at": NEW_TIME}, current))


if __name__ == "__main__":
    unittest.main()
