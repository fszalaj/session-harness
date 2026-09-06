"""Deterministic native metadata regressions; no installed CLI is executed."""
import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import native_quota as native

NOW = 1800000000
RESET = "2030-01-01T15:00:00Z"
IDS = ("initialize-id", "usage-id")
DEBUG = "fetchUtilization: GET /api/oauth/usage (attempt 1)\nfetchUtilization: 200 after 1 attempt(s)"


def claude_data():
    scope = {"model": {"id": None, "display_name": "Example Model"}, "surface": None}
    return dict(session=dict(total_cost_usd=0, total_api_duration_ms=0, total_duration_ms=123,
                             total_lines_added=0, total_lines_removed=0, model_usage={}),
                rate_limits_available=True, behaviors=None, rate_limits=dict(
                    five_hour=dict(utilization=12, resets_at=RESET),
                    seven_day=dict(utilization=18, resets_at=RESET),
                    seven_day_opus=None, seven_day_sonnet=None, nullable_future=None,
                    limits=[dict(kind="session", group="session", percent=12, resets_at=RESET, scope=None, is_active=True),
                            dict(kind="weekly_all", group="weekly", percent=18, resets_at=RESET, scope=None, is_active=False),
                            dict(kind="weekly_scoped", group="weekly", percent=7, resets_at=RESET, scope=scope, is_active=False)],
                    model_scoped=[dict(display_name="Example Model", utilization=7, resets_at=RESET)],
                    extra_usage=dict(is_enabled=False)))


def stream(data, ids=IDS):
    return "\n".join(json.dumps(dict(type="control_response", response=dict(subtype="success", request_id=identity, response=body)))
                     for identity, body in zip(ids, ({}, data)))


def agy_groups():
    return [dict(name=group, buckets=[dict(id=group + "-" + window, window=window,
             remaining_fraction=0.987654321, reset_time=RESET) for window in ("weekly", "5h")])
            for group in ("gemini", "3p")]


class NativeTests(unittest.TestCase):
    def test_claude_all_inactive_scoped_pools_retained(self):
        result = native.claude_snapshot(stream(claude_data()), DEBUG, IDS, NOW)
        self.assertTrue(result["complete"])
        self.assertEqual([12, 18, 7], [row["used_percent"] for row in result["pools"]])
        self.assertNotIn("Example Model", json.dumps(result))

    def test_claude_cached_and_protocol_rejected(self):
        raw = stream(claude_data())
        for debug, stdout in (("", raw), (DEBUG.splitlines()[0], raw),
                              ("\n".join(reversed(DEBUG.splitlines())), raw),
                              (DEBUG, stream(claude_data(), ("wrong", IDS[1]))),
                              (DEBUG, raw + "\n" + raw),
                              (DEBUG, raw + '\n{"type":"assistant"}')):
            with self.subTest(debug=debug, stdout=stdout[:30]):
                with self.assertRaises(native.NativeQuotaError):
                    native.claude_snapshot(stdout, debug, IDS, NOW)

    def test_claude_missing_unknown_enabled_or_disagreeing_limits(self):
        mutations = [lambda d: d["rate_limits"]["limits"].pop(1),
                     lambda d: d["rate_limits"]["limits"].append(copy.deepcopy(d["rate_limits"]["limits"][0])),
                     lambda d: d["rate_limits"]["limits"][0].update(kind="unknown"),
                     lambda d: d["rate_limits"].update(new_pool={}),
                     lambda d: d["rate_limits"]["extra_usage"].update(is_enabled=True),
                     lambda d: d["rate_limits"]["model_scoped"].clear(),
                     lambda d: d["rate_limits"]["five_hour"].update(utilization=99),
                     lambda d: d["session"].update(total_cost_usd=1),
                     lambda d: d["session"].update(model_usage={"unexpected": {}})]
        for mutate in mutations:
            data = claude_data()
            mutate(data)
            with self.subTest(mutation=mutate):
                with self.assertRaises(native.NativeQuotaError):
                    native.claude_snapshot(stream(data), DEBUG, IDS, NOW)

    def test_claude_native_unknown_reset_and_future_pool_retained(self):
        data = claude_data()
        data["rate_limits"]["nimbus_quill"] = dict(utilization=0, resets_at=None,
            limit_dollars=None, used_dollars=None, remaining_dollars=None, locked_reason=None)
        data["rate_limits"]["future_quota"] = dict(utilization=33.125, resets_at=RESET)
        data["rate_limits"]["member_dashboard_available"] = False
        data["rate_limits"]["spend"] = dict(enabled=False, percent=0,
            used=dict(amount_minor=0, currency="USD", exponent=2), limit=None, cap=None,
            balance=None, auto_reload=None, can_purchase_credits=False, disclaimer="informational")
        result = native.claude_snapshot(stream(data), DEBUG, IDS, NOW)
        pools = {row["pool"]: row for row in result["pools"]}
        self.assertTrue(result["complete"])
        self.assertIsNone(pools["native:nimbus_quill"]["resets_at"])
        self.assertEqual(33.125, pools["native:future_quota"]["used_percent"])
        for mutation in (lambda d: d["spend"].update(enabled=True),
                         lambda d: d["spend"]["used"].update(amount_minor=1),
                         lambda d: d["spend"].update(balance={}),
                         lambda d: d["spend"].update(can_purchase_credits=True),
                         lambda d: d["nimbus_quill"].update(used_dollars=0),
                         lambda d: d["future_quota"].update(unrecognized=True),
                         lambda d: d.update(member_dashboard_available={})):
            bad = copy.deepcopy(data)
            mutation(bad["rate_limits"])
            with self.assertRaises(native.NativeQuotaError):
                native.claude_snapshot(stream(bad), DEBUG, IDS, NOW)

    def test_claude_legacy_scoped_alias_must_match_and_is_not_duplicated(self):
        data = claude_data()
        data["rate_limits"]["limits"][2]["scope"]["model"]["display_name"] = "Claude Opus"
        data["rate_limits"]["model_scoped"][0]["display_name"] = "Claude Opus"
        data["rate_limits"]["seven_day_opus"] = dict(utilization=7, resets_at=RESET)
        result = native.claude_snapshot(stream(data), DEBUG, IDS, NOW)
        self.assertEqual(3, len(result["pools"]))
        data["rate_limits"]["seven_day_opus"]["utilization"] = 8
        result = native.claude_snapshot(stream(data), DEBUG, IDS, NOW)
        self.assertEqual(4, len(result["pools"]))
        self.assertEqual(8, result["pools"][-1]["used_percent"])

    def test_agy_all_pools_full_precision_and_additional_groups(self):
        groups = agy_groups()
        group = copy.deepcopy(groups[0])
        group["name"] = "future"
        for bucket in group["buckets"]:
            bucket["id"] = "future-" + bucket["window"]
        groups.append(group)
        pools = native.antigravity_pools(groups, NOW)
        self.assertEqual(6, len(pools))
        self.assertEqual(100 * (1 - 0.987654321), pools[0]["used_percent"])

    def test_agy_unknown_missing_duplicate_pools(self):
        mutations = [lambda d: d.pop(), lambda d: d[0]["buckets"].pop(),
                     lambda d: d[0]["buckets"][0].update(window="unknown"),
                     lambda d: d[0]["buckets"][0].update(id="3p-weekly"),
                     lambda d: d[0]["buckets"][0].update(id="gemini-5h")]
        for mutate in mutations:
            groups = agy_groups()
            mutate(groups)
            with self.assertRaises(native.NativeQuotaError):
                native.antigravity_pools(groups, NOW)

    def test_invalid_percent_reset_and_duplicate_json(self):
        for field, value in (("remaining_fraction", True), ("remaining_fraction", -1),
                             ("remaining_fraction", float("nan")),
                             ("reset_time", "2030-01-01T00:00:00")):
            groups = agy_groups()
            groups[0]["buckets"][0][field] = value
            with self.assertRaises(native.NativeQuotaError):
                native.antigravity_pools(groups, NOW)
        with self.assertRaises(native.NativeQuotaError):
            native.decode('{"secret":1,"secret":2}')

    def test_all_reset_kinds_retained_without_guessing_renewal(self):
        for reset in (None, "2020-01-01T00:00:00Z"):
            data = claude_data()
            for row in data["rate_limits"]["limits"] + data["rate_limits"]["model_scoped"]:
                row["resets_at"] = reset
            for key in ("five_hour", "seven_day"):
                data["rate_limits"][key]["resets_at"] = reset
            result = native.claude_snapshot(stream(data), DEBUG, IDS, NOW)
            expected = native.timestamp(reset, NOW)
            self.assertEqual([expected] * 3, [pool["resets_at"] for pool in result["pools"]])
            groups = agy_groups()
            groups[0]["buckets"][0]["reset_time"] = reset
            self.assertEqual(expected, native.antigravity_pools(groups, NOW)[0]["resets_at"])

    def test_ambiguous_legacy_scope_preserved_without_aggregation(self):
        data = claude_data()
        rates = data["rate_limits"]
        rates["limits"][2]["scope"]["model"]["display_name"] = "Opus Standard"
        rates["model_scoped"][0]["display_name"] = "Opus Standard"
        second = copy.deepcopy(rates["limits"][2])
        second["scope"]["model"]["display_name"] = "Opus Extended"
        second["percent"] = 13
        rates["limits"].append(second)
        rates["model_scoped"].append(dict(display_name="Opus Extended", utilization=13, resets_at=RESET))
        rates["seven_day_opus"] = dict(utilization=9, resets_at=RESET)
        pools = native.claude_snapshot(stream(data), DEBUG, IDS, NOW)["pools"]
        self.assertEqual([12, 18, 7, 13, 9], [pool["used_percent"] for pool in pools])
        self.assertEqual("native:seven_day_opus", pools[-1]["pool"])

    def test_pool_identifier_matches_ledger_bound(self):
        pools = []
        native.add_pool(pools, "x" * 128, 0, None, NOW)
        with self.assertRaises(native.NativeQuotaError):
            native.add_pool(pools, "x" * 129, 0, None, NOW)

    def test_only_metadata_commands_and_sanitized_environment(self):
        def run(argv, **kwargs):
            self.assertEqual(15, kwargs["timeout"])
            self.assertNotIn("quota_service", kwargs)
            self.assertTrue(Path(kwargs["cwd"]).is_dir())
            self.assertNotIn("ANTHROPIC_API_KEY", kwargs["env"])
            self.assertNotIn("ANTHROPIC_MODEL", kwargs["env"])
            self.assertEqual("1", kwargs["env"]["SESSION_HARNESS_LEAF"])
            self.assertIn("--safe-mode", argv)
            self.assertIn("--no-session-persistence", argv)
            self.assertEqual("/dev/stderr", argv[argv.index("--debug-file") + 1])
            requests = [json.loads(line) for line in kwargs["stdin"].splitlines()]
            self.assertEqual(["initialize", "get_usage"], [r["request"]["subtype"] for r in requests])
            self.assertTrue(requests[1]["request"]["skip_behaviors"])
            self.assertTrue(all(r["type"] == "control_request" for r in requests))
            return 0, stream(claude_data(), tuple(r["request_id"] for r in requests)), DEBUG
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "secret", "ANTHROPIC_MODEL": "secret"}), \
                patch.object(native.shutil, "which", side_effect=lambda name: "/native/" + name), \
                patch.object(native.harness, "run", side_effect=run), patch.object(native.time, "time", return_value=NOW):
            for service in ("claude",):
                self.assertEqual(NOW, native.read_snapshot(service)["observed_at"])

    def test_antigravity_uses_owned_force_refresh_only(self):
        import agy_quota
        self.assertFalse(hasattr(native, "antigravity_snapshot"))
        with patch.object(native.shutil, "which", return_value="/native/agy"), \
                patch.object(agy_quota, "read_snapshot", return_value={"complete": True}) as reader, \
                patch.object(native.harness, "run", side_effect=AssertionError("No cached slash-command fallback")):
            self.assertTrue(native.read_snapshot("antigravity")["complete"])
            reader.assert_called_once_with("/native/agy")
            reader.side_effect = ValueError("secret diagnostic")
            with self.assertRaises(native.NativeQuotaError) as raised:
                native.read_snapshot("antigravity")
            self.assertNotIn("secret diagnostic", str(raised.exception))

    def test_failures_redact_raw_diagnostics(self):
        for effect in ((1, "credential-secret", "credential-secret"), (0, "credential-secret", "")):
            with patch.object(native.shutil, "which", return_value="/native/agy"), \
                    patch.object(native.harness, "run", return_value=effect):
                with self.assertRaises(native.NativeQuotaError) as raised:
                    native.read_snapshot("claude")
                self.assertNotIn("credential-secret", str(raised.exception))
                self.assertTrue(raised.exception.__suppress_context__)
        with patch.object(native.shutil, "which", return_value=None):
            with self.assertRaises(native.NativeQuotaError):
                native.read_snapshot("claude")


if __name__ == "__main__":
    unittest.main()
