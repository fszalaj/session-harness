#!/usr/bin/env python3
"""Validate quota adapters and the inference admission boundary without model calls."""
import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import harness
import credits
import usage
from quota import Ledger


class UsageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        settings = patch("credits.antigravity_settings_path", return_value=Path(temporary.name) / "settings.json")
        settings.start()
        self.addCleanup(settings.stop)
        path = Path(temporary.name) / "default.db"
        Ledger(path).complete_setup(services=["codex", "claude", "antigravity"], api_services=[], source="test")
        default = patch("quota.default_path", return_value=path)
        default.start()
        self.addCleanup(default.stop)

    def test_codex_keeps_every_window_and_omits_identity_and_reset_credits(self):
        row = {"primary": {"usedPercent": 42, "windowDurationMins": 10080, "resetsAt": 9999},
               "secondary": {"usedPercent": 8, "windowDurationMins": 300, "resetsAt": 8888}}
        data = usage.codex_snapshot({"accountId": "private", "rateLimitResetCredits": {"id": "private"},
                                    "rateLimitsByLimitId": {"main": row, "other": row}}, now=100)
        self.assertEqual(len(data["pools"]), 4)
        self.assertNotIn("private", json.dumps(data))
        self.assertEqual(data["pools"][0]["window_source"], "codex.windowDurationMins")

    def test_unsupported_refresh_cannot_admit_manually_recorded_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "quota.db")
            ledger.complete_setup(services=["codex", "claude", "antigravity", "copilot", "cursor"], api_services=[], source="test")
            ledger.set_mode("observed")
            with patch("quota.time.time", return_value=100):
                ledger.record(usage.snapshot("cursor", [{"pool": "monthly", "used_percent": 0,
                              "resets_at": 9999}], "fixture", now=100), initialize=True)
                self.assertTrue(ledger.check("cursor")["allowed"])
                result = usage.require_admission("cursor", ledger=ledger)
        self.assertFalse(result["allowed"])
        self.assertIn("unsupported_quota_refresh", result["reasons"])

    def test_codex_spend_control_blocks_before_reset(self):
        raw = {"rateLimitsByLimitId": {"main": {"spendControlReached": True}}}
        data = usage.codex_snapshot(raw, now=100)
        self.assertEqual(data["pools"][0]["used_percent"], 100)

    def test_claude_missing_window_stays_incomplete(self):
        data = usage.client_snapshot("claude", {"rate_limits": {
            "five_hour": {"used_percentage": 20, "resets_at": 9999}}, "email": "private"}, now=100)
        self.assertFalse(data["complete"])
        self.assertNotIn("private", json.dumps(data))

    def test_cached_native_reports_never_authorize_fresh_admission(self):
        raw = {"rate_limits": {"five_hour": {"used_percentage": 10, "resets_at": 9999},
                               "seven_day": None}}
        data = usage.client_snapshot("claude", raw, now=100)
        self.assertFalse(data["reported_pools_complete"])
        raw["rate_limits"]["seven_day"] = {"used_percentage": 10, "resets_at": 9999}
        data = usage.client_snapshot("claude", raw, now=200)
        self.assertTrue(data["reported_pools_complete"])
        self.assertFalse(data["complete"])
        self.assertEqual(data["freshness"], "client_receipt_only_backend_time_unverified")

    def test_copilot_completeness_must_come_from_raw_response_validation(self):
        rows = [{"pool": "included", "remainingPercentage": 80, "resetDate": "2026-10-01T00:00:00Z"}]
        self.assertFalse(usage.copilot_snapshot(rows, now=100)["complete"])
        self.assertTrue(usage.copilot_snapshot(rows, now=100, complete=True)["complete"])
        rows[0]["remainingPercentage"] = True
        with self.assertRaises(ValueError):
            usage.copilot_snapshot(rows, now=100, complete=True)

    def test_antigravity_keeps_all_pools_and_reset_instants(self):
        data = usage.client_snapshot("antigravity", {"quota": {
            "a": {"remaining_fraction": .25, "reset_time": "2026-09-07T00:00:00Z"},
            "b": {"remaining_fraction": .75, "reset_time": "2026-09-07T03:00:00+03:00"}}}, now=100)
        self.assertEqual([p["used_percent"] for p in data["pools"]], [75, 25])
        self.assertEqual(data["pools"][0]["resets_at"], data["pools"][1]["resets_at"])

    def test_invalid_fraction_and_naive_reset_are_rejected(self):
        for fraction in (True, float("nan"), 1.1):
            with self.assertRaises(ValueError):
                usage.client_snapshot("antigravity", {"quota": {"x": {
                    "remaining_fraction": fraction, "reset_time": "2026-09-07T00:00:00Z"}}})
        with self.assertRaises(ValueError):
            usage.epoch("2026-09-07T00:00:00")

    def test_copilot_uses_service_pool_and_skips_explicit_unlimited(self):
        data = usage.copilot_snapshot([
            {"pool": "included", "remainingPercentage": 10, "resetDate": "2026-10-01T00:00:00Z"},
            {"pool": "unlimited", "entitlementRequests": -1}], now=100)
        self.assertEqual(data["service"], "copilot")
        self.assertEqual(data["pools"][0]["used_percent"], 90)
        self.assertEqual(len(data["pools"]), 1)

    def test_strict_guard_never_confuses_observed_headroom_with_enforceable_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "quota.db")
            ledger.complete_setup(services=["codex", "claude", "antigravity", "copilot", "cursor"], api_services=[], source="test")
            with patch.object(usage, "refresh", return_value={"allowed": True, "reasons": []}):
                result = usage.require_admission("codex", ledger=ledger)
        self.assertFalse(result["allowed"])
        self.assertIn("exact_request_bound_unavailable", result["reasons"])

    def test_unknown_quota_blocks_before_any_review_process(self):
        capability = {"review": {"status": "available"}, "auth": {"status": "subscription"},
                      "planner": {"model": "best", "effort": "high"}, "executable": "never-run"}
        with patch.object(usage, "require_admission", return_value={"allowed": False, "reasons": ["missing_snapshot"]}), \
                patch.object(harness, "checked") as process:
            with self.assertRaises(harness.HarnessError) as failure:
                harness.review("claude", b"review", 30, capability)
        self.assertEqual(failure.exception.status, "quota_blocked")
        process.assert_not_called()

    def test_main_launch_quota_denial_never_executes_any_provider(self):
        capability = {"executable": "never-run", "auth": {"status": "subscription"},
                      "planner": {"model": "future-fixture", "effort": "high"}}
        for provider in ("codex", "claude", "antigravity"):
            with self.subTest(provider=provider), patch.dict(harness.os.environ, {}, clear=True), \
                    patch.object(harness, "discover_provider", return_value=capability), \
                    patch.object(harness.sys.stdin, "isatty", return_value=True), \
                    patch.object(harness.sys, "stdout", new_callable=io.StringIO) as output, \
                    patch.object(usage, "require_admission", return_value={"allowed": False, "reasons": ["exact_request_bound_unavailable"]}) as admission, \
                    patch.object(harness.os, "execvpe") as execute:
                self.assertEqual(harness.main(["launch", provider, "--execute"]), 2)
                self.assertEqual(json.loads(output.getvalue())["status"], "quota_blocked")
                admission.assert_called_once()
                self.assertEqual((provider,), admission.call_args.args)
                execute.assert_not_called()

    def test_main_launch_non_tty_never_reaches_quota_or_exec(self):
        capability = {"executable": "never-run", "auth": {"status": "subscription"},
                      "planner": {"model": "future-fixture", "effort": "high"}}
        for provider in ("codex", "claude", "antigravity"):
            with self.subTest(provider=provider), patch.dict(harness.os.environ, {}, clear=True), \
                    patch.object(harness, "discover_provider", return_value=capability), \
                    patch.object(harness.sys.stdin, "isatty", return_value=False), \
                    patch.object(harness.sys, "stdout", new_callable=io.StringIO) as output, \
                    patch.object(usage, "require_admission") as admission, \
                    patch.object(harness.os, "execvpe") as execute:
                self.assertEqual(harness.main(["launch", provider, "--execute"]), 2)
                self.assertEqual(json.loads(output.getvalue())["status"], "interactive_required")
                admission.assert_not_called()
                execute.assert_not_called()

    def test_main_launch_inherited_session_never_reaches_quota_or_exec(self):
        capability = {"executable": "never-run", "auth": {"status": "subscription"},
                      "planner": {"model": "future-fixture", "effort": "high"}}
        for provider in ("codex", "claude", "antigravity"):
            for marker in (harness.SESSION_MARKER, "CODEX_THREAD_ID", "CLAUDECODE", "AGY_SESSION_ID"):
                with self.subTest(provider=provider, marker=marker), \
                        patch.dict(harness.os.environ, {marker: "private-marker"}, clear=True), \
                        patch.object(harness, "discover_provider", return_value=capability), \
                        patch.object(harness.sys.stdin, "isatty", return_value=True), \
                        patch.object(harness.sys, "stdout", new_callable=io.StringIO) as output, \
                        patch.object(usage, "require_admission") as admission, \
                        patch.object(harness.os, "execvpe") as execute:
                    self.assertEqual(harness.main(["launch", provider, "--execute"]), 2)
                    self.assertEqual(json.loads(output.getvalue())["status"], "nested_manager_blocked")
                    self.assertNotIn("private-marker", output.getvalue())
                    admission.assert_not_called()
                    execute.assert_not_called()

    def test_native_readers_feed_all_pools_into_the_shared_ledger(self):
        for service in ("claude", "antigravity"):
            with self.subTest(service=service), tempfile.TemporaryDirectory() as directory:
                ledger = Ledger(Path(directory) / "quota.db")
                ledger.complete_setup(services=["codex", "claude", "antigravity", "copilot", "cursor"], api_services=[], source="test")
                ledger.set_mode("observed")
                ledger.budget_set(service, "fixed", now=100)
                def observed(at, amount):
                    result = usage.snapshot(service, [
                        {"pool": "session", "used_percent": amount, "resets_at": 9999},
                        {"pool": "weekly", "used_percent": amount, "resets_at": 99999},
                    ], "native-test", now=at)
                    if service == "claude":
                        result["credit_resources"] = credits.claude_resources({"extra_usage": {"is_enabled": False}})
                    return result
                with patch("native_quota.read_snapshot", side_effect=[observed(100, 10), observed(101, 30)]) as reader, \
                        patch("credits.antigravity_settings_path", return_value=Path(directory) / "settings.json"):
                    with patch("quota.time.time", return_value=100):
                        first = usage.refresh(service, ledger=ledger, initialize=True)
                    with patch("quota.time.time", return_value=101):
                        second = usage.refresh(service, ledger=ledger)
                self.assertTrue(first["allowed"])
                self.assertFalse(second["allowed"])
                self.assertEqual([pool["daily_consumed"] for pool in second["pools"]], [20, 20])
                self.assertEqual(reader.call_count, 2)

    def test_failed_native_refresh_never_admits_using_old_headroom(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "quota.db")
            ledger.complete_setup(services=["codex", "claude", "antigravity", "copilot", "cursor"], api_services=[], source="test")
            ledger.set_mode("observed")
            ledger.record(usage.snapshot("claude", [{"pool": "weekly", "used_percent": 5,
                           "resets_at": 9999}], "test", now=100), now=100, initialize=True)
            with patch("quota.time.time", return_value=101), \
                    patch("native_quota.read_snapshot", side_effect=ValueError("private payload")):
                result = usage.require_admission("claude", ledger=ledger)
            self.assertFalse(result["allowed"])
            self.assertEqual(result["reasons"], ["quota_refresh_failed"])
            self.assertNotIn("private", json.dumps(result))

    def test_explicit_backend_observation_retains_time_and_cannot_be_redrawn_fresh(self):
        raw = {"rate_limits": {"five_hour": {"used_percentage": 10, "resets_at": 9999},
                               "seven_day": {"used_percentage": 10, "resets_at": 9999}},
               "quota_observation": {"observed_at": 100, "provenance": "backend", "complete": True}}
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "quota.db")
            ledger.complete_setup(services=["codex", "claude", "antigravity", "copilot", "cursor"], api_services=[], source="test")
            ledger.set_mode("observed")
            data = usage.client_snapshot("claude", raw, now=100)
            result = ledger.record(data, now=100)
            self.assertFalse(result["allowed"])
            self.assertIn("credit_metadata_unverified", result["reasons"])
            redraw = usage.client_snapshot("claude", raw, now=300)
            self.assertEqual(redraw["observed_at"], 100)
            with self.assertRaises(ValueError):
                ledger.record(redraw, now=300)
            self.assertFalse(ledger.check("claude", now=300)["allowed"])

    def test_backend_metadata_requires_explicit_provenance(self):
        for metadata in ({"observed_at": 100}, {"observed_at": 100, "provenance": "receipt"},
                         {"observed_at": 101, "provenance": "backend"}):
            with self.assertRaises(ValueError):
                usage.client_snapshot("antigravity", {"quota": {"main": {
                    "remaining_fraction": .9, "reset_time": 9999}},
                    "quota_observation": metadata}, now=100)

    def test_observed_admission_and_polling_use_persisted_mode_without_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "quota.db")
            ledger.complete_setup(services=["codex", "claude", "antigravity", "copilot", "cursor"], api_services=[], source="test")
            ledger.set_mode("observed")
            data = usage.snapshot("claude", [{"pool": "weekly", "used_percent": 20,
                                              "resets_at": 9999}], "test", now=100)
            data["credit_resources"] = credits.claude_resources({"extra_usage": {"is_enabled": False}})
            ledger.record(data, now=100)
            fresh = usage.snapshot("claude", [{"pool": "weekly", "used_percent": 21,
                                               "resets_at": 9999}], "test", now=101)
            fresh["credit_resources"] = credits.claude_resources({"extra_usage": {"is_enabled": False}})
            with patch("quota.time.time", return_value=101), patch("native_quota.read_snapshot", return_value=fresh):
                self.assertTrue(usage.require_admission("claude", ledger=ledger)["allowed"])
            with patch("quota.time.time", return_value=222), patch("native_quota.read_snapshot", return_value=fresh):
                self.assertFalse(usage.require_admission("claude", ledger=ledger)["allowed"])

    def test_context_uses_actual_window_percentage_not_token_spend(self):
        for value, action in [(59, "continue"), (60, "checkpoint"), (75, "reduce_context"),
                              (85, "compact")]:
            self.assertEqual(usage.context_status({"context_window": {"used_percentage": value}})["action"], action)
        self.assertEqual(usage.context_status({"cost": {"total_tokens": 90000}})["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
