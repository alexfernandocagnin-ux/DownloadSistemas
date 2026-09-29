"""Testes dos catálogos de download, sem acessar a rede nem executar nada."""

import io
import unittest
from unittest.mock import patch

from catalogs import _common, bpa_portal, cnes_portal, fpo_portal, sia_portal, sigtap_portal, sihd_portal


class CommonCatalogTests(unittest.TestCase):
    def test_table_parser_reads_official_publication_date(self):
        page = b"""
        <table>
          <tr><th>Descricao</th><th>Data</th><th>Tamanho</th></tr>
          <tr><td><a href="/files/BPAMAG0500.exe">BPAMAG0500.exe</a></td><td>09-Jul-2026</td><td>7,4 MB</td></tr>
        </table>
        """
        with patch("catalogs._common.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = io.BytesIO(page)
            entries = _common.fetch_index_entries("https://sia.datasus.gov.br/versao/listar_ftp_bpa.php")
        self.assertEqual(entries[0]["name"], "BPAMAG0500.exe")
        self.assertEqual(entries[0]["release_date"], "2026-07-09")

    def test_date_parser_accepts_official_month_name_and_numeric_dates(self):
        self.assertEqual(_common.parse_release_date("25-Sep-2026"), "2026-09-25")
        self.assertEqual(_common.parse_release_date("24/09/2026"), "2026-09-24")
        self.assertIsNone(_common.parse_release_date("sem data"))


class SiaPortalTests(unittest.TestCase):
    def test_bdsia_and_sia_are_split_from_the_shared_index(self):
        entries = [
            ("BDSIA202608b.exe", "ftp://ftp.datasus.gov.br/siasus/SIA/BDSIA202608b.exe"),
            ("BDSIA202607a.exe", "ftp://ftp.datasus.gov.br/siasus/SIA/BDSIA202607a.exe"),
            ("SIA0604.exe", "ftp://ftp.datasus.gov.br/siasus/SIA/SIA0604.exe"),
            ("INSTSIA0200.exe", "ftp://ftp.datasus.gov.br/siasus/SIA/INSTSIA0200.exe"),
            ("LERNOTAS.TXT", "ftp://ftp.datasus.gov.br/siasus/SIA/LERNOTAS.TXT"),
        ]
        with patch("catalogs.sia_portal._entries_from_index", return_value=[
            {"name": name, "url": url, "size": None, "release_date": "2026-09-24"} for name, url in entries
        ]):
            bdsia = sia_portal.fetch_bdsia_catalog()
            sia = sia_portal.fetch_sia_catalog()
        self.assertEqual([item["name"] for item in bdsia], ["BDSIA202608b.exe", "BDSIA202607a.exe"])
        self.assertEqual(bdsia[0]["competence"], "202608")
        self.assertEqual(bdsia[0]["release_date"], "2026-09-24")
        self.assertEqual([item["name"] for item in sia], ["SIA0604.exe", "INSTSIA0200.exe"])

    def test_rejects_links_to_unofficial_hosts(self):
        with patch("catalogs.sia_portal._entries_from_index", return_value=[
            {"name": "BDSIA202608b.exe", "url": "https://attacker.example/BDSIA202608b.exe", "size": None},
        ]):
            with self.assertRaises(ValueError):
                sia_portal.fetch_bdsia_catalog()

    def test_falls_back_to_ftp_when_index_page_is_unreachable(self):
        with (
            patch("catalogs.sia_portal._entries_from_index", side_effect=OSError("timeout")),
            patch("catalogs.sia_portal.fetch_ftp_names", return_value=["SIA0604.exe", "LERNOTAS.TXT"]),
        ):
            releases = sia_portal.fetch_sia_catalog()
        self.assertEqual([item["name"] for item in releases], ["SIA0604.exe"])


class FpoPortalTests(unittest.TestCase):
    def test_installer_and_updates_are_separated_and_latest_update_is_first(self):
        entries = [
            {"name": "FPOMAG_Instalador_0100.exe", "url": "ftp://ftp.datasus.gov.br/siasus/FPO/FPOMAG_Instalador_0100.exe", "size": None},
            {"name": "FPOMAG_Atualiza_0301.exe", "url": "ftp://ftp.datasus.gov.br/siasus/FPO/FPOMAG_Atualiza_0301.exe", "size": None},
            {"name": "FPOMAG_Atualiza_0302.exe", "url": "ftp://ftp.datasus.gov.br/siasus/FPO/FPOMAG_Atualiza_0302.exe", "size": None, "release_date": "2026-09-24"},
            {"name": "FPO_Leiame.txt", "url": "ftp://ftp.datasus.gov.br/siasus/FPO/FPO_Leiame.txt", "size": None},
        ]
        with patch("catalogs.fpo_portal._entries_from_index", return_value=entries):
            installers = fpo_portal.fetch_fpo_installer_catalog()
            updates = fpo_portal.fetch_fpo_update_catalog()
        self.assertEqual([item["name"] for item in installers], ["FPOMAG_Instalador_0100.exe"])
        self.assertEqual([item["name"] for item in updates], ["FPOMAG_Atualiza_0302.exe", "FPOMAG_Atualiza_0301.exe"])
        self.assertEqual(updates[0]["release_date"], "2026-09-24")

    def test_rejects_unofficial_host_and_wrong_ftp_directory(self):
        self.assertFalse(fpo_portal.safe_url("https://attacker.example/FPOMAG_Atualiza_0302.exe", "FPOMAG_Atualiza_0302.exe"))
        self.assertFalse(fpo_portal.safe_url("ftp://ftp.datasus.gov.br/siasus/SIA/FPOMAG_Atualiza_0302.exe", "FPOMAG_Atualiza_0302.exe"))

    def test_uses_official_ftp_directory_when_listing_is_unavailable(self):
        with (
            patch("catalogs.fpo_portal._entries_from_index", side_effect=OSError("certificate failure")),
            patch("catalogs.fpo_portal.fetch_ftp_names", return_value=["FPOMAG_Atualiza_0302.exe", "FPO_Leiame.txt"]),
        ):
            updates = fpo_portal.fetch_fpo_update_catalog()
        self.assertEqual([item["name"] for item in updates], ["FPOMAG_Atualiza_0302.exe"])
        self.assertEqual(updates[0]["url"], "ftp://arpoador.datasus.gov.br/siasus/FPO/FPOMAG_Atualiza_0302.exe")


class BpaPortalTests(unittest.TestCase):
    def test_only_the_installer_pattern_is_kept(self):
        with patch("catalogs.bpa_portal._entries_from_index", return_value=[
            {"name": "BPAMAG0500.exe", "url": "ftp://ftp.datasus.gov.br/siasus/BPA/BPAMAG0500.exe", "size": None,
             "release_date": "2026-07-09"},
            {"name": "BPA_LEIAME.txt", "url": "ftp://ftp.datasus.gov.br/siasus/BPA/BPA_LEIAME.txt", "size": None},
            {"name": "BPAMAG0414.exe", "url": "ftp://ftp.datasus.gov.br/siasus/BPA/BPAMAG0414.exe", "size": None},
        ]):
            releases = bpa_portal.fetch_bpa_catalog()
        self.assertEqual([item["name"] for item in releases], ["BPAMAG0500.exe", "BPAMAG0414.exe"])
        self.assertEqual(releases[0]["release_date"], "2026-07-09")


class Sihd2PortalTests(unittest.TestCase):
    PAGE = """
    <html><body>
    CMPT 08/2026 - <a href="ftp://ftp2.datasus.gov.br/public/sistemas/dsweb/SIHD/Programas/SIHD2_2340.exe">Versão 23.40</a> - Arquivos DSIHD017<br>
    CMPT 01/2026 - <a href="ftp://ftp2.datasus.gov.br/public/sistemas/dsweb/SIHD/Programas/SIHD2_2270.exe">Versão 22.70</a> ,
    <a href="ftp://ftp2.datasus.gov.br/public/sistemas/dsweb/SIHD/Programas/SIHD2_2271.exe">Versão 22.71</a> (Cancelada) ,
    <a href="ftp://ftp2.datasus.gov.br/public/sistemas/dsweb/SIHD/Programas/SIHD2_2272.exe">Versão 22.72</a> - Arquivos DSIHD017
    </body></html>
    """

    def _fake_response(self):
        return io.BytesIO(self.PAGE.encode("iso-8859-15"))

    def test_cancelled_versions_are_ignored_and_highest_kept_first(self):
        with patch("catalogs.sihd_portal.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = self._fake_response()
            releases = sihd_portal.fetch_sihd2_catalog()
        self.assertEqual([item["version"] for item in releases], ["23.40", "22.72", "22.70"])
        self.assertNotIn("22.71", [item["version"] for item in releases])

    def test_rejects_links_outside_the_official_ftp_path(self):
        page = (
            '<a href="ftp://attacker.example/public/sistemas/dsweb/SIHD/Programas/SIHD2_2340.exe">'
            "Versão 23.40</a>"
        )
        with patch("catalogs.sihd_portal.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = io.BytesIO(page.encode("iso-8859-15"))
            with self.assertRaises(ValueError):
                sihd_portal.fetch_sihd2_catalog()


class SigtapPortalTests(unittest.TestCase):
    FEED = """<?xml version="1.0" encoding="UTF-8"?>
    <rss><channel>
      <item><link>ftp://ftp2.datasus.gov.br/pub/sistemas/tup/downloads/TabelaUnificada_202609_v2609171117.zip</link></item>
      <item><link>ftp://ftp2.datasus.gov.br/pub/sistemas/tup/downloads/TabelaUnificada_202608_v2608141139.zip</link></item>
      <item><link>ftp://attacker.example/pub/sistemas/tup/downloads/TabelaUnificada_202607_v1.zip</link></item>
    </channel></rss>
    """

    def test_parses_feed_and_rejects_unofficial_hosts(self):
        with patch("catalogs.sigtap_portal.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = self.FEED.encode("utf-8")
            releases = sigtap_portal.fetch_sigtap_catalog()
        self.assertEqual([item["name"] for item in releases], [
            "TabelaUnificada_202609_v2609171117.zip", "TabelaUnificada_202608_v2608141139.zip",
        ])
        self.assertEqual(releases[0]["competence"], "202609")


class CnesPortalTests(unittest.TestCase):
    def test_app_catalog_keeps_only_the_update_installer(self):
        payload = [
            {"nomeArquivo": "SCNES4850-COMPLETA.ZIP"},
            {"nomeArquivo": "SCNES4850-ATUALIZACAO.ZIP"},
            {"nomeArquivo": "SCNESSIMPLIFICADO4850-ATUALIZACAO.ZIP"},
        ]
        with patch("catalogs.cnes_portal._fetch_json", return_value=payload):
            releases = cnes_portal.fetch_cnes_app_catalog()
        self.assertEqual([item["name"] for item in releases], ["SCNES4850-ATUALIZACAO.ZIP"])
        self.assertEqual(
            releases[0]["url"], "https://cnes.datasus.gov.br/EstatisticasServlet?path=SCNES4850-ATUALIZACAO.ZIP",
        )

    def test_base_dados_catalog_parses_competence(self):
        payload = [{"nomeArquivo": "BASE_DE_DADOS_CNES_202608.ZIP"}, {"nomeArquivo": "LEIAME.TXT"}]
        with patch("catalogs.cnes_portal._fetch_json", return_value=payload):
            releases = cnes_portal.fetch_cnes_base_catalog()
        self.assertEqual([item["competence"] for item in releases], ["202608"])

    def test_download_link_must_match_host_path_and_query(self):
        self.assertTrue(cnes_portal.safe_url(
            "https://cnes.datasus.gov.br/EstatisticasServlet?path=SCNES4850-ATUALIZACAO.ZIP",
            "SCNES4850-ATUALIZACAO.ZIP",
        ))
        self.assertFalse(cnes_portal.safe_url(
            "https://attacker.example/EstatisticasServlet?path=SCNES4850-ATUALIZACAO.ZIP",
            "SCNES4850-ATUALIZACAO.ZIP",
        ))
        self.assertFalse(cnes_portal.safe_url(
            "https://cnes.datasus.gov.br/EstatisticasServlet?path=OUTRO.ZIP",
            "SCNES4850-ATUALIZACAO.ZIP",
        ))


if __name__ == "__main__":
    unittest.main()
