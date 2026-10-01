"""Regressões da revisão complementar de integridade e publicação."""
import io
import hashlib
import os
import tempfile
from pathlib import Path
import unittest
import zipfile
from unittest.mock import Mock, patch

from catalogs import _common, mirrors, cnes_portal
from scripts import sync_catalog as sync
from catalogs.state import normalize_catalog
from scripts.publish_catalog import merge_catalogs


class IntegrityReviewTests(unittest.TestCase):
    def test_malformed_official_urls_are_rejected(self):
        for url in ("https://[broken", None, 123):
            with self.subTest(url=url):
                self.assertFalse(cnes_portal.safe_url(url, "file.zip"))
                self.assertFalse(_common.safe_official_url(url, "file.zip"))

    def test_github_commands_have_bounded_timeout(self):
        with patch.object(sync.subprocess, "run") as run:
            sync.gh("release", "view", "tag")
            self.assertEqual(run.call_args.kwargs["timeout"], 120)
            sync.gh("release", "upload", "tag", "file")
            self.assertEqual(run.call_args.kwargs["timeout"], 600)

    def test_changed_remote_digest_is_not_reconfirmed(self):
        mirror = {"asset_name": "file.exe", "asset_url": "https://example/file.exe", "tag": "tag", "size": 100_000, "sha256": "a" * 64}
        asset = {"size": 100_000, "digest": "sha256:" + "b" * 64}
        with patch.object(sync, "PUBLISH", True), patch.object(sync, "remote_asset", return_value=asset):
            self.assertIsNone(sync.confirmed_previous({"name": "file.exe", "mirror": mirror}))

    def test_changed_digest_forces_source_download_instead_of_recovery(self):
        name = "file.exe"
        package = b"MZ" + b"0" * 100_000
        asset = {"name": name, "url": "https://example/file.exe", "size": len(package), "digest": "sha256:" + "b" * 64}
        published = {**asset, "digest": "sha256:" + hashlib.sha256(package).hexdigest()}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"GITHUB_REPOSITORY": mirrors.REPOSITORY}), patch.object(sync, "DIST_DIR", Path(directory)), patch.object(sync, "PUBLISH", True), patch.object(sync, "remote_asset", side_effect=[asset, published]), patch.object(sync, "gh"), patch.object(sync, "probe_mirror") as probe:
            download = Mock(return_value=package)
            result = sync.store_package("test", {"name": name, "url": "source"}, {"download": download}, "tag", expected_sha256="a" * 64)
            download.assert_called_once()
            probe.assert_not_called()
            self.assertEqual(result["sha256"], hashlib.sha256(package).hexdigest())

    def test_invalid_range_cannot_confirm_large_mirror(self):
        name = "file.exe"
        mirror = {"asset_name": name, "asset_url": f"https://github.com/{mirrors.REPOSITORY}/releases/download/test/{name}", "size": 100_000}
        response = io.BytesIO(b"MZ")
        response.headers = {"Content-Range": "bytes 100-101/100000"}
        with patch.object(mirrors, "urlopen", return_value=response), self.assertRaises(ValueError):
            mirrors.probe_mirror(name, mirror)

    def test_zip_with_valid_directory_but_corrupt_member_is_rejected(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("data.txt", b"important data" * 10_000)
        payload = bytearray(output.getvalue())
        payload[100] ^= 1
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(payload)))
        self.assertFalse(_common.looks_like_zip(bytes(payload), min_size=100_000))

    def test_malformed_mirror_url_does_not_crash_portal(self):
        self.assertIsNone(mirrors.matching_mirror("file.exe", {
            "asset_name": "file.exe", "asset_url": "https://[broken",
        }))

    def test_mirror_without_total_size_is_not_confirmed(self):
        name = "file.exe"
        mirror = {"asset_name": name, "asset_url": f"https://github.com/{mirrors.REPOSITORY}/releases/download/test/{name}", "size": 100_000}
        response = io.BytesIO(b"MZ")
        response.headers = {}
        with patch.object(mirrors, "urlopen", return_value=response):
            with self.assertRaises(ValueError):
                mirrors.probe_mirror(name, mirror)

    def test_withdrawal_survives_later_stale_catalog(self):
        withdrawn = {"name": "SIHD2_2340.exe", "url": "ftp://example/old"}
        valid = {"name": "SIHD2_2330.exe", "url": "ftp://example/valid", "withdrawn_names": [withdrawn["name"]]}
        result = normalize_catalog({"latest": valid, "current": withdrawn}, [withdrawn])
        self.assertEqual(result[0]["name"], valid["name"])

    def test_publisher_does_not_resurrect_withdrawn_mirror(self):
        withdrawn = {"name": "SIHD2_2340.exe", "url": "ftp://example/old"}
        valid = {"name": "SIHD2_2330.exe", "url": "ftp://example/valid", "withdrawn_names": [withdrawn["name"]]}
        remote = {"systems": {"sihd2": {"latest": valid, "catalog_checked_at": "2026-10-01", "current": withdrawn}}}
        local = {"systems": {"sihd2": {"latest": withdrawn, "current": withdrawn, "catalog_checked_at": "2026-09-30"}}}
        result = merge_catalogs(remote, local)["systems"]["sihd2"]
        self.assertEqual(result["latest"]["name"], valid["name"])
        self.assertNotIn("current", result)


if __name__ == "__main__":
    unittest.main()
