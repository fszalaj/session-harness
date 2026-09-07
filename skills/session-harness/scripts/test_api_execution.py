"""Paid orchestration does not confuse retries, text and billing evidence."""
from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import api_execution
import api_providers
import harness
from spend import SpendLedger, ticks


class APIExecutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.money = SpendLedger(Path(temporary.name) / "ledger.db")
        self.money.ledger.complete_setup(services=[], api_services=["xai", "openai"], source="test")
        self.money.configure("total", "500", mode="observed")
        self.env = patch.dict(os.environ, {"XAI_API_KEY": "fixture-key", "OPENAI_API_KEY": "fixture-key"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_request(self, **kwargs):
        return api_execution.execute("xai", "account-model", "Review this fixture", 50, "1", ledger=self.money, **kwargs)

    def result(self, **changes):
        return dict(output_valid=True, text="fixture", model="account-model", response_id="fixture-receipt",
                    actual_cost_ticks=ticks("0.01"), **changes)

    def test_duplicate_uses_no_network_and_ledger_does_not_store_text(self):
        with patch.object(api_providers, "execute", return_value=self.result()) as request:
            self.assertEqual("completed", self.run_request(request_id="one")["status"])
            self.assertEqual("duplicate_accounting_only", self.run_request(request_id="one")["status"])
            self.assertEqual(1, request.call_count)
        data = self.money.ledger.path.read_bytes()
        self.assertNotIn(b"Review this fixture", data)
        self.assertNotIn(b"fixture-key", data)

    def test_timeout_retains_reservation_and_sanitizes_error(self):
        with patch.object(api_providers, "execute", side_effect=TimeoutError("SECRET")):
            result = self.run_request(request_id="timedout")
        self.assertEqual("unresolved_dispatch", result["status"])
        self.assertNotIn("SECRET", str(result))
        self.assertEqual(ticks("1"), self.money.status()["caps"][0]["pending_ticks"])

    def test_missing_key_fails_before_liability(self):
        with patch.dict(os.environ, {"XAI_API_KEY": ""}), self.assertRaises(api_providers.APIError):
            self.run_request()
        self.assertEqual([], self.money.status()["unfinished"])

    def test_invalid_output_still_records_verified_charge(self):
        result = self.result()
        result["output_valid"] = False
        with patch.object(api_providers, "execute", return_value=result):
            out = self.run_request()
        self.assertEqual("output_rejected", out["status"])
        self.assertIsNone(out["text"])
        self.assertEqual(ticks("0.01"), out["accounting"]["charged_ticks"])

    def test_network_holds_no_database_write_lock(self):
        def request(*args, **kwargs):
            other = SpendLedger(self.money.ledger.path)
            other.add("total", "1", "during-network")
            return self.result()
        with patch.object(api_providers, "execute", side_effect=request):
            self.assertEqual("completed", self.run_request()["status"])

    def test_missing_usage_does_not_settle_zero(self):
        result = self.result()
        result["actual_cost_ticks"] = None
        with patch.object(api_providers, "execute", return_value=result):
            out = self.run_request()
        self.assertEqual("UNRESOLVED", out["accounting"]["status"])
        self.assertEqual(ticks("1"), self.money.status()["caps"][0]["pending_ticks"])

    def test_stale_pricing_blocks_estimated_route_before_dispatch(self):
        with self.assertRaisesRegex(ValueError, "rates"):
            api_execution.execute("openai", "account-model", "text", 50, "1", ledger=self.money)
        self.assertEqual([], self.money.status()["unfinished"])
        at = time.time()
        self.money.set_rates("openai", "account-model", {"input_tokens": "1", "output_tokens": "2"}, at-1, at+100, "price:fixture")
        response = dict(output_valid=True, text="fixture", model="account-model", usage_complete=True,
                        actual_cost_ticks=None, usage={"input_tokens": 100, "output_tokens": 10})
        with patch.object(api_providers, "execute", return_value=response):
            result = api_execution.execute("openai", "account-model", "text", 50, "1", ledger=self.money)
        self.assertEqual("estimated", result["accounting"]["kind"])
        self.assertEqual(ticks("0.00012"), result["accounting"]["charged_ticks"])

    def test_model_catalog_command_reports_success(self):
        with patch.object(api_providers, "models", return_value={"status": "catalog_metadata", "models": []}), redirect_stdout(StringIO()):
            self.assertEqual(0, api_execution.main(["models", "xai"]))

    def test_leaf_guard_precedes_all_routing_storage_and_network(self):
        with patch.dict(os.environ, {"SESSION_HARNESS_LEAF": "1"}), redirect_stdout(StringIO()), \
                patch("harness.discover_provider") as native, patch.object(api_providers, "preflight") as api:
            for command in (["budget"], ["usage"], ["spend"], ["api"], ["inventory"], ["discover"], ["--help"]):
                self.assertEqual(2, harness.main(command))
            self.assertEqual("recursion_blocked", self.run_request()["status"])
            native.assert_not_called()
            api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
