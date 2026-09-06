"""Money cap, crash liability, concurrency and exact accounting contracts."""
from datetime import datetime, timezone
import hashlib
from contextlib import redirect_stdout
from io import StringIO
import spend_cli
import multiprocessing
from pathlib import Path
import tempfile
import unittest

from quota import Ledger
from spend import SpendLedger, estimate, ticks

DIGEST = hashlib.sha256(b"fixture text").hexdigest()
JAN = datetime(2026, 1, 15, tzinfo=timezone.utc).timestamp()
FEB = datetime(2026, 2, 15, tzinfo=timezone.utc).timestamp()


def contender(path, ident, queue):
    try:
        result = SpendLedger(path).authorize("api:xai", "7", "USD", DIGEST, ident, JAN)
        queue.put(result["dispatch"])
    except ValueError:
        queue.put(False)


class MoneyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "private" / "ledger.sqlite3"
        self.money = SpendLedger(self.path)
        self.money.configure("total", "10", mode="observed")

    def authorize(self, value="2", ident="request", now=JAN):
        return self.money.authorize("api:xai", value, "USD", DIGEST, ident, now)

    def cap(self, now=JAN):
        return self.money.status(now)["caps"][0]

    def test_strict_requires_explicit_observed_and_currency_match(self):
        self.money.configure("total", "10")
        with self.assertRaisesRegex(ValueError, "strict"):
            self.authorize()
        self.money.configure("total", "10", mode="observed")
        with self.assertRaisesRegex(ValueError, "currency"):
            self.money.authorize("api:xai", "1", "EUR", DIGEST)
        with self.assertRaisesRegex(ValueError, "currency"):
            self.money.configure("extra:claude", "2", "EUR")
        self.assertEqual([], self.money.status()["unfinished"])

    def test_duplicate_never_redispatches_and_distinct_ids_allow_same_prompt(self):
        self.assertTrue(self.authorize()["dispatch"])
        self.assertFalse(self.authorize()["dispatch"])
        with self.assertRaisesRegex(ValueError, "different payload"):
            self.authorize("3")
        self.assertTrue(self.authorize(ident="independent")["dispatch"])
        self.assertEqual(ticks("4"), self.cap()["pending_ticks"])

    def test_crash_and_timeout_liability_survives_month_rollover(self):
        self.authorize("8")
        reopened = SpendLedger(self.path)
        self.assertEqual(ticks("8"), reopened.status(FEB)["caps"][0]["pending_ticks"])
        self.money.unresolved("request")
        with self.assertRaisesRegex(ValueError, "cap reached"):
            self.authorize("3", "later", FEB)
        self.money.settle("request", ticks("8"), "receipt:old-month", reconcile=True)
        self.assertEqual(ticks("10"), self.cap(FEB)["available_ticks"])
        self.assertEqual(ticks("8"), self.cap()["charged_ticks"])

    def test_scope_and_total_apply_together_and_extra_has_separate_scope(self):
        self.money.configure("api:xai", "3", mode="observed")
        with self.assertRaisesRegex(ValueError, "cap reached"):
            self.authorize("4")
        self.money.configure("extra:claude", "9", mode="observed")
        self.authorize("2")
        with self.assertRaisesRegex(ValueError, "cap reached"):
            self.money.authorize("extra:claude", "9", "USD", DIGEST, "extra", JAN)
        self.money.authorize("extra:claude", "8", "USD", DIGEST, "extra", JAN)

    def test_overrun_latch_survives_topup_and_only_explicit_evidence_clears(self):
        self.authorize()
        self.money.settle("request", ticks("3"), "provider:receipt")
        self.money.add("total", "20", "grant", JAN)
        with self.assertRaisesRegex(ValueError, "overrun"):
            self.authorize("1", "next")
        with self.assertRaisesRegex(ValueError, "reduce"):
            self.money.settle("request", ticks("1"), "refund", reconcile=True)
        self.money.settle("request", ticks("3"), "invoice:verified", reconcile=True)
        self.assertTrue(self.authorize("1", "next")["dispatch"])

    def test_actual_settlement_idempotent_and_estimate_can_reconcile(self):
        self.authorize()
        self.money.settle("request", ticks("1"), "rate:timestamp", kind="estimated")
        self.money.settle("request", ticks("1"), "rate:timestamp", kind="estimated")
        with self.assertRaises(ValueError):
            self.money.settle("request", ticks("2"), "new")
        self.money.settle("request", ticks("1.5"), "provider:actual", reconcile=True)
        self.assertEqual(ticks("1.5"), self.cap()["charged_ticks"])

    def test_month_boundary_uses_ledger_timezone(self):
        path = self.path.parent / "zone.sqlite3"
        money = SpendLedger(ledger=Ledger(path, timezone="Europe/Warsaw"))
        money.configure("total", "10", mode="observed")
        stamp = datetime(2026, 1, 31, 23, 0, tzinfo=timezone.utc).timestamp()
        money.authorize("api:xai", "1", "USD", DIGEST, "edge", stamp)
        self.assertEqual("2026-02", money.request("edge")["month"])

    def test_concurrent_dispatches_cannot_spend_same_capacity(self):
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        jobs = [context.Process(target=contender, args=(self.path, f"job{n}", queue)) for n in range(2)]
        for job in jobs:
            job.start()
        results = [queue.get(timeout=30) for _ in jobs]
        for job in jobs:
            job.join(30)
            self.assertEqual(0, job.exitcode)
        queue.close()
        self.assertEqual([False, True], sorted(results))

    def test_rates_expire_and_unknown_classes_do_not_become_zero(self):
        self.money.set_rates("fixture", "model", {"input_tokens": "1.25", "output_tokens": "2"}, JAN, FEB, "rates:document")
        rates = self.money.rates("fixture", "model", JAN)["rates"]
        self.assertEqual(12500, estimate({"input_tokens": 1}, rates))
        with self.assertRaises(ValueError):
            estimate({"unknown": 1}, rates)
        with self.assertRaises(ValueError):
            self.money.rates("fixture", "model", FEB)
        with self.assertRaises(ValueError):
            estimate({"input_tokens": True}, rates)

    def test_cli_accepts_exact_numeric_json_rates(self):
        source = self.path.parent / "rates.json"
        source.write_text('{"currency":"USD","rates":{"input_tokens":1.25},"observed_at":"2026-01-01T00:00:00Z","expires_at":"2026-02-01T00:00:00Z","evidence":"rates:fixture"}')
        with redirect_stdout(StringIO()):
            self.assertEqual(0, spend_cli.main(["--db", str(self.path), "rates", "fixture", "model", "--file", str(source)]))
        self.assertEqual(ticks("1.25"), self.money.rates("fixture", "model", JAN)["rates"]["input_tokens"])

    def test_extra_receipt_is_idempotent_and_excess_is_recorded(self):
        result = self.money.record_expense("extra:claude", "12", "USD", "invoice:fixture", "receipt", JAN)
        self.assertEqual(ticks("12"), result["charged_ticks"])
        self.assertTrue(result["review_required"])
        self.assertEqual("duplicate_accounting_only", self.money.record_expense("extra:claude", "12", "USD", "invoice:fixture", "receipt", JAN)["status"])
        self.assertEqual(ticks("12"), self.cap()["charged_ticks"])
        self.assertEqual([], self.money.status(JAN)["unfinished"])

    def test_decimal_rounding_and_invalid_values(self):
        self.assertEqual(10000000001, ticks("1.0000000000000000000000000000000000000001"))
        self.assertEqual(1, ticks("1e-10000000"))
        self.assertEqual(1, ticks("0.00000000001"))
        self.assertEqual(1000000001, ticks("0.10000000001"))
        for value in (True, 0.1, "NaN", "Infinity", "-1", "1e40"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ticks(value)

    def test_topup_retry_and_rollover_preserve_consumption(self):
        self.authorize("2")
        self.money.settle("request", ticks("2"), "provider:receipt")
        self.money.add("total", "3", "same", JAN)
        self.money.add("total", "3", "same", JAN)
        self.assertEqual(ticks("11"), self.cap()["available_ticks"])
        self.assertEqual(ticks("10"), self.cap(FEB)["available_ticks"])
        with self.assertRaises(ValueError):
            self.money.add("total", "4", "same", JAN)


if __name__ == "__main__":
    unittest.main()
