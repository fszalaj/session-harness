import json
import io
import sys
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch
import quota
import multiprocessing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from contextlib import closing

from quota import Ledger


def parallel_record(path, timestamp, queue):
    try:
        ledger = Ledger(path)
        ledger.record(snapshot(timestamp, timestamp - 1000), now=timestamp)
        queue.put("ok")
    except ValueError:
        queue.put("ordered")


def parallel_mode(path):
    ledger = Ledger(path)
    for mode in ("observed", "strict", "observed"):
        ledger.set_mode(mode)


def snapshot(timestamp=1000, used=64, reset=100000, complete=True):
    return dict(service="codex-personal", observed_at=timestamp, complete=complete,
                source="native-test", pools=[dict(pool="weekly", used_percent=used, resets_at=reset)])


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "private/ledger.sqlite3"
        self.ledger = Ledger(self.path, timezone="Europe/Warsaw", reserve=10)
        self.ledger.budget_defaults(strategy="fixed", now=0)

    def record(self, timestamp=1000, used=64, **kwargs):
        return self.ledger.record(snapshot(timestamp, used, **kwargs), now=timestamp, initialize=True)

    def test_diagnostic_flag_cannot_authorize_check_in_strict_mode(self):
        self.record()
        base = ["quota.py", "check", "--service", "codex-personal", "--db", str(self.path)]
        with patch.object(sys, "argv", base + ["--observed-only"]), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                quota.main()
        self.assertEqual(2, caught.exception.code)
        with patch.object(sys, "argv", base), patch.object(quota.time, "time", return_value=1000), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(2, quota.main())
        self.assertFalse(json.loads(output.getvalue())["allowed"])
        base[1] = "status"
        with patch.object(sys, "argv", base + ["--observed-only"]), \
                patch.object(quota.time, "time", return_value=1000), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, quota.main())
        self.assertTrue(json.loads(output.getvalue())["allowed"])
        self.assertEqual("strict", self.ledger.mode())

    def test_initial_history_requires_explicit_baseline(self):
        result = self.ledger.record(snapshot(), now=1000)
        self.assertFalse(result["allowed_by_observed_threshold"])
        self.assertIn("weekly:unknown_daily_consumption", result["reasons"])

    def test_baseline_and_exact_cap_separate(self):
        result = self.record()
        self.assertTrue(result["allowed_by_observed_threshold"])
        self.assertTrue(result["pools"][0]["history_partial"])
        self.assertFalse(result["allowed"])
        self.assertFalse(result["exact_cap_supported"])
        self.assertTrue(self.ledger.check("codex-personal", now=1000, strict=False)["allowed"])

    def test_daily_boundary(self):
        self.record()
        self.assertTrue(self.record(1001, 83.99)["allowed_by_observed_threshold"])
        result = self.record(1002, 84)
        self.assertIn("weekly:daily_limit", result["reasons"])

    def test_reserve_boundary_every_pool(self):
        data = snapshot()
        data["pools"].append(dict(pool="session", used_percent=90, resets_at=5000))
        result = self.ledger.record(data, now=1000, initialize=True)
        self.assertIn("session:reserve_floor", result["reasons"])

    def test_reset_never_refunds_daily(self):
        self.record()
        self.record(1001, 74)
        result = self.record(1002, 2, reset=200000)
        self.assertEqual(result["pools"][0]["daily_consumed"], 12)
        self.assertFalse(result["allowed_by_observed_threshold"])
        self.assertEqual(result["reset_history"][0]["resets_at"], 200000)
        self.assertEqual(self.record(1003, 12, reset=200000)["pools"][0]["daily_consumed"], 22)

    def test_changed_reset_without_drop_is_ambiguous(self):
        self.record()
        self.assertFalse(self.record(1001, 65, reset=200000)["allowed_by_observed_threshold"])

    def test_gap_and_stale(self):
        self.record()
        self.assertFalse(self.ledger.check("codex-personal", now=1121)["allowed_by_observed_threshold"])
        self.assertFalse(self.record(1400, 65)["allowed_by_observed_threshold"])

    def test_reset_time_alone_never_renews(self):
        self.record(reset=1010)
        result = self.ledger.check("codex-personal", now=1011)
        self.assertIn("weekly:reset_needs_fresh_evidence", result["reasons"])
        self.assertFalse(self.record(1012, 64, reset=1010)["allowed_by_observed_threshold"])

    def test_unreported_reset_schedule_preserves_budget_and_reserve(self):
        self.ledger.set_mode("observed")
        initial = self.record(1000, 0, reset=None)
        self.assertTrue(initial["allowed"])
        self.assertIsNone(initial["pools"][0]["resets_at"])
        self.assertFalse(initial["pools"][0]["reset_schedule_known"])
        self.assertTrue(self.record(1001, 19, reset=None)["allowed"])
        self.assertIn("weekly:daily_limit", self.record(1002, 20, reset=None)["reasons"])
        reset = self.record(1003, 1, reset=9999)
        self.assertEqual(reset["pools"][0]["daily_consumed"], 21)
        self.assertFalse(reset["allowed"])
        self.assertTrue(reset["pools"][0]["reset_schedule_known"])
        self.assertIsNone(reset["reset_history"][0]["prior_reset"])

    def test_unknown_schedule_does_not_bypass_staleness_strict_or_reserve(self):
        self.assertFalse(self.record(1000, 89, reset=None)["allowed"])
        self.ledger.set_mode("observed")
        self.assertFalse(self.ledger.check("codex-personal", now=1121)["allowed"])
        self.assertIn("weekly:reserve_floor", self.record(1122, 90, reset=None)["reasons"])
        malformed = snapshot(1123, 0)
        del malformed["pools"][0]["resets_at"]
        with self.assertRaises(ValueError):
            self.ledger.record(malformed, now=1123)

    def test_incomplete_and_disappearing_pool(self):
        self.record()
        self.assertFalse(self.record(1001, 65, complete=False)["allowed_by_observed_threshold"])
        data = snapshot(1002, 1)
        data["pools"][0]["pool"] = "new-pool"
        result = self.ledger.record(data, now=1002, initialize=True)
        self.assertIn("incomplete_pools", result["reasons"])

    def test_calendar_midnight_conservatively_attributes_delta(self):
        timestamp = datetime(2026, 9, 6, 23, 59, 59, tzinfo=ZoneInfo("Europe/Warsaw")).timestamp()
        self.record(timestamp, 10, reset=timestamp + 50000)
        self.record(timestamp + 0.5, 29, reset=timestamp + 50000)
        self.assertFalse(self.ledger.check("codex-personal", now=timestamp + 2)["allowed_by_observed_threshold"])
        result = self.record(timestamp + 2, 31, reset=timestamp + 50000)
        self.assertEqual(result["day"], "2026-09-07")
        self.assertEqual(result["pools"][0]["daily_consumed"], 2)

    def test_invalid_inputs_and_policy_mismatch(self):
        for used in [float("nan"), float("inf"), -1, 101, True]:
            with self.assertRaises(ValueError):
                self.record(1000, used)
        with self.assertRaises(ValueError):
            self.ledger.record(snapshot(1001), now=1000)
        with self.assertRaises(ValueError):
            Ledger(self.path, timezone="UTC")

    def test_permissions_and_allowlisted_storage(self):
        data = snapshot()
        data["secret"] = "NEVER_STORE_THIS"
        self.ledger.record(data, now=1000, initialize=True)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        self.assertNotIn(b"NEVER_STORE_THIS", self.path.read_bytes())

    def test_corruption_denies(self):
        self.record()
        with closing(sqlite3.connect(self.path)) as db:
            with db:
                db.execute("UPDATE state SET value='broken' WHERE key='service:codex-personal'")
        self.assertFalse(self.ledger.check("codex-personal", now=1000)["allowed"])

    def test_corrupt_daily_accounting_cannot_restore_observed_budget(self):
        self.ledger.set_mode("observed")
        self.record(1000, 10)
        self.record(1001, 35)
        with closing(sqlite3.connect(self.path)) as db:
            original = json.loads(db.execute(
                "SELECT value FROM state WHERE key='service:codex-personal'").fetchone()[0])
        day = self.ledger._day(1001)
        for corruption in ("days", "date", "pool", "boolean_count", "boolean_history"):
            with self.subTest(corruption=corruption):
                state = json.loads(json.dumps(original))
                if corruption == "days":
                    del state["days"]
                elif corruption == "date":
                    del state["days"][day]
                elif corruption == "pool":
                    del state["days"][day]["weekly"]
                elif corruption == "boolean_count":
                    state["days"][day]["weekly"]["consumed"] = False
                else:
                    state["days"][day]["weekly"]["history_partial"] = "false"
                with closing(sqlite3.connect(self.path)) as db:
                    with db:
                        db.execute("UPDATE state SET value=? WHERE key='service:codex-personal'",
                                   (json.dumps(state),))
                result = self.ledger.check("codex-personal", now=1001)
                self.assertFalse(result["allowed"])
                self.assertIn("invalid_ledger", result["reasons"])
                self.assertEqual(result["pools"], [])
                with self.assertRaises(ValueError):
                    self.record(1002, 36)

    def test_invalid_persisted_mode_fails_closed(self):
        self.record()
        with closing(sqlite3.connect(self.path)) as db:
            with db:
                db.execute("INSERT INTO state VALUES ('admission_mode', ?)", ('"unrecognized"',))
        result = self.ledger.check("codex-personal", now=1000)
        self.assertFalse(result["allowed"])
        self.assertIn("invalid_ledger", result["reasons"])

    def test_observed_mode_persists_and_preserves_prior_counts(self):
        self.record(1000, 10)
        self.record(1001, 25)
        self.ledger.set_mode("observed")
        reopened = Ledger(self.path)
        self.assertEqual(reopened.mode(), "observed")
        result = reopened.check("codex-personal", now=1001)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["pools"][0]["daily_consumed"], 15)
        self.assertTrue(result["in_flight_overshoot_possible"])
        reopened.set_mode("strict")
        self.assertFalse(reopened.check("codex-personal", now=1001)["allowed"])
        self.assertEqual(reopened.check("codex-personal", now=1001)["pools"][0]["daily_consumed"], 15)

    def test_observed_mode_recovers_after_gap_with_honest_partial_history(self):
        self.record(1000, 10)
        self.record(2000, 13)
        self.ledger.set_mode("observed")
        result = self.ledger.check("codex-personal", now=2000)
        self.assertTrue(result["allowed"])
        self.assertTrue(result["pools"][0]["history_partial"])
        self.assertTrue(result["pools"][0]["daily_consumption_lower_bound"])
        self.assertEqual(result["pools"][0]["daily_consumed"], 3)
        self.assertFalse(self.ledger.check("codex-personal", now=2121)["allowed"])

    def test_observed_reset_drop_counts_new_window_use_and_stops_at_limit(self):
        self.ledger.set_mode("observed")
        self.record(1000, 40)
        self.record(1001, 57)
        result = self.record(1002, 3, reset=200000)
        self.assertEqual(result["pools"][0]["daily_consumed"], 20)
        self.assertIn("weekly:daily_limit", result["reasons"])
        self.assertFalse(result["allowed"])
        self.assertEqual(self.record(1003, 1, reset=300000)["pools"][0]["daily_consumed"], 21)

    def test_reset_estimate_drift_never_records_actual_reset_or_refunds(self):
        self.ledger.set_mode("observed")
        self.record(1000, 10)
        result = self.record(1001, 12, reset=200000)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["pools"][0]["daily_consumed"], 2)
        self.assertEqual(result["reset_history"], [])

    def test_observed_mode_still_requires_current_complete_metadata(self):
        self.ledger.set_mode("observed")
        self.assertFalse(self.ledger.check("codex-personal", now=1000)["allowed"])
        self.assertFalse(self.record(1000, 10, complete=False)["allowed"])
        self.assertFalse(self.record(1001, 90)["allowed"])
        self.assertFalse(self.record(1002, 10, reset=1002)["allowed"])

    def test_observed_opt_in_accepts_prospective_baseline_without_claiming_history(self):
        self.ledger.set_mode("observed")
        result = self.ledger.record(snapshot(), now=1000)
        self.assertTrue(result["allowed"])
        self.assertTrue(result["pools"][0]["daily_consumption_lower_bound"])

    def test_process_concurrency_never_loses_monotonic_consumption(self):
        self.record(1000, 0)
        queue = multiprocessing.Queue()
        processes = [multiprocessing.Process(target=parallel_record, args=(str(self.path), t, queue))
                     for t in range(1001, 1009)]
        processes.append(multiprocessing.Process(target=parallel_mode, args=(str(self.path),)))
        for process in processes:
            process.start()
        for process in processes:
            process.join(10)
            self.assertEqual(process.exitcode, 0)
        results = [queue.get(timeout=2) for _ in range(8)]
        self.assertIn("ok", results)
        result = self.ledger.check("codex-personal", now=1008)
        self.assertEqual(result["pools"][0]["daily_consumed"], 8)
        self.assertEqual(self.ledger.mode(), "observed")


if __name__ == "__main__":
    unittest.main()
