"""A missing reset must neither deadlock verified weekly pools nor release their balance."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import budget_cli
import budget_policy as budgets
import claude_gate
import credits
from quota import Ledger
from test_budget_policy import stamp


class UnknownResetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "ledger.sqlite3"
        self.ledger = Ledger(self.path, timezone="Europe/Warsaw")
        self.ledger.complete_setup(services=["claude"], api_services=[], source="test")
        self.ledger.set_mode("observed")
        self.now = stamp("2026-09-07T12:00:00")

    def record(self, used=0, *, at=None, reset=None, complete=True, **metadata):
        at = self.now if at is None else at
        pool = {"pool": "weekly_scoped:example", "used_percent": used, "resets_at": reset,
                "window_minutes": 10080, "window_source": "claude.native_limit_kind", **metadata}
        if pool["window_source"] is None:
            del pool["window_source"]
        return self.ledger.record({"service": "claude", "observed_at": at, "complete": complete,
                                  "credit_resources": credits.claude_resources({"extra_usage": {"is_enabled": False}}),
                                  "source": "fixture", "pools": [pool]}, now=at)

    def test_unknown_reset_uses_full_window_without_predicting_refill(self):
        result = self.record()
        pool = result["pools"][0]
        self.assertTrue(result["allowed"], result["reasons"])
        self.assertEqual(12.5, pool["spendable_percent"])
        self.assertEqual("native_window_duration", pool["pacing_source"])
        self.assertEqual(8, pool["pacing_workdays"])
        self.assertIsNone(pool["forecast_days"])
        self.assertIsNone(pool["resets_at"])
        self.assertFalse(pool["deadline_release"])
        self.assertEqual([], result["reset_history"])

    def test_reads_restarts_repeated_refreshes_cannot_grow_the_daily_allowance(self):
        self.record()
        self.assertEqual(7.5, self.record(5, at=self.now + 1)["pools"][0]["spendable_percent"])
        self.ledger = Ledger(self.path)
        with self.ledger._connect() as db:
            before = self.ledger._budgets(db)
        for _ in range(3):
            self.ledger.check("claude", now=self.now + 1)
        with self.ledger._connect() as db:
            self.assertEqual(before, self.ledger._budgets(db))
        stopped = self.record(12.5, at=self.now + 2)
        self.assertFalse(stopped["allowed"])
        self.assertIn("weekly_scoped:example:daily_limit", stopped["reasons"])
        self.assertFalse(self.record(12.5, at=self.now + 3)["allowed"])

    def test_actual_reset_appearance_preserves_today_cap(self):
        self.record()
        actual = self.now + 7 * 86400
        result = self.record(5, at=self.now + 1, reset=actual)
        pool = result["pools"][0]
        self.assertEqual("reported_reset", pool["pacing_source"])
        self.assertEqual(actual, pool["resets_at"])
        self.assertEqual(7.5, pool["spendable_percent"])
        self.assertFalse(self.record(12.5, at=self.now + 2, reset=actual)["allowed"])

    def test_real_recovery_to_null_preserves_consumption_and_spent_grants(self):
        self.record(80, reset=self.now + 7 * 86400)
        self.ledger.budget_add("claude", 5, grant_id="one", now=self.now)
        self.record(85, at=self.now + 1, reset=self.now + 7 * 86400)
        result = self.record(0, at=self.now + 2)
        pool = result["pools"][0]
        self.assertTrue(result["allowed"])
        self.assertEqual(5, pool["daily_consumed"])
        self.assertEqual(2.5, pool["grant_remaining_percent"])
        self.assertEqual(15, pool["spendable_percent"])
        self.assertEqual(1, len(result["reset_history"]))
        self.assertIsNone(result["reset_history"][0]["resets_at"])
        self.assertFalse(self.record(15, at=self.now + 3)["allowed"])

    def test_disappearing_reset_or_changed_duration_cannot_recredit_an_anchor(self):
        self.record(reset=self.now + 7 * 86400)
        self.record(10, at=self.now + 1, reset=self.now + 7 * 86400)
        self.assertEqual(2.5, self.record(10, at=self.now + 2)["pools"][0]["spendable_percent"])
        self.record(11, at=self.now + 3, reset=self.now + 7 * 86400)
        self.assertEqual(1.5, self.record(11, at=self.now + 4, window_minutes=20160)["pools"][0]["spendable_percent"])
        self.assertFalse(self.record(12.5, at=self.now + 5)["allowed"])

    def test_deadline_withdrawal_tightens_full_balance_to_weekly_pacing(self):
        self.assertTrue(self.record(reset=stamp("2026-09-08T08:30:00"))["pools"][0]["deadline_release"])
        result = self.record(10, at=self.now + 1)
        self.assertEqual(11.25, result["pools"][0]["spendable_percent"])
        self.assertFalse(result["pools"][0]["deadline_release"])

    def test_unknown_untrusted_and_expired_metadata_still_block(self):
        self.assertFalse(self.record(window_source=None)["allowed"])
        self.assertFalse(self.record(at=self.now + 1, window_minutes=1e100)["allowed"])
        self.assertFalse(self.record(at=self.now + 2, reset=self.now + 2)["allowed"])
        self.assertFalse(self.record(at=self.now + 3, complete=False)["allowed"])
        self.assertTrue(self.record(at=self.now + 4)["allowed"])
        self.assertFalse(self.ledger.check("claude", now=self.now + 125)["allowed"])
        self.ledger.set_mode("strict")
        self.assertFalse(self.ledger.check("claude", now=self.now + 4)["allowed"])

    def test_stale_or_incomplete_transition_cannot_use_old_large_anchor(self):
        self.record(reset=stamp("2026-09-08T08:30:00"))
        result = self.record(10, at=self.now + 1, complete=False)
        self.assertFalse(result["allowed"])
        self.assertIsNone(result["pools"][0]["anchor"])
        self.assertEqual(0, result["pools"][0]["spendable_percent"])

    def test_next_day_redistributes_without_a_fake_recovery(self):
        self.record(20)
        result = self.record(24, at=stamp("2026-09-08T12:00:00"))
        self.assertEqual(4, result["pools"][0]["daily_consumed"])
        self.assertEqual(76 / 8, result["pools"][0]["spendable_percent"])
        self.assertEqual([], result["reset_history"])

    def test_work_calendar_reserve_and_cutoff_are_respected(self):
        self.ledger.budget_calendar(workdays=list(range(5)), reset_cutoff="23:59", now=self.now)
        self.ledger.budget_set("claude", "adaptive", reserve=10, now=self.now)
        pool = self.record()["pools"][0]
        self.assertEqual(6, pool["pacing_workdays"])
        self.assertEqual(15, pool["spendable_percent"])
        result = self.record(at=stamp("2026-09-12T12:00:00"))
        self.assertFalse(result["allowed"])
        self.assertEqual(0, result["pools"][0]["spendable_percent"])

    def test_dst_uses_full_duration_and_never_the_reset_cutoff(self):
        value = {"resets_at": None, "window_minutes": 10080, "window_source": "claude.native_limit_kind"}
        for day in ("2026-03-23", "2026-10-19"):
            for cutoff in ("00:00", "08:30", "23:59"):
                source, days = budgets.pacing_forecast(value, stamp(day + "T12:00:00"), "Europe/Warsaw",
                                                      {"workdays": list(range(7)), "reset_cutoff": cutoff})
                self.assertEqual(("native_window_duration", 8), (source, days))

    def test_hook_allows_paced_work_and_stops_at_its_cap(self):
        result = self.record()
        payload = {"hook_event_name": "UserPromptSubmit", "session_id": "fixture"}
        with patch.object(claude_gate.coordination, "dispatch", return_value=result):
            self.assertEqual({}, claude_gate.evaluate(payload))
        result = self.record(12.5, at=self.now + 1)
        with patch.object(claude_gate.coordination, "dispatch", return_value=result):
            self.assertFalse(claude_gate.evaluate(payload)["continue"])

    def test_budget_display_distinguishes_pacing_from_a_reported_reset(self):
        result = self.record()
        output = io.StringIO()
        with redirect_stdout(output):
            budget_cli.display({"calendar": {"timezone": "Europe/Warsaw", "calendar": budgets.calendar({})},
                                "defaults": {"default_strategy": "adaptive", "default_daily_limit": 20,
                                             "default_reserve": 0}, "services": [result]})
        self.assertIn("reset unknown", output.getvalue())
        self.assertIn("full native window across 8 workdays (not a reset prediction)", output.getvalue())


if __name__ == "__main__":
    unittest.main()
