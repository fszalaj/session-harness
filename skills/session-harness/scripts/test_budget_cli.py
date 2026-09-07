"""Budget commands retain accounting and admission boundaries."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import budget_cli
import harness
from quota import Ledger


class BudgetCLITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = str(Path(temporary.name) / "ledger.db")
        self.ledger = Ledger(self.path)
        self.at = time.time()
        self.ledger.record(self.snapshot(self.at), initialize=True)

    def snapshot(self, at):
        return {"service": "codex", "observed_at": at, "source": "fixture", "complete": True,
                "pools": [{"pool": "weekly", "used_percent": 40, "resets_at": at + 604800}]}

    def invoke(self, *arguments, json_output=True):
        output = io.StringIO()
        argv = [*arguments, "--db", self.path] + (["--json"] if json_output else [])
        with contextlib.redirect_stdout(output):
            code = budget_cli.main(argv)
        return code, json.loads(output.getvalue()) if json_output else output.getvalue()

    def fresh(self, service, *, ledger):
        self.at = time.time()
        return ledger.record(self.snapshot(self.at))

    def test_config_preserves_mode_and_accounting_and_warns_strict(self):
        code, result = self.invoke("set", "codex", "--strategy", "adaptive", "--reserve", "0")
        self.assertEqual(code, 0)
        self.assertIn("Strict", result["warning"])
        self.assertFalse(result["services"][0]["allowed"])
        self.assertEqual(result["services"][0]["pools"][0]["remaining_percent"], 60)

    def test_add_retries_do_not_grant_twice_and_conflicts_fail(self):
        with patch("usage.refresh", side_effect=self.fresh):
            code, first = self.invoke("add", "codex", "5", "--id", "same-request")
            self.assertEqual(code, 0)
            code, second = self.invoke("add", "codex", "5", "--id", "same-request")
            self.assertEqual(code, 0)
            self.assertEqual(first["services"][0]["pools"][0]["granted_percent"], 5)
            self.assertEqual(second["services"][0]["pools"][0]["granted_percent"], 5)
            self.assertEqual(self.invoke("add", "codex", "6", "--id", "same-request")[0], 2)

    def test_use_rest_prints_expiry_without_changing_strict(self):
        with patch("usage.refresh", side_effect=self.fresh):
            code, output = self.invoke("use-rest", "codex", json_output=False)
        self.assertEqual(code, 0)
        self.assertIn("Expires:", output)
        self.assertIn("Strict mode blocks inference", output)
        self.assertEqual(self.ledger.mode(), "strict")

    def test_unsupported_or_failed_refresh_does_not_claim_admission(self):
        with patch("usage.refresh", side_effect=ValueError("unavailable")):
            code, result = self.invoke("codex")
        self.assertEqual(code, 0)
        self.assertFalse(result["services"][0]["allowed"])
        self.assertIn("quota_refresh_failed", result["services"][0]["reasons"])
        with patch("usage.refresh", return_value={"refresh_status": "unsupported"}):
            self.assertEqual(self.invoke("use-rest", "codex")[0], 2)

    def test_harness_routes_budget_without_model_discovery(self):
        with patch("budget_cli.main", return_value=0) as command, patch("harness.discover_provider") as discover:
            self.assertEqual(harness.main(["budget", "codex"]), 0)
        command.assert_called_once_with(["codex"])
        discover.assert_not_called()

    def test_calendar_and_defaults_are_shared_without_model_discovery(self):
        with patch("usage.refresh", side_effect=self.fresh), patch("harness.discover_provider") as discover:
            code, result = self.invoke("calendar", "--workdays", "mon,wed,fri", "--reset-cutoff", "07:45")
            self.assertEqual(code, 0)
            self.assertEqual(result["calendar"]["calendar"], {"workdays": [0, 2, 4], "reset_cutoff": "07:45"})
            self.assertEqual(result["calendar"]["timezone"], "UTC")
            code, result = self.invoke("defaults", "--reserve", "3")
            self.assertEqual(code, 0)
            self.assertEqual(result["defaults"]["default_reserve"], 3)
            self.assertEqual(result["services"][0]["pools"][0]["reserve_percent"], 3)
            discover.assert_not_called()

    def test_calendar_failed_refresh_saves_preferences_without_claiming_admission(self):
        self.ledger.set_mode("observed")
        with patch("usage.refresh", side_effect=ValueError("unavailable")):
            code, result = self.invoke("calendar", "--workdays", "weekdays")
        self.assertEqual(code, 0)
        self.assertFalse(result["services"][0]["allowed"])
        self.assertIn("quota_refresh_failed", result["services"][0]["reasons"])
        self.assertEqual(self.ledger.budget_calendar()["calendar"]["workdays"], list(range(5)))

    def test_calendar_rejects_timezone_reinterpretation_and_invalid_cutoff(self):
        self.assertEqual(self.invoke("calendar", "--timezone", "Europe/Warsaw")[0], 2)
        self.assertEqual(self.invoke("calendar", "--reset-cutoff", "25:00")[0], 2)
        self.assertEqual(self.ledger.budget_calendar()["calendar"]["reset_cutoff"], "08:30")


if __name__ == "__main__":
    unittest.main()
