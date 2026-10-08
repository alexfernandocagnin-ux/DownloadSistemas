"""Regressões da recuperação das listagens SIA, sem acessar a rede."""

import unittest
from unittest.mock import patch

from catalogs import apac_portal, bpa_portal, fpo_portal, sia_portal


SOURCES = (
    (bpa_portal, "fetch_bpa_catalog", "BPAMAG0500.exe", "APACMAG_0402.exe"),
    (apac_portal, "fetch_apac_catalog", "APACMAG_0402.exe", "BPAMAG0500.exe"),
    (sia_portal, "fetch_sia_catalog", "SIA0605.exe", "BDSIA202609a.exe"),
    (sia_portal, "fetch_bdsia_catalog", "BDSIA202609a.exe", "SIA0605.exe"),
    (fpo_portal, "fetch_fpo_installer_catalog", "FPOMAG_Instalador_0100.exe", "FPOMAG_Atualiza_0303.exe"),
    (fpo_portal, "fetch_fpo_update_catalog", "FPOMAG_Atualiza_0303.exe", "FPOMAG_Instalador_0100.exe"),
)


class SourceRecoveryTests(unittest.TestCase):
    def test_ftp_directories_match_the_paths_already_confirmed_in_the_catalog(self):
        self.assertEqual(sia_portal.FTP_DIRECTORY, "/siasus/sia")
        self.assertEqual(fpo_portal.FTP_DIRECTORY, "/siasus/fpo")

    def test_descriptive_labels_use_actual_href_filename_and_preserve_date(self):
        for module, fetch_name, name, _ in SOURCES:
            with self.subTest(source=fetch_name):
                # Queries, fragments and percent encoding must not become part of the filename.
                encoded_name = f"%{ord(name[0]):02X}" + name[1:]
                url = f"https://sia.datasus.gov.br/files/{encoded_name}?download=1#arquivo"
                entries = [{"name": "Baixar a versão atual", "url": url,
                            "size": 1234, "release_date": "2026-10-01"}]
                with patch.object(module, "fetch_index_entries", return_value=entries), \
                        patch.object(module, "fetch_ftp_names", side_effect=AssertionError("unnecessary FTP")):
                    releases = getattr(module, fetch_name)()
                self.assertEqual(releases[0]["name"], name)
                self.assertEqual(releases[0]["url"], url)
                self.assertEqual(releases[0]["size"], 1234)
                self.assertEqual(releases[0]["release_date"], "2026-10-01")

    def test_malformed_link_does_not_hide_a_valid_link(self):
        for module, fetch_name, name, _ in SOURCES:
            with self.subTest(source=fetch_name):
                entries = [{"name": name, "url": "https://[broken"},
                           {"name": "Download", "url": f"https://sia.datasus.gov.br/files/{name}"}]
                with patch.object(module, "fetch_index_entries", return_value=entries), \
                        patch.object(module, "fetch_ftp_names", side_effect=AssertionError("unnecessary FTP")):
                    releases = getattr(module, fetch_name)()
                self.assertEqual([release["name"] for release in releases], [name])

    def test_rejected_index_links_recover_from_official_ftp(self):
        for module, fetch_name, name, _ in SOURCES:
            with self.subTest(source=fetch_name):
                entries = [{"name": name, "url": f"https://attacker.example/{name}"}]
                with patch.object(module, "fetch_index_entries", return_value=entries), \
                        patch.object(module, "fetch_ftp_names", return_value=[name]) as listing:
                    releases = getattr(module, fetch_name)()
                self.assertEqual(releases[0]["name"], name)
                self.assertEqual(releases[0]["url"],
                                 f"ftp://arpoador.datasus.gov.br{module.FTP_DIRECTORY}/{name}")
                listing.assert_called_once_with("arpoador.datasus.gov.br", module.FTP_DIRECTORY)

    def _assert_second_host_recovers(self, first_files):
        for module, fetch_name, name, other_name in SOURCES:
            with self.subTest(source=fetch_name):
                def list_names(host, directory):
                    return first_files(other_name) if host == "arpoador.datasus.gov.br" else [name]

                with patch.object(module, "fetch_index_entries", side_effect=OSError("index offline")), \
                        patch.object(module, "fetch_ftp_names", side_effect=list_names) as listing:
                    releases = getattr(module, fetch_name)()
                self.assertEqual(releases[0]["name"], name)
                self.assertEqual(releases[0]["url"], f"ftp://ftp.datasus.gov.br{module.FTP_DIRECTORY}/{name}")
                self.assertEqual([call.args for call in listing.call_args_list],
                                 [(host, module.FTP_DIRECTORY) for host in sorted(module.FTP_HOSTS)])

    def test_empty_first_ftp_host_does_not_block_second_host(self):
        self._assert_second_host_recovers(lambda _: [])

    def test_first_ftp_host_with_another_family_does_not_block_second_host(self):
        self._assert_second_host_recovers(lambda other_name: [other_name, "LERNOTAS.TXT"])

    def test_first_ftp_host_timeout_does_not_block_second_host(self):
        for module, fetch_name, name, _ in SOURCES:
            with self.subTest(source=fetch_name):
                with patch.object(module, "fetch_index_entries", side_effect=OSError("index offline")), \
                        patch.object(module, "fetch_ftp_names", side_effect=[TimeoutError("timeout"), [name]]) as listing:
                    releases = getattr(module, fetch_name)()
                self.assertEqual(releases[0]["name"], name)
                self.assertEqual(listing.call_count, 2)

    def test_all_ftp_failures_preserve_the_transport_cause(self):
        for module, fetch_name, _, _ in SOURCES:
            with self.subTest(source=fetch_name):
                last_error = TimeoutError("last FTP timed out")
                with patch.object(module, "fetch_index_entries", side_effect=TimeoutError("index timed out")), \
                        patch.object(module, "fetch_ftp_names", side_effect=[OSError("first FTP offline"), last_error]), \
                        self.assertRaises(OSError) as failure:
                    getattr(module, fetch_name)()
                self.assertIs(failure.exception.__cause__, last_error)

    def test_empty_responsive_sources_report_no_release(self):
        for module, fetch_name, _, _ in SOURCES:
            with self.subTest(source=fetch_name):
                with patch.object(module, "fetch_index_entries", return_value=[]), \
                        patch.object(module, "fetch_ftp_names", return_value=[]) as listing, \
                        self.assertRaises(ValueError):
                    getattr(module, fetch_name)()
                self.assertEqual(listing.call_count, 2)


if __name__ == "__main__":
    unittest.main()
