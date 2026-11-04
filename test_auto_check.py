"""Consulta disparada pelo portal quando o agendamento do GitHub atrasa."""

import os
os.environ["SITE_AUTO_CHECK"] = "0"  # O teste do app abaixo não consulta as fontes de verdade.
import json
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from unittest.mock import patch

from catalogs.auto_check import RETRY_AFTER, BackgroundCheck, is_stale

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


def catalog(completed_at):
    return {"last_check": {"completed_at": completed_at}}


class StaleTests(unittest.TestCase):
    def test_only_checks_after_two_hours_and_ten_minutes(self):
        self.assertFalse(is_stale(catalog("2026-11-04T09:50:00+00:00"), NOW))
        self.assertTrue(is_stale(catalog("2026-11-04T09:49:00+00:00"), NOW))

    def test_missing_or_invalid_date_counts_as_stale(self):
        for value in [{}, catalog(""), catalog("ontem")]:
            with self.subTest(value=value):
                self.assertTrue(is_stale(value, NOW))

    def test_falls_back_to_updated_at_and_understands_utc_suffix(self):
        self.assertFalse(is_stale({"updated_at": "2026-11-04T11:00:00Z"}, NOW))


class BackgroundCheckTests(unittest.TestCase):
    def test_runs_once_at_a_time_and_waits_before_retrying(self):
        check, release, calls = BackgroundCheck(), Event(), []

        def run():
            calls.append(1)
            release.wait(5)

        self.assertTrue(check.try_start(run, NOW))
        self.assertFalse(check.try_start(run, NOW + RETRY_AFTER * 2))  # Ainda em curso.
        release.set()
        for _ in range(100):
            if not check.running:
                break
            Event().wait(0.01)
        self.assertFalse(check.try_start(run, NOW + RETRY_AFTER - timedelta(seconds=1)))
        self.assertTrue(check.try_start(run, NOW + RETRY_AFTER))
        self.assertEqual(len(calls), 2)

    def test_a_failing_check_frees_the_next_attempt(self):
        check, done = BackgroundCheck(), Event()

        def run():
            done.set()
            raise OSError("fonte fora do ar")

        check.try_start(run, NOW)
        done.wait(5)
        for _ in range(100):
            if not check.running:
                break
            Event().wait(0.01)
        self.assertFalse(check.running)
        self.assertTrue(check.try_start(lambda: None, NOW + RETRY_AFTER))


class StaleNoticeTests(unittest.TestCase):
    def test_late_catalog_shows_notice_whose_button_checks_every_source(self):
        from streamlit.testing.v1 import AppTest
        from catalogs import (apac_portal, bpa_portal, ciha_portal, cnes_portal, fpo_portal, raas_portal,
                              sia_portal, sigtap_portal, sihd_portal, snapshot)

        fetchers = [(apac_portal, "fetch_apac_catalog"), (ciha_portal, "fetch_ciha02_catalog"),
                    (ciha_portal, "fetch_ciha02_installer_catalog"), (bpa_portal, "fetch_bpa_catalog"),
                    (sia_portal, "fetch_sia_catalog"), (sia_portal, "fetch_bdsia_catalog"),
                    (fpo_portal, "fetch_fpo_installer_catalog"), (fpo_portal, "fetch_fpo_update_catalog"),
                    (sihd_portal, "fetch_sihd2_catalog"), (cnes_portal, "fetch_cnes_complete_catalog"),
                    (cnes_portal, "fetch_cnes_app_catalog"), (sigtap_portal, "fetch_sigtap_catalog"),
                    (raas_portal, "fetch_raas_catalog")]
        path = Path(__file__).parent / "data" / "catalog.json"
        original = path.read_bytes()
        late = json.loads(original)
        late["last_check"] = {"completed_at": "2026-01-01T00:00:00+00:00", "source": "automatic",
                              "succeeded": 13, "total": 13, "failed_systems": []}
        late["updated_at"] = "2026-01-01T00:00:00+00:00"
        try:
            path.write_text(json.dumps(late), encoding="utf-8")
            with ExitStack() as stack:
                stack.enter_context(patch.object(snapshot, "read_published_catalog", return_value=None))
                stack.enter_context(patch("catalogs.state.atomic_write"))
                mocks = [stack.enter_context(patch.object(module, name, return_value=[])) for module, name in fetchers]
                app = AppTest.from_file(str(Path(__file__).parent / "app.py"), default_timeout=20).run()
                self.assertFalse(app.exception)
                text = " ".join(item.value for item in app.markdown)
                self.assertIn("As versões podem estar desatualizadas", text)
                next(b for b in app.button if b.key == "stale_check_now").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(all(fetch.call_count == 1 for fetch in mocks))
        finally:
            path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
