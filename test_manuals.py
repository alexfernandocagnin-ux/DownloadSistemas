"""Busca e entrega das cópias locais verificadas dos manuais."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from catalogs import manuals


class ManualTests(unittest.TestCase):
    def test_library_covers_all_systems_with_unique_ids_and_combined_filters(self):
        self.assertEqual({manual["system"] for manual in manuals.load_manuals()}, set(manuals.SYSTEMS))
        self.assertEqual(len({manual["id"] for manual in manuals.load_manuals()}), len(manuals.load_manuals()))
        result = manuals.filter_manuals("instalacao SCNES", "cnes", "Instalação")
        self.assertTrue(result)
        self.assertTrue(all(item["system"] == "cnes" and item["category"] == "Instalação" for item in result))
        self.assertEqual(manuals.filter_manuals("inexistente"), [])

    def test_manifest_changes_take_effect_without_restarting(self):
        entry = manuals.load_manuals()[0]
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory, "manuals.json")
            with patch.object(manuals, "MANUALS_PATH", manifest):
                manifest.write_text(json.dumps([entry]), encoding="utf-8")
                self.assertEqual(manuals.filter_manuals(), [entry])
                manifest.write_text("[]", encoding="utf-8")
                self.assertEqual(manuals.filter_manuals(), [])
                with self.assertRaises(ValueError):
                    manuals.download_manual(entry["id"])

    def test_every_manual_downloads_with_the_official_servers_offline(self):
        with patch("catalogs._common.urlopen", side_effect=AssertionError("network access")), \
             patch("catalogs._common.FTP", side_effect=AssertionError("FTP access")):
            for manual in manuals.load_manuals():
                with self.subTest(manual=manual["id"]):
                    self.assertIn(manual["format"], ("PDF", "ZIP"))
                    package = manuals.download_manual(manual["id"])
                    self.assertEqual(len(package), manual["size"])
                    self.assertEqual(hashlib.sha256(package).hexdigest(), manual["sha256"])

    def test_missing_corrupt_and_unsafe_copies_are_not_delivered(self):
        pdf = b"%PDF-1.4\nmanual\n%%EOF\n"
        entry = {**manuals.load_manuals()[0], "file": "manual.pdf", "size": len(pdf),
                 "sha256": hashlib.sha256(pdf).hexdigest()}
        with tempfile.TemporaryDirectory() as directory, patch.object(manuals, "MANUALS_DIR", Path(directory)), \
             patch.object(manuals, "load_manuals", return_value=[entry]):
            with self.assertRaises(OSError):
                manuals.download_manual(entry["id"])
            Path(directory, "manual.pdf").write_bytes(pdf)
            self.assertEqual(manuals.download_manual(entry["id"]), pdf)
            Path(directory, "manual.pdf").write_bytes(pdf.replace(b"manual", b"broken"))
            with self.assertRaises(ValueError):
                manuals.download_manual(entry["id"])
            entry["file"] = "../outside.pdf"
            with self.assertRaises(ValueError):
                manuals.download_manual(entry["id"])
        with self.assertRaises(ValueError):
            manuals.download_manual("missing-manual")


if __name__ == "__main__":
    unittest.main()
