"""Verificações da busca e dos downloads da biblioteca oficial."""
import io
import unittest
import zipfile
from unittest.mock import patch

from catalogs import manuals


class ManualTests(unittest.TestCase):
    def test_library_covers_all_systems_with_unique_ids_and_combined_filters(self):
        self.assertEqual({manual["system"] for manual in manuals.MANUALS}, set(manuals.SYSTEMS))
        self.assertEqual(len({manual["id"] for manual in manuals.MANUALS}), len(manuals.MANUALS))
        result = manuals.filter_manuals("instalacao SCNES", "cnes", "Instalação")
        self.assertTrue(result)
        self.assertTrue(all(item["system"] == "cnes" and item["category"] == "Instalação" for item in result))
        self.assertEqual(manuals.filter_manuals("inexistente"), [])

    def test_only_valid_pdf_or_zip_is_delivered(self):
        pdf = b"%PDF-1.4\nmanual\n%%EOF\n"
        with patch.object(manuals, "download_via_ftp", return_value=pdf) as download:
            self.assertEqual(manuals.download_manual("bpa-operacao"), pdf)
            self.assertEqual(download.call_args.args[:2], ("arpoador.datasus.gov.br", "/siasus/Documentos/BPA"))
        for payload in (b"<html>erro</html>", b"%PDF-1.4\ntruncated"):
            with patch.object(manuals, "download_via_ftp", return_value=payload), self.assertRaises(ValueError):
                manuals.download_manual("bpa-operacao")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("manual.pdf", pdf)
        with patch.object(manuals, "download_via_http", return_value=output.getvalue()):
            self.assertEqual(manuals.download_manual("cnes-instalacao"), output.getvalue())
        with patch.object(manuals, "download_via_http", return_value=b"PKtruncated"), self.assertRaises(ValueError):
            manuals.download_manual("cnes-instalacao")

    def test_foreign_download_host_is_rejected_before_network_access(self):
        entry = {**manuals.MANUALS[0], "url": "ftp://example.com/siasus/Documentos/BPA/Manual_Operacional_BPA.pdf"}
        with patch.object(manuals, "MANUALS", [entry]), patch.object(manuals, "download_via_ftp") as download:
            with self.assertRaises(ValueError):
                manuals.download_manual(entry["id"])
            download.assert_not_called()
        with self.assertRaises(ValueError):
            manuals.download_manual("ciha02-operacao")


if __name__ == "__main__":
    unittest.main()
