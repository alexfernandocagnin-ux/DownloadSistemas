"""Testes dos catálogos de download, sem acessar a rede nem executar nada."""

import io
import unittest
from unittest.mock import patch

from catalogs import bpa_portal, sia_portal, sihd_portal


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
            {"name": name, "url": url, "size": None} for name, url in entries
        ]):
            bdsia = sia_portal.fetch_bdsia_catalog()
            sia = sia_portal.fetch_sia_catalog()
        self.assertEqual([item["name"] for item in bdsia], ["BDSIA202608b.exe", "BDSIA202607a.exe"])
        self.assertEqual(bdsia[0]["competence"], "202608")
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


class BpaPortalTests(unittest.TestCase):
    def test_only_the_installer_pattern_is_kept(self):
        with patch("catalogs.bpa_portal._entries_from_index", return_value=[
            {"name": "BPAMAG0500.exe", "url": "ftp://ftp.datasus.gov.br/siasus/BPA/BPAMAG0500.exe", "size": None},
            {"name": "BPA_LEIAME.txt", "url": "ftp://ftp.datasus.gov.br/siasus/BPA/BPA_LEIAME.txt", "size": None},
            {"name": "BPAMAG0414.exe", "url": "ftp://ftp.datasus.gov.br/siasus/BPA/BPAMAG0414.exe", "size": None},
        ]):
            releases = bpa_portal.fetch_bpa_catalog()
        self.assertEqual([item["name"] for item in releases], ["BPAMAG0500.exe", "BPAMAG0414.exe"])


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


if __name__ == "__main__":
    unittest.main()
