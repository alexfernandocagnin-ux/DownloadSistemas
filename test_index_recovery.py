"""Recovery from temporary source failures without hiding incomplete checks."""
import io
import ssl
import unittest
from contextlib import redirect_stdout
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from catalogs import _common
from scripts import sync_catalog


class IndexRecoveryTests(unittest.TestCase):
    URL = "https://sia.datasus.gov.br/versao/listar_ftp_bpa.php"
    PAGE = b'<table><tr><td><a href="ftp://arpoador.datasus.gov.br/siasus/BPA/BPAMAG0500.exe">BPAMAG0500.exe</a></td><td>09-Jul-2026</td></tr></table>'

    def test_temporary_failure_retries_same_https_index_and_keeps_date(self):
        for error in (URLError(TimeoutError("timed out")), ConnectionResetError("reset"),
                      HTTPError(self.URL, 503, "Service Unavailable", {}, None)):
            with self.subTest(error=type(error).__name__), patch.object(_common, "sleep") as sleep, \
                 patch.object(_common, "urlopen", side_effect=[error, io.BytesIO(self.PAGE)]) as opening:
                result = _common.fetch_index_entries(self.URL)
                self.assertEqual(result[0]["release_date"], "2026-07-09")
                self.assertEqual([call.args[0].full_url for call in opening.call_args_list], [self.URL, self.URL])
                sleep.assert_called_once_with(1)

    def test_permanent_http_error_is_not_retried(self):
        with patch.object(_common, "sleep") as sleep, patch.object(_common, "urlopen", \
                side_effect=HTTPError(self.URL, 404, "Not Found", {}, None)) as opening:
            with self.assertRaises(HTTPError):
                _common.fetch_index_entries(self.URL)
            opening.assert_called_once()
            sleep.assert_not_called()

    def test_foreign_certificate_failure_is_not_bypassed_or_retried(self):
        with patch.object(_common, "sleep") as sleep, patch.object(_common, "urlopen", \
                side_effect=URLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))) as opening:
            with self.assertRaises(URLError):
                _common.fetch_index_entries("https://other.example/catalog")
            opening.assert_called_once()
            sleep.assert_not_called()

    def test_oversized_index_is_rejected_without_second_download(self):
        with patch.object(_common, "urlopen", return_value=io.BytesIO(self.PAGE)) as opening:
            with self.assertRaises(ValueError):
                _common.fetch_index_entries(self.URL, max_bytes=10)
            opening.assert_called_once()

    def test_failure_log_preserves_cause_and_old_copy_without_claiming_success(self):
        error = OSError("Nenhuma fonte respondeu")
        error.__cause__ = TimeoutError("servidor não respondeu\nna listagem")
        old = {"latest": {"name": "BPAMAG0500.exe"}, "mirror": {"sha256": "a" * 64},
               "catalog_checked_at": "2026-10-07T20:53:31-03:00"}
        log = io.StringIO()
        with redirect_stdout(log):
            result = sync_catalog.failed(old, {"label": "BPA", "official_page": self.URL},
                                         "2026-10-08T10:00:00-03:00", error)
        self.assertEqual(result["latest"], old["latest"])
        self.assertEqual(result["mirror"], old["mirror"])
        self.assertEqual(result["catalog_checked_at"], old["catalog_checked_at"])
        self.assertEqual(result["catalog_check_error"], "OSError")
        self.assertFalse(result["official_reachable"])
        self.assertIn("TimeoutError: servidor não respondeu na listagem", log.getvalue())
        self.assertEqual(len(log.getvalue().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
