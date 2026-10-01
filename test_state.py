import json
import tempfile
import unittest
from pathlib import Path
from catalogs.state import normalize_catalog, atomic_write, CATALOG_LOCK
from concurrent.futures import ThreadPoolExecutor


class CatalogStateTests(unittest.TestCase):
    def test_old_source_cannot_replace_latest_pending_release(self):
        current = {"name": "SIA0604.exe", "url": "ftp://example/SIA0604.exe"}
        latest = {"name": "SIA0605.exe", "url": "ftp://example/SIA0605.exe", "release_date": "2026-09-24"}
        self.assertEqual(normalize_catalog({"current": current, "latest": latest}, [current]), [latest])

    def test_partial_monthly_source_preserves_history_and_newer_revision(self):
        old = {"name": "BDSIA201001b.exe", "competence": "201001", "url": "ftp://example/old"}
        newer = {"name": "BDSIA202609b.exe", "competence": "202609", "url": "ftp://example/new"}
        stale = {**newer, "name": "BDSIA202609a.exe"}
        result = normalize_catalog({"latest": newer, "available_releases": [old, newer]}, [stale], monthly=True)
        self.assertEqual([r["name"] for r in result], [newer["name"], old["name"]])

    def test_numeric_versions_and_missing_dates(self):
        saved = {"latest": {"name": "SIHD2_10000.exe", "url": "ftp://example/new", "release_date": "2026-09-24"}}
        self.assertEqual(normalize_catalog(saved, [{"name": "SIHD2_9999.exe", "url": "ftp://example/old"}])[0]["name"], "SIHD2_10000.exe")
        same = {**saved["latest"], "release_date": None}
        self.assertEqual(normalize_catalog(saved, [same])[0]["release_date"], "2026-09-24")

    def test_atomic_write_replaces_file_and_cleans_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            atomic_write(path, {"systems": {"sia": {"latest": "0605"}}})
            atomic_write(path, {"systems": {"sia": {"latest": "0606"}}})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["systems"]["sia"]["latest"], "0606")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_simultaneous_read_merge_write_keeps_every_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            atomic_write(path, {"systems": {}})
            def update(index):
                with CATALOG_LOCK:
                    snapshot = json.loads(path.read_text(encoding="utf-8"))
                    snapshot["systems"][str(index)] = index
                    atomic_write(path, snapshot)
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(update, range(20)))
            self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))["systems"]), 20)
