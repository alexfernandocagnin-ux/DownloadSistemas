"""Conferência semanal dos manuais, sem consultar as fontes reais."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
import check_manuals  # noqa: E402

FILE = {"id": "bpa", "title": "Manual BPA", "url": "ftp://host/dir/a.pdf", "sha256": "abc"}
SHARED = {"id": "bpa-copia", "title": "Mesmo arquivo", "url": "ftp://host/dir/a.pdf", "sha256": "abc"}
WIKI = {"id": "wiki", "title": "Guia Wiki", "url": "https://wiki.saude.gov.br/sia/index.php/P",
        "source_format": "Online", "copied_at": "2026-10-07T00:00:00+00:00"}


class CheckManualsTests(unittest.TestCase):
    def run_check(self, sha="abc", edited=datetime(2026, 10, 1, tzinfo=timezone.utc), fail=()):
        calls = []

        def fetch_sha(url):
            calls.append(url)
            if "sha" in fail:
                raise OSError("offline")
            return sha

        def fetch_edit(url):
            if "wiki" in fail:
                raise TimeoutError()
            return edited

        result = check_manuals.check([FILE, SHARED, WIKI], fetch_sha256=fetch_sha, fetch_last_edit=fetch_edit)
        return result, calls

    def test_unchanged_sources_report_nothing_and_download_shared_files_once(self):
        (changed, unreachable), calls = self.run_check()
        self.assertEqual((changed, unreachable), ([], []))
        self.assertEqual(calls, [FILE["url"]])
        self.assertIn("Nenhum dos 3 manuais", check_manuals.report(changed, unreachable, 3))

    def test_new_file_and_newer_wiki_edit_are_reported(self):
        (changed, _), _ = self.run_check(sha="outro", edited=datetime(2026, 10, 9, tzinfo=timezone.utc))
        self.assertEqual([m["id"] for m, _ in changed], ["bpa", "bpa-copia", "wiki"])
        self.assertIn("3 de 3 manuais mudaram", check_manuals.report(changed, [], 3))

    def test_excerpt_copies_are_compared_with_the_original_source_hash(self):
        excerpt = {**FILE, "id": "trecho", "url": "https://host/inteiro.pdf", "sha256": "trecho", "source_sha256": "inteiro"}
        changed, _ = check_manuals.check([excerpt], fetch_sha256=lambda url: "inteiro")
        self.assertEqual(changed, [])
        changed, _ = check_manuals.check([excerpt], fetch_sha256=lambda url: "nova-edicao")
        self.assertEqual([m["id"] for m, _ in changed], ["trecho"])

    def test_offline_sources_are_not_reported_as_changes(self):
        (changed, unreachable), _ = self.run_check(fail=("sha", "wiki"))
        self.assertEqual(changed, [])
        self.assertEqual([m["id"] for m, _ in unreachable], ["bpa", "bpa-copia", "wiki"])
        self.assertIn("Não foi possível conferir 3", check_manuals.report(changed, unreachable, 3))


if __name__ == "__main__":
    unittest.main()
