"""Monthly workday pacing, stable daily anchors and setup admission."""
from datetime import datetime, timezone
import multiprocessing
from pathlib import Path
import tempfile
import unittest

from quota import Ledger
from spend import SpendLedger, ticks
from test_spend import DIGEST, complete_setup


def stamp(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()


MIDMONTH = stamp("2026-01-15T12:00:00")
TWO_DAYS = stamp("2026-01-30T12:00:00")


def reserve_contender(path, ident, queue):
    try:
        result = SpendLedger(path).authorize("api:xai", "7", "USD", DIGEST, ident, MIDMONTH)
        queue.put(result["dispatch"])
    except ValueError:
        queue.put(False)


class PacingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "ledger.sqlite3"
        self.money = SpendLedger(self.path)
        complete_setup(self.money.ledger)
        self.money.configure("total", "170", mode="observed")

    def authorize(self, value, ident="request", now=MIDMONTH, scope="api:xai"):
        return self.money.authorize(scope, value, "USD", DIGEST, ident, now)

    def cap(self, now=MIDMONTH, scope="total"):
        return next(c for c in self.money.status(now)["caps"] if c["scope"] == scope)

    def stored_counts(self):
        with self.money.ledger._connect() as db:
            return tuple(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                         for table in ("money_daily_anchors", "money_audit", "money_requests"))

    def test_monthly_default_and_next_day_use_remaining_budget_and_days(self):
        self.assertEqual(17, self.cap()["workdays_remaining"])
        self.assertEqual(ticks("10"), self.cap()["daily_available_ticks"])
        self.authorize("10")
        with self.assertRaisesRegex(ValueError, "daily"):
            self.authorize("0.01", "excess")
        next_day = stamp("2026-01-16T12:00:00")
        self.assertEqual(16, self.cap(next_day)["workdays_remaining"])
        self.assertEqual(ticks("10"), self.cap(next_day)["daily_available_ticks"])
        self.authorize("10", "tomorrow", next_day)
        self.assertEqual(ticks("20"), self.cap(next_day)["pending_ticks"])

    def test_restart_noop_configuration_and_status_preserve_anchor(self):
        self.authorize("6")
        counts = self.stored_counts()
        self.money = SpendLedger(self.path)
        self.money.configure("total", "170", mode="observed")
        self.money.ledger.budget_calendar(workdays=list(range(7)), now=MIDMONTH)
        for _ in range(2):
            self.assertEqual(ticks("4"), self.cap()["daily_available_ticks"])
        self.assertEqual(counts, self.stored_counts())
        with self.assertRaisesRegex(ValueError, "daily"):
            self.authorize("5", "too-much")
        self.assertEqual(counts, self.stored_counts())

    def test_status_only_forecasts_without_writing_anchors_or_audit(self):
        counts = self.stored_counts()
        self.cap()
        self.cap(stamp("2026-02-01T12:00:00"))
        self.assertEqual(counts, self.stored_counts())
        self.assertEqual(0, counts[0])

    def test_configuration_change_redistributes_without_refunding_today(self):
        self.money.configure("total", "20", mode="observed")
        self.authorize("6", now=TWO_DAYS)
        self.money.configure("total", "40", mode="observed")
        self.assertEqual(ticks("6"), self.cap(TWO_DAYS)["daily_debit_ticks"])
        self.assertEqual(ticks("14"), self.cap(TWO_DAYS)["daily_available_ticks"])
        self.authorize("14", "redistributed", TWO_DAYS)
        self.money.configure("total", "40", mode="observed")
        self.assertEqual(0, self.cap(TWO_DAYS)["daily_available_ticks"])
        self.assertEqual(ticks("20"), self.cap(TWO_DAYS)["pending_ticks"])

    def test_tiny_cap_changes_and_calendar_cycles_never_refund_daily_debit(self):
        self.money.configure("total", "20", mode="observed")
        self.authorize("10", now=TWO_DAYS)
        for cap in ("19", "20.01", "20", "20.01", "20"):
            self.money.configure("total", cap, mode="observed")
            self.assertLessEqual(self.cap(TWO_DAYS)["daily_available_ticks"], ticks("0.005"))
            with self.assertRaisesRegex(ValueError, "daily"):
                self.authorize("1", "extra", TWO_DAYS)
        self.money.ledger.budget_calendar(workdays=list(range(5)), now=TWO_DAYS)
        self.authorize("5", "weekday", TWO_DAYS)
        self.money.ledger.budget_calendar(workdays=list(range(7)), now=TWO_DAYS)
        self.assertEqual(0, self.cap(TWO_DAYS)["daily_available_ticks"])
        self.money.ledger.budget_calendar(workdays=list(range(5)), now=TWO_DAYS)
        self.assertEqual(ticks("5"), self.cap(TWO_DAYS)["daily_available_ticks"])

    def test_pre_anchor_receipts_count_against_today(self):
        self.money.configure("total", "20", mode="observed")
        self.money.record_expense("api:xai", "6", "USD", "receipt:before", now=TWO_DAYS)
        self.assertEqual(ticks("4"), self.cap(TWO_DAYS)["daily_available_ticks"])

    def test_lowered_cap_cannot_erase_existing_debit(self):
        self.authorize("6")
        self.money.configure("total", "5", mode="observed")
        self.assertEqual(ticks("6"), self.cap()["daily_debit_ticks"])
        self.assertEqual(0, self.cap()["daily_available_ticks"])
        self.assertEqual(0, self.cap()["available_ticks"])
        with self.assertRaisesRegex(ValueError, "monthly"):
            self.authorize("0.01", "lowered")
        self.money.settle("request", ticks("6"), "receipt:already-spent")
        self.assertEqual(ticks("6"), self.cap()["charged_ticks"])
        self.assertEqual(0, self.cap()["daily_available_ticks"])

    def test_topup_retry_does_not_redistribute_twice(self):
        self.money.configure("total", "20", mode="observed")
        self.authorize("6", now=TWO_DAYS)
        self.money.add("total", "20", "grant", TWO_DAYS)
        self.authorize("10", "after-grant", TWO_DAYS)
        counts = self.stored_counts()
        self.money.add("total", "20", "grant", TWO_DAYS)
        self.assertEqual(ticks("4"), self.cap(TWO_DAYS)["daily_available_ticks"])
        self.assertEqual(counts, self.stored_counts())

    def test_calendar_change_retains_spent_debit_and_cutoff_does_not_reanchor(self):
        self.money.configure("total", "20", mode="observed")
        self.authorize("6", now=TWO_DAYS)
        self.money.ledger.budget_calendar(workdays=list(range(5)), now=TWO_DAYS)
        self.assertEqual(1, self.cap(TWO_DAYS)["workdays_remaining"])
        self.authorize("10", "weekday", TWO_DAYS)
        self.money.ledger.budget_calendar(reset_cutoff="01:00", now=TWO_DAYS)
        self.assertEqual(ticks("4"), self.cap(TWO_DAYS)["daily_available_ticks"])
        self.assertEqual(ticks("16"), self.cap(TWO_DAYS)["daily_debit_ticks"])

    def test_offdays_deny_even_with_monthly_topup(self):
        self.money.ledger.budget_calendar(workdays=list(range(5)), now=MIDMONTH)
        weekend = stamp("2026-01-17T12:00:00")
        self.money.add("total", "100", "weekend-grant", weekend)
        self.assertFalse(self.cap(weekend)["scheduled_workday"])
        self.assertEqual(0, self.cap(weekend)["daily_available_ticks"])
        with self.assertRaisesRegex(ValueError, "daily"):
            self.authorize("0.01", now=weekend)

    def test_reservation_settlement_releases_only_unused_daily_reservation(self):
        self.authorize("6")
        self.money.settle("request", ticks("2"), "receipt:actual")
        self.assertEqual(ticks("2"), self.cap()["daily_debit_ticks"])
        self.assertEqual(ticks("8"), self.cap()["daily_available_ticks"])
        self.money.settle("request", ticks("2"), "receipt:actual")
        self.authorize("8", "remaining")
        self.assertEqual(0, self.cap()["daily_available_ticks"])

    def test_prior_month_pending_blocks_capacity_without_enlarging_frozen_day(self):
        self.money.configure("total", "280", mode="observed")
        self.authorize("28", now=stamp("2026-01-31T12:00:00"))
        february = stamp("2026-02-01T12:00:00")
        self.assertEqual(ticks("9"), self.cap(february)["daily_available_ticks"])
        self.authorize("1", "february", february)
        self.money.settle("request", ticks("28"), "receipt:january")
        self.assertEqual(ticks("8"), self.cap(february)["daily_available_ticks"])
        self.assertEqual(ticks("279"), self.cap(february)["available_ticks"])
        self.assertFalse(self.authorize("28", now=february)["dispatch"])

    def test_scoped_and_total_daily_caps_both_apply(self):
        self.money.configure("api:xai", "85", mode="observed")
        with self.assertRaisesRegex(ValueError, "daily"):
            self.authorize("6")
        self.authorize("5")
        with self.assertRaisesRegex(ValueError, "daily"):
            self.authorize("1", "scope-exhausted")
        self.authorize("5", "other-provider", scope="api:openai")
        with self.assertRaisesRegex(ValueError, "daily"):
            self.authorize("1", "total-exhausted", scope="api:openai")

    def test_concurrent_first_reservations_share_one_daily_anchor(self):
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        jobs = [context.Process(target=reserve_contender, args=(self.path, f"job{i}", queue)) for i in range(2)]
        for job in jobs:
            job.start()
        results = [queue.get(timeout=30) for _ in jobs]
        for job in jobs:
            job.join(30)
            self.assertEqual(0, job.exitcode)
        queue.close()
        queue.join_thread()
        self.assertEqual([False, True], sorted(results))
        self.assertEqual(ticks("3"), self.cap()["daily_available_ticks"])
        self.assertEqual(1, self.stored_counts()[0])

    def test_calendar_month_boundaries_leap_year_and_dst_use_local_dates(self):
        money = SpendLedger(ledger=Ledger(self.path.parent / "warsaw.sqlite3", timezone="Europe/Warsaw"))
        complete_setup(money.ledger)
        money.configure("total", "30", mode="observed")
        money.ledger.budget_calendar(workdays=list(range(5)), now=MIDMONTH)
        cases = [("2026-03-27T12:00:00", 3, True),
                 ("2026-03-29T12:00:00", 2, False),
                 ("2026-03-30T12:00:00", 2, True),
                 ("2026-10-25T12:00:00", 5, False),
                 ("2028-02-28T12:00:00", 2, True),
                 ("2028-02-29T12:00:00", 1, True)]
        for value, days, scheduled in cases:
            with self.subTest(value=value):
                cap = money.status(stamp(value))["caps"][0]
                self.assertEqual(days, cap["workdays_remaining"])
                self.assertEqual(scheduled, cap["scheduled_workday"])
        money.ledger.budget_calendar(workdays=list(range(7)), now=MIDMONTH)
        edge = stamp("2026-01-31T23:00:00")
        money.authorize("api:xai", "1", "USD", DIGEST, "month-edge", edge)
        self.assertEqual("2026-02", money.request("month-edge")["month"])
        self.assertEqual("2026-02-01", money.status(edge)["caps"][0]["day"])

    def test_integer_rounding_does_not_overallocate_and_remainder_reaches_last_day(self):
        self.money.configure("total", "0.0000000003", mode="observed")
        self.assertEqual(1, self.cap(TWO_DAYS)["daily_available_ticks"])
        self.authorize("0.0000000001", now=TWO_DAYS)
        last = stamp("2026-01-31T12:00:00")
        self.assertEqual(2, self.cap(last)["daily_available_ticks"])
        self.authorize("0.0000000002", "last-day", last)
        self.assertEqual(0, self.cap(last)["available_ticks"])

    def test_missing_setup_or_unapproved_service_cannot_reserve(self):
        money = SpendLedger(self.path.parent / "unconfigured.sqlite3")
        money.configure("total", "170", mode="observed")
        with self.assertRaises(ValueError):
            money.authorize("api:xai", "1", "USD", DIGEST, "missing", MIDMONTH)
        self.assertEqual([], money.status(MIDMONTH)["unfinished"])
        with self.assertRaises(ValueError):
            self.authorize("1", scope="api:unapproved")
        self.assertEqual(0, self.stored_counts()[0])

    def test_setup_alone_does_not_supply_a_monetary_budget(self):
        money = SpendLedger(self.path.parent / "no-budget.sqlite3")
        complete_setup(money.ledger)
        with self.assertRaisesRegex(ValueError, "configure a total"):
            money.authorize("api:xai", "1", "USD", DIGEST, "no-cap", MIDMONTH)
        self.assertEqual([], money.status(MIDMONTH)["unfinished"])


if __name__ == "__main__":
    unittest.main()
