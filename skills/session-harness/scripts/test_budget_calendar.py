"""Calendar pacing preserves native balances and explicit daily grants."""
from contextlib import closing
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from zoneinfo import ZoneInfo

import budget_policy as budgets
from quota import Ledger


ZONE = "Europe/Warsaw"


def stamp(value, *, fold=0):
    return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo(ZONE), fold=fold).timestamp()


class CalendarMathTests(unittest.TestCase):
    def test_cutoff_includes_previous_day_through_exact_second(self):
        now = stamp("2026-09-07T12:00:00")
        self.assertEqual(1, budgets.forecast_days(now, stamp("2026-09-08T08:30:00"), ZONE))
        self.assertEqual(2, budgets.forecast_days(now, stamp("2026-09-08T08:30:01"), ZONE))
        self.assertEqual(1, budgets.forecast_days(now, stamp("2026-09-07T12:00:01"), ZONE))
        self.assertIsNone(budgets.forecast_days(now, now, ZONE))

    def test_leap_day_and_month_boundary(self):
        self.assertEqual(2, budgets.forecast_days(stamp("2028-02-28T12:00:00"),
                                                stamp("2028-03-01T08:30:00"), ZONE))
        self.assertEqual(3, budgets.forecast_days(stamp("2028-02-28T12:00:00"),
                                                stamp("2028-03-01T08:30:01"), ZONE))
        self.assertEqual(1, budgets.forecast_days(stamp("2026-12-31T23:59:00"),
                                                stamp("2027-01-01T08:30:00"), ZONE))

    def test_workdays_exclude_weekend_and_cutoff_reset_date(self):
        schedule = {"workdays": list(range(5)), "reset_cutoff": "08:30"}
        friday = stamp("2026-09-04T12:00:00")
        monday = stamp("2026-09-07T08:30:00")
        self.assertEqual(1, budgets.forecast_days(friday, monday, ZONE, schedule))
        self.assertEqual(2, budgets.forecast_days(friday, monday + 1, ZONE, schedule))
        self.assertEqual(0, budgets.forecast_days(stamp("2026-09-05T12:00:00"), monday,
                                                ZONE, schedule))

    def test_long_horizon_matches_calendar_iteration(self):
        schedule = {"workdays": [0, 2, 4], "reset_cutoff": "08:30"}
        start = datetime(2026, 9, 7).date()
        last = datetime(2056, 3, 1).date()
        expected = sum((start + timedelta(days=i)).weekday() in schedule["workdays"]
                       for i in range((last - start).days + 1))
        self.assertEqual(expected, budgets.forecast_days(stamp("2026-09-07T12:00:00"),
                         stamp("2056-03-01T08:30:01"), ZONE, schedule))

    def test_dst_days_use_local_deadline_instead_of_fixed_utc_duration(self):
        schedule = budgets.calendar({})
        for day, tomorrow, elapsed in (("2026-03-28", "2026-03-29", 23),
                                      ("2026-10-24", "2026-10-25", 25)):
            with self.subTest(day=day):
                now = stamp(day + "T08:30:00")
                reset = stamp(tomorrow + "T08:30:00")
                self.assertEqual(elapsed * 3600, reset - now)
                self.assertTrue(budgets.deadline_release({"resets_at": reset}, now, ZONE, schedule))
                self.assertFalse(budgets.deadline_release({"resets_at": reset + 1}, now, ZONE, schedule))
                self.assertEqual(1, budgets.forecast_days(now, reset, ZONE))

    def test_both_dst_fold_instants_have_same_calendar_horizon(self):
        first = stamp("2026-10-25T02:30:00", fold=0)
        second = stamp("2026-10-25T02:30:00", fold=1)
        self.assertEqual(3600, second - first)
        reset = stamp("2026-10-26T08:30:00")
        for now in (first, second):
            self.assertEqual(1, budgets.forecast_days(now, reset, ZONE))
            self.assertTrue(budgets.deadline_release({"resets_at": reset}, now, ZONE, budgets.calendar({})))


class CalendarLedgerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "ledger.db"
        self.ledger = Ledger(self.path, timezone=ZONE, reserve=0)
        self.ledger.complete_setup(services=["account"], api_services=[], source="test")
        self.ledger.set_mode("observed")
        self.now = stamp("2026-09-07T12:00:00")
        self.reset = stamp("2026-09-14T08:30:00")

    def record(self, used=30, *, now=None, reset=None, complete=True, extra=None):
        now = self.now if now is None else now
        pools = [{"pool": "weekly", "used_percent": used,
                  "resets_at": self.reset if reset is None else reset}]
        if extra:
            pools.append(extra)
        return self.ledger.record({"service": "account", "source": "fixture", "complete": complete,
                                   "observed_at": now, "pools": pools}, now=now)

    def adaptive(self, reserve=0):
        self.ledger.budget_set("account", "adaptive", reserve=reserve, now=self.now)
        return self.record()

    def pool(self, result):
        return next(pool for pool in result["pools"] if pool["pool"] == "weekly")

    def stored(self, key="budget_v1"):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def test_default_calendar_and_workday_metadata(self):
        pool = self.pool(self.adaptive())
        self.assertEqual(7, pool["workdays_remaining"])
        self.assertTrue(pool["scheduled_workday"])
        self.assertFalse(pool["deadline_release"])
        self.assertEqual(10, pool["spendable_percent"])
        self.assertEqual({"workdays": list(range(7)), "reset_cutoff": "08:30"}, pool["calendar"])

    def test_deadline_releases_current_balance_past_exhausted_epoch_allocation(self):
        self.adaptive()
        self.assertFalse(self.record(45, now=self.now + 1)["allowed"])
        result = self.record(46, now=self.now + 2, reset=stamp("2026-09-08T08:30:00"))
        pool = self.pool(result)
        self.assertTrue(result["allowed"])
        self.assertTrue(pool["deadline_release"])
        self.assertEqual(54, pool["spendable_percent"])
        self.assertEqual(16, pool["daily_consumed"])
        self.assertEqual(10, pool["anchor"]["allocation"])

    def test_later_forecast_withdraws_release_without_refunding_consumption(self):
        self.adaptive()
        cutoff = stamp("2026-09-08T08:30:00")
        self.assertTrue(self.pool(self.record(45, now=self.now + 1, reset=cutoff))["deadline_release"])
        result = self.record(46, now=self.now + 2, reset=cutoff + 1)
        self.assertFalse(result["allowed"])
        self.assertFalse(self.pool(result)["deadline_release"])
        self.assertEqual(16, self.pool(result)["daily_consumed"])
        self.assertEqual(0, self.pool(result)["spendable_percent"])

    def test_initial_deadline_anchor_repaces_after_reset_moves_later(self):
        self.ledger.budget_set("account", "adaptive", reserve=0, now=self.now)
        initial = self.record(reset=stamp("2026-09-08T08:30:00"))
        self.assertEqual(70, self.pool(initial)["spendable_percent"])
        self.assertTrue(self.pool(initial)["deadline_release"])
        result = self.record(31, now=self.now + 1)
        pool = self.pool(result)
        self.assertTrue(result["allowed"])
        self.assertFalse(pool["deadline_release"])
        self.assertEqual(1, pool["daily_consumed"])
        self.assertAlmostEqual(69 / 7, pool["spendable_percent"])
        self.assertAlmostEqual(1 + 69 / 7, pool["daily_ceiling"])
        self.assertEqual([], result["reset_history"])
        grants = self.ledger.budget_add("account", 100, grant_id="native-clipped", now=self.now + 1)
        self.assertEqual(69, self.pool(grants["status"])["spendable_percent"])

    def test_initial_deadline_withdrawal_waits_for_complete_fresh_write(self):
        self.ledger.budget_set("account", "adaptive", reserve=0, now=self.now)
        self.record(reset=stamp("2026-09-08T08:30:00"))
        result = self.record(31, now=self.now + 1, complete=False)
        self.assertFalse(result["allowed"])
        self.assertIn("weekly:budget_anchor_missing", result["reasons"])
        before = self.stored()
        self.ledger.check("account", now=self.now + 1)
        self.assertEqual(before, self.stored())
        result = self.record(32, now=self.now + 2)
        self.assertTrue(result["allowed"])
        self.assertEqual(2, self.pool(result)["daily_consumed"])
        self.assertAlmostEqual(68 / 7, self.pool(result)["spendable_percent"])

    def test_deadline_origin_reanchor_does_not_recredit_spent_grants(self):
        self.adaptive()
        self.ledger.budget_add("account", 5, grant_id="partly-spent", now=self.now)
        self.record(43, now=self.now + 1, reset=stamp("2026-09-08T08:30:00"))
        self.ledger.budget_calendar(reset_cutoff="09:00", now=self.now + 1)
        result = self.record(44, now=self.now + 2)
        pool = self.pool(result)
        self.assertFalse(pool["deadline_release"])
        self.assertEqual(14, pool["daily_consumed"])
        self.assertEqual(2, pool["grant_remaining_percent"])
        self.assertEqual(8 + 2, pool["spendable_percent"])
        self.assertEqual(14 + 8 + 2, pool["daily_ceiling"])

    def test_deadline_keeps_explicit_reserve_and_strict_mode(self):
        self.adaptive(reserve=10)
        result = self.record(50, now=self.now + 1, reset=stamp("2026-09-08T08:30:00"))
        self.assertEqual(40, self.pool(result)["spendable_percent"])
        self.ledger.set_mode("strict")
        result = self.ledger.check("account", now=self.now + 1)
        self.assertFalse(result["allowed"])
        self.assertIn("exact_request_bound_unavailable", result["reasons"])

    def test_stale_or_incomplete_all_pool_evidence_never_releases_deadline(self):
        self.adaptive()
        cutoff = stamp("2026-09-08T08:30:00")
        self.record(now=self.now + 1, reset=cutoff)
        result = self.ledger.check("account", now=self.now + 122)
        self.assertFalse(result["allowed"])
        self.assertFalse(self.pool(result)["deadline_release"])
        result = self.record(now=self.now + 123, reset=cutoff, complete=False)
        self.assertFalse(result["allowed"])
        self.assertFalse(self.pool(result)["deadline_release"])

    def test_missing_sibling_pool_prevents_release_for_fresh_weekly_pool(self):
        self.adaptive()
        self.record(now=self.now + 1, extra={"pool": "session", "used_percent": 1,
                                           "resets_at": self.reset})
        result = self.record(now=self.now + 2, reset=stamp("2026-09-08T08:30:00"))
        self.assertIn("incomplete_pools", result["reasons"])
        self.assertFalse(self.pool(result)["deadline_release"])

    def test_off_day_denies_base_but_add_and_rest_explicitly_allow_work(self):
        self.now = stamp("2026-09-06T12:00:00")
        self.ledger.budget_calendar(workdays=list(range(5)), now=self.now)
        result = self.adaptive()
        self.assertFalse(result["allowed"])
        self.assertFalse(self.pool(result)["scheduled_workday"])
        self.assertEqual(0, self.pool(result)["spendable_percent"])
        self.assertFalse(self.pool(self.record(now=self.now + 1,
                         reset=stamp("2026-09-07T08:30:00")))["deadline_release"])
        result = self.ledger.budget_add("account", 5, grant_id="off-day", now=self.now + 1)["status"]
        self.assertTrue(result["allowed"])
        self.assertEqual(5, self.pool(result)["spendable_percent"])
        self.assertFalse(self.record(35, now=self.now + 2)["allowed"])
        result = self.ledger.budget_use_rest("account", now=self.now + 2)["status"]
        self.assertTrue(result["allowed"])
        self.assertEqual(65, self.pool(result)["spendable_percent"])

    def test_weekday_schedule_divides_only_working_dates(self):
        self.ledger.budget_calendar(workdays=list(range(5)), now=self.now)
        pool = self.pool(self.adaptive())
        self.assertEqual(5, pool["workdays_remaining"])
        self.assertEqual(14, pool["spendable_percent"])

    def test_calendar_change_invalidates_stale_anchor_then_fresh_record_reanchors(self):
        self.adaptive()
        self.record(35, now=self.now + 1)
        self.ledger.budget_calendar(workdays=list(range(5)), now=self.now + 122)
        result = self.ledger.check("account", now=self.now + 122)
        self.assertFalse(result["allowed"])
        self.assertIn("weekly:budget_anchor_missing", result["reasons"])
        result = self.record(35, now=self.now + 123)
        self.assertTrue(result["allowed"])
        self.assertEqual(5, self.pool(result)["daily_consumed"])
        self.assertEqual(13, self.pool(result)["spendable_percent"])

    def test_calendar_noop_and_reads_do_not_reanchor_or_mutate_audit(self):
        self.adaptive()
        self.record(35, now=self.now + 1)
        before = self.stored()
        self.ledger.budget_calendar(workdays=list(range(7)), reset_cutoff="08:30", now=self.now + 1)
        self.assertEqual(before["anchors"], self.stored()["anchors"])
        self.assertEqual(5, self.pool(self.ledger.check("account", now=self.now + 1))["spendable_percent"])
        before = self.stored()
        self.ledger.budget_calendar(now=self.now + 1)
        for _ in range(3):
            self.ledger.check("account", now=self.now + 1)
        self.assertEqual(before, self.stored())

    def test_deadline_transitions_are_audited_on_writes_only(self):
        self.adaptive()
        self.record(now=self.now + 1, reset=stamp("2026-09-08T08:30:00"))
        before = self.stored()
        self.ledger.check("account", now=self.now + 1)
        self.assertEqual(before, self.stored())
        self.record(now=self.now + 2)
        transitions = [event["active"] for event in self.stored()["audit"]
                       if event["action"] == "deadline_release" and event["pool"] == "weekly"]
        self.assertEqual([True, False], transitions[-2:])

    def test_calendar_changes_preserve_daily_counters_and_grants(self):
        self.adaptive()
        self.ledger.budget_add("account", 5, grant_id="preserved", now=self.now)
        self.record(33, now=self.now + 1)
        accounting = self.stored("service:account")
        grants = self.stored()["grants"]
        self.ledger.budget_calendar(workdays=[0, 2, 4], reset_cutoff="09:00", now=self.now + 1)
        self.assertEqual(accounting, self.stored("service:account"))
        self.assertEqual(grants, self.stored()["grants"])

    def test_custom_cutoff_changes_release_at_the_exact_local_boundary(self):
        self.ledger.budget_calendar(reset_cutoff="06:00", now=self.now)
        self.adaptive()
        reset = stamp("2026-09-08T06:00:00")
        result = self.record(45, now=self.now + 1, reset=reset)
        self.assertTrue(self.pool(result)["deadline_release"])
        self.assertEqual(55, self.pool(result)["spendable_percent"])
        result = self.record(46, now=self.now + 2, reset=reset + 1)
        self.assertFalse(self.pool(result)["deadline_release"])
        self.assertFalse(result["allowed"])

    def test_defaults_changes_preserve_accounting_grants_and_explicit_policy(self):
        self.adaptive(reserve=7)
        self.ledger.budget_add("account", 5, grant_id="defaults-survivor", now=self.now)
        self.record(33, now=self.now + 1)
        accounting = self.stored("service:account")
        grants = self.stored()["grants"]
        self.ledger.budget_defaults(reserve=4, now=self.now + 1)
        self.assertEqual(accounting, self.stored("service:account"))
        self.assertEqual(grants, self.stored()["grants"])
        result = self.ledger.check("account", now=self.now + 1)
        self.assertEqual(7, self.pool(result)["reserve_percent"])
        self.assertEqual(3, self.pool(result)["daily_consumed"])
        before = self.stored()
        self.ledger.budget_defaults(now=self.now + 1)
        self.assertEqual(before, self.stored())

    def test_use_rest_remains_pinned_when_recovery_enters_deadline(self):
        self.adaptive()
        self.ledger.budget_use_rest("account", grant_id="pinned", now=self.now)
        self.record(80, now=self.now + 1)
        result = self.record(1, now=self.now + 2, reset=stamp("2026-09-08T08:30:00"))
        pool = self.pool(result)
        self.assertEqual(70, pool["daily_ceiling"])
        self.assertEqual(51, pool["daily_consumed"])
        self.assertEqual(19, pool["spendable_percent"])
        self.assertFalse(pool["deadline_release"])

    def test_calendar_validation_is_atomic(self):
        self.adaptive()
        before = self.stored()
        for kwargs in ({"workdays": []}, {"workdays": [7]}, {"workdays": [True]},
                       {"reset_cutoff": "24:00"}, {"reset_cutoff": "08:30:01"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.ledger.budget_calendar(now=self.now, **kwargs)
            self.assertEqual(before, self.stored())


class CalendarDefaultsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "ledger.db"
        self.now = stamp("2026-09-07T12:00:00")

    def test_new_ledger_uses_utc_and_zero_reserve(self):
        ledger = Ledger(self.path)
        self.assertEqual("UTC", ledger.policy["timezone"])
        self.assertEqual(0, ledger.policy["reserve"])
        self.assertEqual(20, ledger.policy["daily_limit"])
        self.assertEqual("strict", ledger.mode())
        self.assertEqual("adaptive", ledger.budget_defaults()["default_strategy"])

    def test_legacy_policy_survives_reopen_and_defaults_override_future_partial_set(self):
        legacy = Ledger(self.path, timezone=ZONE, reserve=10)
        with legacy._connect() as db:
            db.execute("DELETE FROM state WHERE key='budget_v1'")
        reopened = Ledger(self.path)
        self.assertEqual("fixed", reopened.budget_defaults()["default_strategy"])
        self.assertEqual(legacy.policy, reopened.policy)
        self.assertEqual(10, reopened.policy["reserve"])
        reopened.budget_defaults(reserve=0, now=self.now)
        result = reopened.budget_set("new-service", "adaptive", now=self.now)
        self.assertEqual(0, result["budget_policy"]["reserve"])
        self.assertEqual(10, Ledger(self.path).policy["reserve"])

    def test_explicit_pool_reserve_wins_and_reset_uses_updated_fallback(self):
        ledger = Ledger(self.path, timezone=ZONE, reserve=10)
        ledger.set_mode("observed")
        ledger.budget_set("account", "adaptive", reserve=7, pool="weekly", now=self.now)
        ledger.budget_defaults(reserve=0, now=self.now)
        ledger.record({"service": "account", "source": "fixture", "complete": True,
                       "observed_at": self.now, "pools": [{"pool": "weekly", "used_percent": 20,
                       "resets_at": self.now + 7 * 86400}]}, now=self.now)
        self.assertEqual(7, ledger.check("account", now=self.now)["pools"][0]["reserve_percent"])
        result = ledger.budget_reset("account", pool="weekly", now=self.now)["status"]
        self.assertEqual(0, result["pools"][0]["reserve_percent"])
        self.assertEqual("adaptive", result["pools"][0]["strategy"])


if __name__ == "__main__":
    unittest.main()
