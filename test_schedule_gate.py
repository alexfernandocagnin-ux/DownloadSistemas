"""Agendamento frequente sem consultar as fontes mais de uma vez a cada ~2 horas."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from schedule_gate import should_run  # noqa: E402

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def catalog(completed_at):
    return {"last_check": {"completed_at": completed_at}}


class ScheduleGateTests(unittest.TestCase):
    def test_recent_check_skips_only_scheduled_runs(self):
        recent = catalog("2026-11-03T11:00:00+00:00")
        self.assertFalse(should_run(recent, "schedule", NOW))
        self.assertTrue(should_run(recent, "workflow_dispatch", NOW))
        self.assertTrue(should_run(recent, "push", NOW))

    def test_old_check_runs_after_one_hour_forty(self):
        self.assertTrue(should_run(catalog("2026-11-03T10:20:00+00:00"), "schedule", NOW))
        self.assertFalse(should_run(catalog("2026-11-03T10:21:00+00:00"), "schedule", NOW))

    def test_missing_or_invalid_check_always_runs(self):
        for value in [{}, {"last_check": None}, catalog(""), catalog("ontem")]:
            with self.subTest(value=value):
                self.assertTrue(should_run(value, "schedule", NOW))

    def test_utc_suffix_and_naive_dates_are_understood(self):
        self.assertFalse(should_run(catalog("2026-11-03T11:30:00Z"), "schedule", NOW))
        self.assertFalse(should_run(catalog("2026-11-03T11:30:00"), "schedule", NOW))


if __name__ == "__main__":
    unittest.main()
