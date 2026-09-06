import json
import multiprocessing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import budget_policy as budgets
from quota import Ledger


def stamp(value, zone="Europe/Warsaw"):
    return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo(zone)).timestamp()


def add_worker(path, identifier, now, queue):
    try:
        Ledger(path).budget_add("account", 5, grant_id=identifier, now=now)
        queue.put("ok")
    except Exception as exc:
        queue.put(type(exc).__name__)


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ledger.sqlite3"
        self.ledger = Ledger(self.path, timezone="Europe/Warsaw", reserve=10)
        self.ledger.budget_defaults(strategy="fixed", now=0)
        self.ledger.set_mode("observed")
        self.now = stamp("2026-09-06T12:00:00")
        self.reset = stamp("2026-09-13T00:00:00")

    def record(self, used=30, *, now=None, reset="default", complete=True, extra=None, **metadata):
        now = self.now if now is None else now
        data = {"service": "account", "observed_at": now, "source": "fixture", "complete": complete,
                "pools": [{"pool": "weekly", "used_percent": used,
                           "resets_at": self.reset if reset == "default" else reset, **metadata}]}
        if extra:
            data["pools"].append(extra)
        return self.ledger.record(data, now=now)

    def pool(self, result=None):
        return (result or self.ledger.check("account", now=self.now))["pools"][0]

    def adaptive(self):
        self.ledger.budget_set("account", "adaptive", reserve=0, now=self.now)
        return self.record()

    def test_calendar_forecasts_month_week_partial_and_midnight(self):
        self.assertEqual(7, budgets.forecast_days(self.now, self.reset, "Europe/Warsaw"))
        self.assertEqual(30, budgets.forecast_days(stamp("2026-09-01T12:00:00"), stamp("2026-10-01T00:00:00"), "Europe/Warsaw"))
        self.assertEqual(1, budgets.forecast_days(stamp("2026-09-06T23:59:00"), stamp("2026-09-07T00:00:00"), "Europe/Warsaw"))
        self.assertEqual(1, budgets.forecast_days(stamp("2026-09-06T23:59:00"), stamp("2026-09-07T00:00:01"), "Europe/Warsaw"))
        self.assertIsNone(budgets.forecast_days(self.now, self.now, "Europe/Warsaw"))

    def test_dst_expiry_is_local_calendar_midnight(self):
        for date, hours in (("2026-03-29", 23), ("2026-10-25", 25)):
            start = stamp(date + "T00:00:00")
            self.assertEqual(hours * 3600, budgets.midnight_after(start, "Europe/Warsaw") - start)
            self.assertEqual(1, budgets.forecast_days(start, budgets.midnight_after(start, "Europe/Warsaw"), "Europe/Warsaw"))

    def test_legacy_defaults_and_explicit_strategy_replaces_gate(self):
        self.record(10)
        self.assertFalse(self.record(31, now=self.now + 1)["allowed"])
        self.ledger.budget_set("account", "window", reserve=0, now=self.now + 1)
        result = self.ledger.check("account", now=self.now + 1)
        self.assertTrue(result["allowed"])
        self.assertEqual(69, self.pool(result)["spendable_percent"])
        self.assertEqual(21, self.pool(result)["daily_consumed"])

    def test_constructor_loads_unspecified_configuration_and_rejects_conflicts(self):
        other = Path(self.tmp.name) / "other.sqlite3"
        first = Ledger(other, timezone="UTC", daily_limit=31, reserve=0)
        reopened = Ledger(other)
        self.assertEqual(first.policy, reopened.policy)
        with self.assertRaises(ValueError):
            Ledger(other, reserve=10)
        with self.assertRaises(ValueError):
            Ledger(other, timezone="Europe/Warsaw")

    def test_frozen_daily_anchor_and_forecast_drift(self):
        self.assertEqual(10, self.pool(self.adaptive())["daily_ceiling"])
        result = self.record(35, now=self.now + 1, reset=self.reset + 86400)
        self.assertEqual(10, self.pool(result)["daily_ceiling"])
        self.assertEqual(5, self.pool(result)["spendable_percent"])
        self.assertEqual(8, self.pool(result)["forecast_days"])
        result = self.record(40, now=self.now + 2, reset=self.reset - 86400)
        self.assertFalse(result["allowed"])
        self.assertEqual(10, self.pool(result)["daily_ceiling"])
        self.assertEqual([], result["reset_history"])

    def test_next_day_redistributes_remaining(self):
        self.adaptive()
        result = self.record(35, now=stamp("2026-09-07T00:00:01"))
        self.assertAlmostEqual(65 / 6, self.pool(result)["base_allocation"])
        self.assertEqual(5, self.pool(result)["daily_consumed"])
        self.assertAlmostEqual(5 + 65 / 6, self.pool(result)["daily_ceiling"])

    def test_recovery_reanchors_without_refunding_or_recrediting_grants(self):
        self.adaptive()
        self.ledger.budget_add("account", 5, grant_id="extra", now=self.now)
        self.record(43, now=self.now + 1)
        result = self.record(2, now=self.now + 2)
        pool = self.pool(result)
        self.assertEqual(15, pool["daily_consumed"])
        self.assertEqual(14, pool["base_allocation"])
        self.assertEqual(0, pool["grant_remaining_percent"])
        self.assertEqual(29, pool["daily_ceiling"])
        self.assertEqual(14, pool["spendable_percent"])
        self.assertTrue(pool["anchor_lower_bound"])
        with self.assertRaises(ValueError):
            self.record(2, now=self.now + 2)
        self.assertEqual(29, self.pool(self.ledger.check("account", now=self.now + 2))["daily_ceiling"])

    def test_native_growth_clamp_cannot_be_evaded_by_partial_daily_counter(self):
        self.adaptive()
        self.record(41, now=self.now + 1)
        with sqlite3.connect(self.path) as db:
            state = json.loads(db.execute("SELECT value FROM state WHERE key='service:account'").fetchone()[0])
            state["days"][self.ledger._day(self.now)]["weekly"]["consumed"] = 0
            db.execute("UPDATE state SET value=? WHERE key='service:account'", (json.dumps(state),))
        result = self.ledger.check("account", now=self.now + 1)
        self.assertFalse(result["allowed"])
        self.assertIn("weekly:native_growth_limit", result["reasons"])

    def test_automatic_window_requires_allowlisted_native_provenance(self):
        self.adaptive()
        result = self.record(60, now=self.now + 1, window_minutes=300)
        self.assertEqual("adaptive", self.pool(result)["strategy"])
        result = self.record(61, now=self.now + 2, window_minutes=300,
                             window_source="codex.windowDurationMins")
        self.assertEqual("window", self.pool(result)["strategy"])
        self.assertTrue(result["allowed"])
        with self.assertRaises(ValueError):
            self.record(61, now=self.now + 3, window_minutes=300, window_source="guess")

    def test_unknown_and_elapsed_reset_deny_adaptive_but_explicit_window_allows_unknown(self):
        self.ledger.budget_set("account", "adaptive", now=self.now)
        result = self.record(reset=None)
        self.assertIn("weekly:unknown_adaptive_reset", result["reasons"])
        self.ledger.budget_use_rest("account", now=self.now)
        self.assertFalse(self.ledger.check("account", now=self.now)["allowed"])
        self.ledger.budget_set("account", "window", now=self.now)
        self.assertTrue(self.ledger.check("account", now=self.now)["allowed"])
        result = self.record(now=self.now + 1, reset=self.now + 1)
        self.assertIn("weekly:reset_needs_fresh_evidence", result["reasons"])

    def test_add_is_native_clipped_and_does_not_override_reserve(self):
        self.record(87)
        result = self.ledger.budget_add("account", 5, now=self.now)["status"]
        self.assertEqual(3, self.pool(result)["spendable_percent"])
        result = self.record(97, now=self.now + 1)
        self.assertFalse(result["allowed"])
        self.assertEqual(0, self.pool(result)["spendable_percent"])

    def test_grant_ids_bind_payload_and_expire(self):
        self.record()
        first = self.ledger.budget_add("account", 5, grant_id="same", now=self.now)
        second = self.ledger.budget_add("account", 5, grant_id="same", now=self.now + 1)
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(5, self.pool(second["status"])["granted_percent"])
        for kwargs in ({"points": 6}, {"points": 5, "pool": "weekly"}):
            with self.assertRaises(ValueError):
                self.ledger.budget_add("account", grant_id="same", now=self.now, **kwargs)
        result = self.record(31, now=first["expires_at"])
        self.assertEqual(0, self.pool(result)["granted_percent"])
        with self.assertRaises(ValueError):
            self.ledger.budget_add("account", 5, grant_id="same", now=first["expires_at"])

    def test_grant_bounds_and_atomic_pool_application(self):
        self.record(extra={"pool": "session", "used_percent": 0, "resets_at": self.reset})
        for invalid in (0, -1, 101, True, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                self.ledger.budget_add("account", invalid, now=self.now)
        self.ledger.budget_add("account", 98, pool="weekly", now=self.now)
        with self.assertRaises(ValueError):
            self.ledger.budget_add("account", 5, now=self.now)
        result = self.ledger.check("account", now=self.now)
        self.assertEqual([0, 98], [p["granted_percent"] for p in result["pools"]])

    def test_use_rest_pins_ceiling_at_recovery_and_does_not_inherit_new_pool(self):
        self.adaptive()
        first = self.ledger.budget_use_rest("account", grant_id="rest", now=self.now)
        self.assertEqual(70, self.pool(first["status"])["daily_ceiling"])
        self.record(80, now=self.now + 1)
        result = self.record(1, now=self.now + 2,
                             extra={"pool": "new", "used_percent": 20, "resets_at": self.reset})
        pools = {p["pool"]: p for p in result["pools"]}
        self.assertEqual(70, pools["weekly"]["daily_ceiling"])
        self.assertEqual(19, pools["weekly"]["spendable_percent"])
        self.assertFalse(pools["new"]["use_rest"])
        repeated = self.ledger.budget_use_rest("account", grant_id="rest-again", now=self.now + 2)
        pools = {p["pool"]: p for p in repeated["status"]["pools"]}
        self.assertEqual(70, pools["weekly"]["daily_ceiling"])

    def test_use_rest_is_zero_reserve_but_native_exhaustion_denies(self):
        self.record(95)
        result = self.ledger.budget_use_rest("account", now=self.now)["status"]
        self.assertTrue(result["allowed"])
        self.assertEqual(5, self.pool(result)["spendable_percent"])
        result = self.record(100, now=self.now + 1)
        self.assertFalse(result["allowed"])
        self.assertIn("weekly:reserve_floor", result["reasons"])

    def test_grants_require_fresh_complete_snapshot_and_never_override_strict(self):
        for action in (lambda: self.ledger.budget_add("account", 5, now=self.now),
                       lambda: self.ledger.budget_use_rest("account", now=self.now)):
            with self.assertRaises(ValueError):
                action()
        self.record(complete=False)
        with self.assertRaises(ValueError):
            self.ledger.budget_add("account", 5, now=self.now)
        self.record(now=self.now + 1)
        with self.assertRaises(ValueError):
            self.ledger.budget_use_rest("account", now=self.now + 122)
        self.ledger.set_mode("strict")
        result = self.ledger.budget_use_rest("account", now=self.now + 1)["status"]
        self.assertFalse(result["allowed"])
        self.assertIn("exact_request_bound_unavailable", result["reasons"])

    def test_config_reloads_on_existing_instance_and_preserves_history_and_grants(self):
        self.record(10)
        self.record(35, now=self.now + 1)
        other = Ledger(self.path)
        other.budget_set("account", "fixed", daily_limit=40, reserve=0, now=self.now + 1)
        other.budget_add("account", 5, now=self.now + 1)
        result = self.ledger.check("account", now=self.now + 1)
        self.assertTrue(result["allowed"])
        self.assertEqual(45, self.pool(result)["daily_ceiling"])
        other.budget_reset("account", now=self.now + 1)
        result = self.ledger.check("account", now=self.now + 1)
        self.assertEqual(25, self.pool(result)["daily_consumed"])
        self.assertEqual(5, self.pool(result)["granted_percent"])
        self.assertFalse(result["allowed"])

    def test_config_before_observation_and_pool_override(self):
        self.ledger.budget_set("account", "adaptive", reserve=0, now=self.now)
        self.ledger.budget_set("account", "fixed", daily_limit=30, pool="weekly", now=self.now)
        self.assertEqual(["account"], self.ledger.budget_services())
        self.assertEqual("fixed", self.pool(self.record())["strategy"])
        self.ledger.budget_reset("account", pool="weekly", now=self.now)
        self.assertEqual("adaptive", self.pool()["strategy"])

    def test_corrupt_budget_state_fails_closed_without_mutation(self):
        self.adaptive()
        with sqlite3.connect(self.path) as db:
            raw = db.execute("SELECT value FROM state WHERE key='budget_v1'").fetchone()[0]
        for broken in ("broken", '{}', raw.replace('"strategy": "adaptive"', '"strategy": "wrong"'),
                       raw.replace('"allocation": 10.0', '"allocation": false')):
            with sqlite3.connect(self.path) as db:
                db.execute("UPDATE state SET value=? WHERE key='budget_v1'", (broken,))
            result = self.ledger.check("account", now=self.now)
            self.assertIn("invalid_ledger", result["reasons"])
            with self.assertRaises(ValueError):
                self.ledger.budget_add("account", 5, now=self.now)

    def test_short_windows_allow_cumulative_consumption_above_100(self):
        self.ledger.budget_set("account", "window", reserve=0, now=self.now)
        self.record(0)
        self.record(90, now=self.now + 1)
        self.record(1, now=self.now + 2)
        result = self.record(80, now=self.now + 3)
        self.assertEqual(170, self.pool(result)["daily_consumed"])
        result = self.ledger.budget_add("account", 100, now=self.now + 3)["status"]
        self.assertTrue(result["allowed"])
        self.assertEqual(20, self.pool(result)["spendable_percent"])
        result = self.ledger.budget_use_rest("account", now=self.now + 3)["status"]
        self.assertEqual(190, self.pool(result)["daily_ceiling"])
        result = self.record(1, now=self.now + 4)
        self.assertEqual(19, self.pool(result)["spendable_percent"])
        self.assertEqual(190, self.pool(result)["daily_ceiling"])

    def test_rest_stays_pinned_through_policy_changes_and_recovery(self):
        self.adaptive()
        self.ledger.budget_use_rest("account", now=self.now)
        self.record(70, now=self.now + 1)
        result = self.record(2, now=self.now + 2)
        self.assertEqual(70, self.pool(result)["daily_ceiling"])
        result = self.ledger.budget_set("account", "fixed", daily_limit=100, reserve=10,
                                        now=self.now + 2)["status"]
        self.assertEqual(70, self.pool(result)["daily_ceiling"])
        self.assertEqual(28, self.pool(result)["spendable_percent"])
        result = self.ledger.budget_reset("account", now=self.now + 2)["status"]
        self.assertEqual(70, self.pool(result)["daily_ceiling"])
        self.assertEqual(0, self.pool(result)["reserve_percent"])

    def test_repeated_policy_set_and_unaffected_override_do_not_reanchor(self):
        self.adaptive()
        self.record(35, now=self.now + 1)
        result = self.ledger.budget_set("account", "adaptive", reserve=0, now=self.now + 1)["status"]
        self.assertEqual(10, self.pool(result)["daily_ceiling"])
        self.ledger.budget_set("account", "adaptive", reserve=0, pool="weekly", now=self.now + 1)
        result = self.ledger.budget_set("account", "window", reserve=0, now=self.now + 1)["status"]
        self.assertEqual(10, self.pool(result)["daily_ceiling"])

    def test_policy_change_carries_only_unspent_adaptive_additions(self):
        self.adaptive()
        self.ledger.budget_add("account", 5, now=self.now)
        self.record(43, now=self.now + 1)
        result = self.ledger.budget_set("account", "adaptive", reserve=5, now=self.now + 1)["status"]
        pool = self.pool(result)
        self.assertEqual(2, pool["grant_remaining_percent"])
        self.assertAlmostEqual(13 + 52 / 7 + 2, pool["daily_ceiling"])
        result = self.ledger.budget_set("account", "adaptive", reserve=4, now=self.now + 1)["status"]
        self.assertEqual(2, self.pool(result)["grant_remaining_percent"])

    def test_fixed_grants_remain_absolute_across_recovery(self):
        self.record(0)
        self.ledger.budget_add("account", 10, now=self.now)
        self.record(25, now=self.now + 1)
        result = self.record(1, now=self.now + 2)
        self.assertEqual(26, self.pool(result)["daily_consumed"])
        self.assertEqual(30, self.pool(result)["daily_ceiling"])
        self.assertEqual(4, self.pool(result)["spendable_percent"])

    def test_morning_cutoff_excludes_the_reset_date(self):
        now = stamp("2026-09-06T23:59:00")
        self.assertEqual(2, budgets.forecast_days(now, now + 25 * 3600, "Europe/Warsaw"))

    def test_concurrent_grants_no_lost_updates_and_idempotency(self):
        self.record()
        queue = multiprocessing.Queue()
        ids = ["same", "same", "one", "two", "three"]
        workers = [multiprocessing.Process(target=add_worker, args=(str(self.path), key, self.now, queue)) for key in ids]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            self.assertEqual(0, worker.exitcode)
        self.assertEqual(["ok"] * 5, [queue.get(timeout=2) for _ in workers])
        self.assertEqual(20, self.pool()["granted_percent"])


if __name__ == "__main__":
    unittest.main()
