"""Regressões: espelhos quebrados, publicação incompleta e DATASUS indisponível."""

import hashlib
import io
import zipfile
import json
import os
import importlib.util
from ftplib import error_perm
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from catalogs import mirrors, _common, apac_portal, bpa_portal, ciha_portal, cnes_portal, fpo_portal, sia_portal, sigtap_portal, sihd_portal
from catalogs.updates import merge_updates
from scripts import sync_catalog as sync


NAME = "BPAMAG0500.exe"
URL = "ftp://arpoador.datasus.gov.br/siasus/BPA/" + NAME
MIRROR = {"tag": "bpa-latest", "asset_name": NAME,
          "asset_url": f"https://github.com/{mirrors.REPOSITORY}/releases/download/bpa-latest/{NAME}"}
PACKAGE = b"MZ" + b"0" * 100_000

def zip_package():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("data.txt", b"0" * 100_000)
    return output.getvalue()


class MirrorTests(unittest.TestCase):
    def test_old_mirror_is_not_used_for_new_version(self):
        self.assertIsNone(mirrors.matching_mirror("BPAMAG0501.exe", MIRROR))

    def test_foreign_repository_is_rejected(self):
        foreign = {**MIRROR, "asset_url": MIRROR["asset_url"].replace(mirrors.REPOSITORY, "other/repository")}
        self.assertIsNone(mirrors.matching_mirror(NAME, foreign))

    def test_error_page_is_not_offered_as_installer(self):
        with patch.object(mirrors, "download_via_http", return_value=b"<html>404</html>"):
            with self.assertRaises(ValueError):
                mirrors.download_mirror(NAME, MIRROR)

    def test_truncated_download_is_rejected(self):
        with patch.object(mirrors, "download_via_http", return_value=PACKAGE):
            with self.assertRaises(ValueError):
                mirrors.download_mirror(NAME, {**MIRROR, "size": len(PACKAGE) + 1})

    def test_corrupt_download_is_rejected(self):
        with patch.object(mirrors, "download_via_http", return_value=PACKAGE):
            with self.assertRaises(ValueError):
                mirrors.download_mirror(NAME, {**MIRROR, "sha256": "0" * 64})

    def test_probe_reads_only_signature_for_large_file(self):
        size = 739_134_749
        name = "BASE_DE_DADOS_CNES_202608.ZIP"
        mirror = {**MIRROR, "asset_name": name, "asset_url": MIRROR["asset_url"].replace(NAME, name)}
        with patch.object(mirrors, "urlopen") as opening:
            response = opening.return_value.__enter__.return_value
            response.read.return_value = b"PK"
            response.headers = {"Content-Range": f"bytes 0-1/{size}"}
            result = mirrors.probe_mirror(name, {**mirror, "size": size})
        response.read.assert_called_once_with(2)
        self.assertEqual(result, mirror["asset_url"])

    def test_zip_cannot_be_delivered_as_exe_even_with_matching_hash(self):
        wrong = b"PK" + b"0" * 100_000
        with patch.object(mirrors, "download_via_http", return_value=wrong):
            with self.assertRaises(ValueError):
                mirrors.download_mirror(NAME, {**MIRROR, "sha256": hashlib.sha256(wrong).hexdigest()})

    def test_probe_rejects_missing_or_wrong_file(self):
        with patch.object(mirrors, "urlopen") as opening:
            response = opening.return_value.__enter__.return_value
            response.read.return_value = b"<h"
            response.headers = {"Content-Length": "100"}
            with self.assertRaises(ValueError):
                mirrors.probe_mirror(NAME, MIRROR)

    def test_valid_download_is_returned(self):
        with patch.object(mirrors, "download_via_http", return_value=PACKAGE):
            result = mirrors.download_mirror(NAME, {**MIRROR, "size": len(PACKAGE), "sha256": hashlib.sha256(PACKAGE).hexdigest()})
        self.assertEqual(result, PACKAGE)


class CnesRecoveryTests(unittest.TestCase):
    def test_catalog_works_when_https_api_is_offline(self):
        with patch.object(cnes_portal, "_fetch_json", side_effect=OSError("offline")), patch.object(cnes_portal, "fetch_ftp_names", return_value=["SCNES4850-ATUALIZACAO.ZIP", "SCNES4850-COMPLETA.ZIP"]):
            releases = cnes_portal.fetch_cnes_app_catalog()
        self.assertEqual([r["name"] for r in releases], ["SCNES4850-ATUALIZACAO.ZIP"])

    def test_download_avoids_unavailable_servlet(self):
        name = "SCNES4850-ATUALIZACAO.ZIP"
        package = zip_package()
        with patch.object(cnes_portal, "download_via_ftp", return_value=package) as ftp, patch.object(cnes_portal, "download_via_http", side_effect=AssertionError("servlet should not be needed")):
            result = cnes_portal.download_app_release({"name": name, "url": cnes_portal._download_url(name)})
        self.assertEqual(result, package)
        self.assertEqual(ftp.call_args.args[1], "/cnes/Versoes-Fces-Nacional")

    def test_base_download_uses_correct_directory(self):
        name = "BASE_DE_DADOS_CNES_202608.ZIP"
        with patch.object(cnes_portal, "download_via_ftp", return_value=zip_package()) as ftp:
            cnes_portal.download_base_release({"name": name, "url": cnes_portal._download_url(name)})
        self.assertEqual(ftp.call_args.args[1], "/cnes")


class FtpRecoveryTests(unittest.TestCase):
    def test_download_uses_another_official_host_after_outage(self):
        package = b"MZ" + b"0" * 1_000_000
        with patch.object(_common, "download_via_ftp", side_effect=[OSError("offline"), package]) as download:
            self.assertEqual(bpa_portal.download_release({"name": NAME, "url": URL}), package)
        self.assertEqual(download.call_count, 2)
        self.assertNotEqual(download.call_args_list[0].args[0], download.call_args_list[1].args[0])

    def test_ftp_protocol_errors_become_recoverable_errors(self):
        with patch.object(_common, "FTP") as ftp:
            ftp.return_value.__enter__.return_value.retrbinary.side_effect = error_perm("550 not available")
            with self.assertRaises(OSError):
                _common.download_via_ftp("official", "/folder", NAME, max_size=2_000_000)


class SynchronizationTests(unittest.TestCase):
    def test_discovery_records_latest_without_downloading_or_announcing_it_again(self):
        release = {"name": "BPAMAG9999.exe", "url": URL}
        config = {"label": "BPA", "official_page": "https://sia.datasus.gov.br", "fetch": lambda: [release]}
        previous = {"systems": {"bpa": {"current": {"name": NAME}, "latest": release}}}
        with patch.object(sync, "CATALOG_ONLY", True), patch.object(sync, "store_package", side_effect=AssertionError("download")):
            result = sync.sync_single_version_system("bpa", config, previous)
        self.assertEqual(result["latest"]["name"], release["name"])
        self.assertEqual(result["current"]["name"], NAME)
        self.assertNotIn("_announcements", result)

    def test_unexpected_source_error_does_not_abort_other_systems(self):
        def broken():
            raise RuntimeError("invalid response")
        configs = {"bpa": {"label": "BPA", "official_page": "https://example", "fetch": broken},
                   "sia": {"label": "SIA", "official_page": "https://example",
                           "fetch": lambda: [{"name": "SIA0605.exe", "url": "ftp://example/SIA0605.exe"}]}}
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps({"systems": {"bpa": {"current": {"name": NAME}}}}), encoding="utf-8")
            stack.enter_context(patch.object(sync, "CATALOG_PATH", path))
            stack.enter_context(patch.object(sync, "SINGLE_VERSION_SYSTEMS", configs))
            stack.enter_context(patch.object(sync, "COMPETENCE_SYSTEMS", {}))
            stack.enter_context(patch("sys.argv", ["sync_catalog.py", "--catalog-only"]))
            stack.enter_context(patch.object(sync, "CATALOG_ONLY", False))
            stack.enter_context(patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""}))
            sync.main()
            result = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(result["systems"]["bpa"]["current"]["name"], NAME)
            self.assertEqual(result["systems"]["sia"]["latest"]["name"], "SIA0605.exe")
            self.assertEqual(result["systems"]["bpa"]["error"], "RuntimeError")

    def setUp(self):
        self.old = {"current": {"name": NAME, "url": URL}, "mirror": MIRROR,
                    "checked_at": "2026-09-20T12:00:00+00:00", "official_reachable": True}
        self.previous = {"systems": {"bpa": self.old}}
        self.config = {**sync.SINGLE_VERSION_SYSTEMS["bpa"], "fetch": lambda: [{"name": NAME, "url": URL}],
                       "download": lambda release: PACKAGE}

    def test_offline_source_preserves_copy_and_confirmation_date(self):
        self.config["fetch"] = lambda: (_ for _ in ()).throw(OSError("offline"))
        result = sync.sync_single_version_system("bpa", self.config, self.previous)
        self.assertEqual(result["mirror"], MIRROR)
        self.assertEqual(result["current"], self.old["current"])
        self.assertEqual(result["last_success_at"], self.old["checked_at"])
        self.assertFalse(result["official_reachable"])

    def test_same_release_keeps_its_known_official_date_when_listing_has_no_date(self):
        old = {**self.old, "current": {**self.old["current"], "release_date": "2026-07-09"}}
        previous = {"systems": {"bpa": old}}
        result = sync.sync_single_version_system("bpa", self.config, previous)
        self.assertEqual(result["current"]["release_date"], "2026-07-09")

    def test_missing_remote_asset_is_downloaded_again(self):
        with patch.object(sync, "PUBLISH", True), patch.object(sync, "remote_asset", return_value=None), patch.object(sync, "store_package", return_value={**MIRROR, "verified_at": "now"}) as store:
            result = sync.sync_single_version_system("bpa", self.config, self.previous)
        store.assert_called_once()
        self.assertEqual(result["mirror"]["verified_at"], "now")

    def test_failed_upload_never_replaces_previous_version(self):
        self.config["fetch"] = lambda: [{"name": "BPAMAG0501.exe", "url": URL}]
        with patch.object(sync, "store_package", side_effect=ValueError("upload missing")):
            result = sync.sync_single_version_system("bpa", self.config, self.previous)
        self.assertEqual(result["current"], self.old["current"])
        self.assertEqual(result["mirror"], MIRROR)
        self.assertEqual(result["latest"]["name"], "BPAMAG0501.exe")
        self.assertTrue(result["official_reachable"])
        self.assertTrue(result["pending_download"])

    def test_new_single_release_is_announced_even_when_mirror_upload_fails(self):
        self.config["fetch"] = lambda: [{"name": "BPAMAG0501.exe", "url": URL}]
        with patch.object(sync, "store_package", side_effect=OSError("upload offline")):
            result = sync.sync_single_version_system("bpa", self.config, self.previous)
        self.assertEqual(result["current"], self.old["current"])
        self.assertEqual(result["_announcements"][0]["system"], "BPA Magnético")
        self.assertEqual(result["_announcements"][0]["name"], "BPAMAG0501.exe")

    def test_draft_asset_is_not_announced_as_public_download(self):
        draft = {"isDraft": True, "assets": [{"name": NAME, "size": len(PACKAGE), "url": MIRROR["asset_url"]}]}
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": mirrors.REPOSITORY}), patch.object(sync, "gh", return_value=json.dumps(draft)):
            self.assertIsNone(sync.remote_asset("bpa-latest", NAME))

    def test_completed_upload_is_recovered_after_interrupted_run(self):
        asset = {"name": NAME, "url": MIRROR["asset_url"], "size": len(PACKAGE), "digest": "sha256:" + "a" * 64}
        config = {**self.config, "download": lambda release: (_ for _ in ()).throw(AssertionError("unnecessary download"))}
        with patch.object(sync, "PUBLISH", True), patch.object(sync, "remote_asset", return_value=asset), patch.object(sync, "probe_mirror", return_value=MIRROR["asset_url"]):
            mirror = sync.store_package("bpa", {"name": NAME, "url": URL}, config, "bpa-latest")
        self.assertEqual(mirror["sha256"], "a" * 64)
        self.assertEqual(mirror["asset_url"], MIRROR["asset_url"])

    def test_local_download_does_not_invent_published_link(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sync, "DIST_DIR", Path(directory)), patch.object(sync, "PUBLISH", False):
            mirror = sync.store_package("bpa", {"name": NAME, "url": URL}, self.config, "bpa-latest")
            self.assertTrue((Path(directory) / "bpa" / NAME).is_file())
        self.assertIsNone(mirror)

    def test_first_sync_prioritizes_latest_month_and_reports_progress(self):
        releases = [{"name": f"base_{month}.ZIP", "url": "official", "competence": month} for month in ["202608", "202607"]]
        config = {**sync.COMPETENCE_SYSTEMS["cnes_base"], "fetch": lambda: releases}
        progress = []
        with patch.object(sync, "store_package", return_value=MIRROR) as store:
            result = sync.sync_competence_system("cnes_base", config, {}, lambda key, info: progress.append((key, info)))
        self.assertEqual(store.call_count, 2)
        self.assertEqual(set(result["competences"]), {"202608", "202607"})
        self.assertEqual(progress[0][0], "cnes_base")
        self.assertEqual(progress[0][1]["available_releases"], releases)
        self.assertFalse(progress[0][1]["competences"])

    def test_full_history_is_saved_even_when_publication_budget_is_exhausted(self):
        releases = [{"name": f"BDSIA{month}a.exe", "url": "official", "competence": month}
                    for month in ["202609", "202608", "201001"]]
        config = {**sync.COMPETENCE_SYSTEMS["bdsia"], "fetch": lambda: releases, "new_packages_per_run": 1}
        with patch.object(sync, "store_package", return_value=MIRROR) as store:
            result = sync.sync_competence_system("bdsia", config, {})
        store.assert_called_once()
        self.assertEqual(result["available_releases"], releases)
        self.assertEqual(set(result["competences"]), {"202609"})

    def test_month_tag_comes_from_competence_not_filename_guess(self):
        release = {"name": "BASE_DE_DADOS_CNES_202608.ZIP", "url": "official", "competence": "202608",
                   "release_date": "2026-08-28"}
        config = {**sync.COMPETENCE_SYSTEMS["cnes_base"], "fetch": lambda: [release]}
        with patch.object(sync, "store_package", return_value=MIRROR) as store:
            result = sync.sync_competence_system("cnes_base", config, {})
        self.assertEqual(store.call_args.args[3], "cnes-base-202608")
        self.assertEqual(result["competences"]["202608"]["release_date"], "2026-08-28")

    def test_older_months_survive_new_catalog_and_failed_download(self):
        old_entry = {"name": "old.exe", "url": "old", "mirror": MIRROR}
        previous = {"systems": {"bdsia": {"competences": {"202601": old_entry}}}}
        config = {**sync.COMPETENCE_SYSTEMS["bdsia"], "fetch": lambda: [{"name": "new.exe", "url": "new", "competence": "202609"}]}
        with patch.object(sync, "store_package", side_effect=OSError("offline")):
            result = sync.sync_competence_system("bdsia", config, previous)
        self.assertEqual(result["competences"]["202601"], old_entry)
        self.assertEqual(result["pending_competences"], ["202609"])
        self.assertEqual(result["latest"]["name"], "new.exe")
        self.assertEqual(result["_announcements"][0]["competence"], "202609")

    def test_update_feed_deduplicates_and_keeps_first_discovery_date(self):
        old = {"id": "bpa:BPAMAG0501.exe", "name": "BPAMAG0501.exe", "found_at": "2026-09-20T10:00:00+00:00"}
        repeated = {**old, "found_at": "2026-09-29T10:00:00+00:00"}
        newest = {"id": "sia:SIA0605.exe", "name": "SIA0605.exe", "found_at": "2026-09-29T12:00:00+00:00"}
        merged = merge_updates([old], [repeated, newest])
        self.assertEqual([event["id"] for event in merged], [newest["id"], old["id"]])
        self.assertEqual(merged[1]["found_at"], old["found_at"])


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "Requer Streamlit")
class PortalTests(unittest.TestCase):
    def setUp(self):
        import streamlit as st
        st.cache_data.clear()
        remote = patch("catalogs.snapshot.read_published_catalog", return_value=None)
        remote.start()
        self.addCleanup(remote.stop)

    def app(self, program="bpa"):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(Path(__file__).parent / "app.py"), default_timeout=20)
        app.session_state["program_system"] = program
        return app

    def test_home_opens_without_any_official_request(self):
        with patch("catalogs.bpa_portal.fetch_bpa_catalog", side_effect=AssertionError("official request")):
            app = self.app(program="cnes").run()
        self.assertFalse(app.exception)
        self.assertTrue(app.button)
        self.assertEqual([tab.label for tab in app.tabs], ["Programas e instaladores", "Tabelas e bases", "Manuais"])
        rendered = "\n".join(element.value for element in app.markdown)
        self.assertIn("Downloads Sistemas", rendered)
        self.assertNotIn("Downloads sem rodeios", rendered)
        self.assertIn("Novidades dos sistemas", rendered)
        self.assertIn("Biblioteca".upper(), rendered)
        self.assertNotIn("Últimos lançamentos", rendered)
        self.assertTrue(any(box.key == "manual_system" for box in app.selectbox))
        self.assertTrue(any(button.key == "force_catalog_check" for button in app.button))
        self.assertTrue(any(str(button.key).startswith("prep_cnes_complete_") for button in app.button))
        self.assertTrue(any(str(button.key).startswith("prep_cnes_app_") for button in app.button))
        self.assertIn("Instalação completa", rendered)
        self.assertIn("Atualização", rendered)

    def test_system_navigation_keeps_the_download_selection_and_cnes_packages_separate(self):
        app = self.app(program="cnes").run()
        self.assertFalse(app.exception)
        app.button(key="choose_program_fpo").click().run()
        self.assertEqual(app.session_state["program_system"], "fpo")
        self.assertTrue(any(str(button.key).startswith("prep_fpo_update_") for button in app.button))
        self.assertTrue(any(str(button.key).startswith("prep_fpo_installer_") for button in app.button))
        self.assertFalse(any(str(button.key).startswith("prep_cnes_") for button in app.button))
        app.selectbox(key="program_system").select("ciha02").run()
        self.assertFalse(app.exception)
        self.assertTrue(any(str(button.key).startswith("prep_ciha02_installer_") for button in app.button))
        self.assertTrue(any(str(button.key).startswith("prep_ciha02_") for button in app.button))
        app.button(key="choose_program_cnes").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any(str(button.key).startswith("prep_cnes_complete_") for button in app.button))
        self.assertTrue(any(str(button.key).startswith("prep_cnes_app_") for button in app.button))
        app.run()
        self.assertEqual(app.session_state["program_system"], "cnes")

    def test_updated_manual_with_same_id_delivers_current_verified_bytes(self):
        from catalogs import manuals
        item = next(item for item in manuals.load_manuals() if item["id"] == "bpa-layout")
        old_pdf = b"%PDF-1.4\nold edition\n%%EOF"
        new_pdf = b"%PDF-1.4\nnew edition\n%%EOF"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manuals.json"
            document = root / item["file"]
            with patch.object(manuals, "MANUALS_PATH", manifest), patch.object(manuals, "MANUALS_DIR", root):
                for package in [old_pdf, new_pdf]:
                    document.write_bytes(package)
                    item = {**item, "size": len(package), "sha256": hashlib.sha256(package).hexdigest()}
                    manifest.write_text(json.dumps([item]), encoding="utf-8")
                    app = self.app().run()
                    app.button(key="prep_manual_bpa-layout_Layout_Exportacao_BPA.pdf").click().run()
                    self.assertFalse(app.exception)
                    self.assertEqual(app.session_state["official_download_manual_bpa-layout"]["data"], package)

    def test_manual_filters_and_shared_system_download_flow(self):
        pdf = b"%PDF-1.4\nverified manual\n%%EOF"
        with patch("catalogs.manuals.download_manual", return_value=pdf) as download:
            app = self.app().run()
            download.assert_not_called()
            app.selectbox(key="manual_system").select("bpa").run()
            app.text_input(key="manual_search").input("exportacao").run()
            rendered = "\n".join(element.value for element in app.markdown)
            self.assertIn("Layout de exportação do BPA", rendered)
            self.assertNotIn("Manual operacional do BPA", rendered)
            self.assertNotIn("Manual operacional da APAC", rendered)
            app.button(key="prep_manual_bpa-layout_Layout_Exportacao_BPA.pdf").click().run()
            self.assertFalse(app.exception)
            download.assert_called_once_with("bpa-layout")
            self.assertTrue(any("Baixar manual:" in button.proto.label for button in app.get("download_button")))
            self.assertEqual(app.session_state["official_download_manual_bpa-layout"]["data"], pdf)
            app.text_input(key="manual_search").input("nada-encontrado").run()
            self.assertTrue(any("Nenhum manual encontrado" in item.value for item in app.info))
        app = self.app().run()
        with patch("catalogs.manuals.download_manual", side_effect=OSError("offline")):
            app.button(key="prep_manual_bpa-operacao_Manual_Operacional_BPA.pdf").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("O arquivo não está disponível agora" in item.value for item in app.error))

    def test_manual_discovery_survives_a_new_session_and_is_not_announced_twice(self):
        path = Path(__file__).parent / "data" / "catalog.json"
        original = path.read_bytes()
        new = {"name": "BPAMAG9999.exe", "url": URL.replace(NAME, "BPAMAG9999.exe")}
        try:
            with ExitStack() as stack:
                stack.enter_context(patch.object(bpa_portal, "fetch_bpa_catalog", return_value=[new]))
                for module, name in [(apac_portal, "fetch_apac_catalog"), (ciha_portal, "fetch_ciha02_catalog"),
                                     (ciha_portal, "fetch_ciha02_installer_catalog"), (sia_portal, "fetch_sia_catalog"),
                                     (sia_portal, "fetch_bdsia_catalog"), (fpo_portal, "fetch_fpo_installer_catalog"),
                                     (fpo_portal, "fetch_fpo_update_catalog"), (sihd_portal, "fetch_sihd2_catalog"),
                                     (cnes_portal, "fetch_cnes_complete_catalog"), (cnes_portal, "fetch_cnes_app_catalog"),
                                     (cnes_portal, "fetch_cnes_base_catalog"), (sigtap_portal, "fetch_sigtap_catalog")]:
                    stack.enter_context(patch.object(module, name, return_value=[]))
                app = self.app().run()
                next(b for b in app.button if b.key == "force_catalog_check").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["systems"]["bpa"]["latest"]["name"], new["name"])
                fresh = self.app().run()
                self.assertIn(f'<dd>{new["name"]}</dd>', "\n".join(item.value for item in fresh.markdown))
                next(b for b in fresh.button if b.key == "force_catalog_check").click().run()
                self.assertFalse(fresh.exception)
                self.assertEqual(fresh.session_state["forced_live_updates"], [])
        finally:
            path.write_bytes(original)

    def test_published_catalog_reaches_the_portal_without_official_query_or_redeploy(self):
        latest = {"name": "BPAMAG9999.exe", "url": URL.replace(NAME, "BPAMAG9999.exe")}
        published = {"updated_at": "2026-10-06T23:50:00+00:00",
                     "last_check": {"completed_at": "2026-10-06T23:50:00+00:00", "total": 12, "succeeded": 12},
                     "systems": {"bpa": {"latest": latest, "catalog_checked_at": "2026-10-06T23:50:00+00:00"}}}
        catalog_path = Path(__file__).parent / "data" / "catalog.json"
        local = {"updated_at": "2026-10-06T22:00:00+00:00",
                 "last_check": {"completed_at": "2026-10-06T22:00:00+00:00", "total": 12, "succeeded": 12},
                 "systems": {"bpa": {"latest": {"name": NAME, "url": URL},
                                      "catalog_checked_at": "2026-10-06T22:00:00+00:00"}}}
        original_read = Path.read_text

        def read(path, *args, **kwargs):
            return json.dumps(local) if path == catalog_path else original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", read), patch("catalogs.snapshot.read_published_catalog", return_value=published), patch("catalogs.state.atomic_write") as write, patch.object(bpa_portal, "fetch_bpa_catalog", side_effect=AssertionError("official query")):
            app = self.app().run()
        self.assertFalse(app.exception)
        self.assertIn(f'<dd>{latest["name"]}</dd>', "\n".join(item.value for item in app.markdown))
        self.assertIn("20:50", "\n".join(item.value for item in app.markdown))
        self.assertEqual(write.call_args.args[1]["last_check"], published["last_check"])

    def test_manual_query_with_no_answer_preserves_success_time_and_shows_attempt(self):
        path = Path(__file__).parent / "data" / "catalog.json"
        original = path.read_bytes()
        try:
            with patch.object(apac_portal, "fetch_apac_catalog", return_value=[]), patch.object(ciha_portal, "fetch_ciha02_catalog", return_value=[]), patch.object(ciha_portal, "fetch_ciha02_installer_catalog", return_value=[]), patch.object(bpa_portal, "fetch_bpa_catalog", return_value=[]), patch.object(sia_portal, "fetch_sia_catalog", return_value=[]), patch.object(sia_portal, "fetch_bdsia_catalog", return_value=[]), patch.object(fpo_portal, "fetch_fpo_installer_catalog", return_value=[]), patch.object(fpo_portal, "fetch_fpo_update_catalog", return_value=[]), patch.object(sihd_portal, "fetch_sihd2_catalog", return_value=[]), patch.object(cnes_portal, "fetch_cnes_complete_catalog", return_value=[]), patch.object(cnes_portal, "fetch_cnes_app_catalog", return_value=[]), patch.object(sigtap_portal, "fetch_sigtap_catalog", return_value=[]):
                app = self.app().run()
                next(b for b in app.button if b.key == "force_catalog_check").click().run()
            self.assertFalse(app.exception)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["updated_at"], json.loads(original)["updated_at"])
            self.assertEqual(saved["last_check"]["succeeded"], 0)
            self.assertTrue(any("0 de 12" in warning.value for warning in app.warning))
        finally:
            path.write_bytes(original)

    def test_sihd_can_prepare_from_official_source_without_a_mirror(self):
        with patch.object(sihd_portal, "download_release", return_value=PACKAGE), patch("catalogs.mirrors.matching_mirror", return_value=None):
            app = self.app(program="sihd2").run()
            next(b for b in app.button if str(b.key).startswith("prep_sihd2_")).click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any("SIHD2" in b.proto.label for b in app.get("download_button")))

    def test_manual_check_forces_every_catalog_without_cache(self):
        fetchers = [
            (apac_portal, "fetch_apac_catalog"),
            (ciha_portal, "fetch_ciha02_catalog"),
            (ciha_portal, "fetch_ciha02_installer_catalog"),
            (bpa_portal, "fetch_bpa_catalog"), (sia_portal, "fetch_sia_catalog"),
            (fpo_portal, "fetch_fpo_installer_catalog"), (fpo_portal, "fetch_fpo_update_catalog"),
            (sihd_portal, "fetch_sihd2_catalog"), (cnes_portal, "fetch_cnes_complete_catalog"),
            (cnes_portal, "fetch_cnes_app_catalog"), (sia_portal, "fetch_bdsia_catalog"),
            (sigtap_portal, "fetch_sigtap_catalog"),
        ]
        with ExitStack() as stack:
            stack.enter_context(patch("catalogs.state.atomic_write"))
            mocks = [stack.enter_context(patch.object(module, name, return_value=[])) for module, name in fetchers]
            app = self.app().run()
            next(button for button in app.button if button.key == "force_catalog_check").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(all(fetch.call_count == 1 for fetch in mocks))
        self.assertIn("Última verificação manual, sem cache", "\n".join(element.value for element in app.caption))

    def test_saved_old_competence_downloads_without_manual_catalog_check(self):
        catalog_path = Path(__file__).parent / "data" / "catalog.json"
        old = {"name": "BDSIA201001a.exe", "url": "ftp://arpoador.datasus.gov.br/siasus/SIA/BDSIA201001a.exe",
               "competence": "201001"}
        snapshot = {"systems": {"bdsia": {"available_releases": [old]}}}
        original_read = Path.read_text

        def read(path, *args, **kwargs):
            return json.dumps(snapshot) if path == catalog_path else original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", read), patch.object(sia_portal, "fetch_bdsia_catalog", side_effect=AssertionError("manual check")), patch.object(sia_portal, "download_release", return_value=PACKAGE) as download:
            app = self.app().run()
            selector = next(box for box in app.selectbox if box.key == "competence_bdsia")
            self.assertEqual(selector.value, "201001")
            next(button for button in app.button if button.key == "prep_bdsia_BDSIA201001a.exe").click().run()
            self.assertFalse(app.exception)
            download.assert_called_once()
            self.assertTrue(app.get("download_button"))

    def test_mirror_download_works_while_official_source_is_offline(self):
        with patch("catalogs.mirrors.download_mirror", return_value=PACKAGE), patch("catalogs.bpa_portal.download_release", side_effect=AssertionError("DATASUS should not be needed")) as official:
            app = self.app().run()
            next(button for button in app.button if str(button.key).startswith("prep_bpa_")).click().run()
        self.assertFalse(app.exception)
        official.assert_not_called()
        self.assertTrue(app.get("download_button"))

    def test_broken_mirror_falls_back_without_redirect(self):
        with patch("catalogs.mirrors.download_mirror", side_effect=OSError("404")), patch("catalogs.bpa_portal.download_release", return_value=PACKAGE) as official:
            app = self.app().run()
            next(button for button in app.button if str(button.key).startswith("prep_bpa_")).click().run()
        self.assertFalse(app.exception)
        official.assert_called_once()
        self.assertTrue(app.get("download_button"))
        self.assertTrue(app.warning)

    def test_both_sources_offline_show_error_without_crashing(self):
        with patch("catalogs.mirrors.download_mirror", side_effect=OSError("404")), patch("catalogs.sia_portal.download_release", side_effect=OSError("offline")) as official:
            app = self.app(program="sia").run()
            next(button for button in app.button if str(button.key).startswith("prep_sia_")).click().run()
        self.assertFalse(app.exception)
        official.assert_called_once()
        self.assertTrue(app.error)

    def test_fpo_buttons_deliver_the_selected_package_without_github_redirect(self):
        downloads = []
        snapshot = json.loads((Path(__file__).parent / "data" / "catalog.json").read_text(encoding="utf-8"))
        update_name = snapshot["systems"]["fpo_update"]["current"]["name"]
        installer_name = snapshot["systems"]["fpo_installer"]["current"]["name"]

        def download(name, mirror, **kwargs):
            self.assertEqual(mirror["asset_name"], name)
            downloads.append(name)
            return PACKAGE + name.encode()

        with patch("catalogs.mirrors.download_mirror", side_effect=download):
            app = self.app(program="fpo").run()
            next(button for button in app.button if str(button.key).startswith("prep_fpo_update_")).click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["official_download_fpo_update"]["data"], PACKAGE + update_name.encode())
            self.assertTrue(any(update_name in button.proto.label for button in app.get("download_button")))
            next(button for button in app.button if str(button.key).startswith("prep_fpo_installer_")).click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["official_download_fpo_installer"]["data"], PACKAGE + installer_name.encode())
            self.assertTrue(any(installer_name in button.proto.label for button in app.get("download_button")))
        self.assertEqual(downloads, [update_name, installer_name])


if __name__ == "__main__":
    unittest.main()
