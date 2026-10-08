"""Regression checks for the seven-day announcements and their expandable list."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from catalogs.state import merge_catalogs
from catalogs.updates import make_update_event, recent_updates


ROOT = Path(__file__).parent
CATALOG_PATH = ROOT / "data" / "catalog.json"
NOW = datetime(2026, 10, 8, 16, tzinfo=timezone.utc)


class FeedVisibilityTests(unittest.TestCase):
    def setUp(self):
        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        self.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        self.current_time = NOW
        read_text = Path.read_text

        def read_snapshot(path, *args, **kwargs):
            if path == CATALOG_PATH:
                return json.dumps(self.catalog)
            return read_text(path, *args, **kwargs)

        owner = self

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return owner.current_time.astimezone(tz) if tz else owner.current_time.replace(tzinfo=None)

        for replacement in [patch.object(Path, "read_text", read_snapshot),
                            patch("catalogs.snapshot.read_published_catalog", return_value=None),
                            patch("catalogs.updates.datetime", Clock)]:
            replacement.start()
            self.addCleanup(replacement.stop)

    def event(self, system="sigtap", name="TabelaUnificada_202609_v2610050950.zip", found_at=None):
        return make_update_event(system, system.upper(), name, found_at or (NOW - timedelta(days=3)).isoformat())

    def app(self):
        result = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
        self.assertFalse(result.exception)
        return result

    def test_one_valid_announcement_still_has_an_expandable_list(self):
        event = self.event()
        self.catalog["updates"] = [event]
        app = self.app()
        self.assertEqual([box.label for box in app.expander],
                         ["Últimas atualizações · 1 aviso nos últimos 7 dias"])
        self.assertIn(event["name"], app.expander[0].markdown[0].value)
        self.assertIn("primeira identificação", app.expander[0].caption[0].value)

    def test_expiring_one_of_two_announcements_keeps_the_other_and_the_list(self):
        recent = self.event()
        expiring = self.event("sia", "SIA0605.exe", (NOW - timedelta(days=7) + timedelta(seconds=1)).isoformat())
        self.catalog["updates"] = [recent, expiring]
        app = self.app()
        self.assertIn("2 avisos", app.expander[0].label)
        self.current_time += timedelta(seconds=2)
        app.run()
        self.assertFalse(app.exception)
        self.assertIn("1 aviso", app.expander[0].label)
        contents = app.expander[0].markdown[0].value
        self.assertIn(recent["name"], contents)
        self.assertNotIn(expiring["name"], contents)
        self.assertEqual(self.catalog["updates"], [recent, expiring])

    def test_the_final_announcement_expires_without_deleting_its_saved_record(self):
        event = self.event(found_at=(NOW - timedelta(days=7)).isoformat())
        self.catalog["updates"] = [event]
        app = self.app()
        self.assertEqual(len(app.expander), 1)
        self.current_time += timedelta(seconds=1)
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.expander), 0)
        self.assertTrue(any("Nenhuma nova versão identificada" in block.value for block in app.markdown))
        self.assertEqual(self.catalog["updates"], [event])

    def test_manual_and_automatic_announcements_remain_visible_together(self):
        automatic, manual = self.event(), self.event("bpa", "BPAMAG0501.exe", NOW.isoformat())
        self.catalog["updates"] = [automatic]
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20)
        app.session_state["forced_live_updates"] = [manual]
        app.run()
        self.assertFalse(app.exception)
        self.assertIn("2 avisos", app.expander[0].label)
        contents = app.expander[0].markdown[0].value
        for event in [automatic, manual]:
            self.assertIn(event["name"], contents)

    def test_an_empty_feed_keeps_the_header_and_omits_the_expander(self):
        self.catalog["updates"] = []
        app = self.app()
        self.assertEqual(len(app.expander), 0)
        self.assertTrue(any("Novidades dos sistemas" in block.value for block in app.markdown))


class FeedPersistenceTests(unittest.TestCase):
    def test_merging_after_a_source_outage_preserves_the_first_discovery_and_window(self):
        original = make_update_event("sigtap", "SIGTAP", "new.zip", "2026-10-05T17:11:09+00:00")
        repeated = {**original, "found_at": "2026-10-08T16:00:00+00:00"}
        remote = {"systems": {}, "updates": [original]}
        local = {"systems": {}, "updates": [repeated],
                 "last_check": {"completed_at": NOW.isoformat(), "succeeded": 6, "total": 12}}
        merged = merge_catalogs(remote, local)
        self.assertEqual(merged["updates"], [original])
        self.assertEqual(recent_updates(merged["updates"], now=NOW), [original])
        self.assertEqual(recent_updates(merged["updates"], now=datetime(2026, 10, 12, 17, 11, 10, tzinfo=timezone.utc)), [])

    def test_brasilia_and_utc_discovery_times_have_the_same_seven_day_boundary(self):
        events = [{"name": "Brasília", "found_at": "2026-10-01T10:04:57-03:00"},
                  {"name": "UTC", "found_at": "2026-10-01T13:04:57+00:00"}]
        expires = datetime(2026, 10, 8, 13, 4, 57, tzinfo=timezone.utc)
        self.assertEqual(recent_updates(events, now=expires), events)
        self.assertEqual(recent_updates(events, now=expires + timedelta(seconds=1)), [])


if __name__ == "__main__":
    unittest.main()
