"""Credit reporting never silently authorizes native paid execution."""
import contextlib
import copy
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import credits
import native_quota
from quota import Ledger
from test_native_quota import claude_data, stream, DEBUG, IDS, NOW
import usage


def money(amount, currency="USD", exponent=2):
    return {"amount_minor": amount, "currency": currency, "exponent": exponent}


class CreditMetadataTests(unittest.TestCase):
    def setUp(self):
        absent = patch.object(credits, "codex_owner_policy", return_value=None)
        absent.start()
        self.addCleanup(absent.stop)

    def test_disabled_claude_can_report_subscription_only_without_purchase_inference(self):
        rows = credits.claude_resources({"extra_usage": {"is_enabled": False}})
        self.assertEqual([], credits.native_reasons("claude", rows))
        self.assertIsNone(rows[0]["can_purchase"])
        self.assertIsNone(rows[0]["auto_reload"])
        self.assertFalse(rows[0]["paid_execution_supported"])

    def test_present_claude_spend_requires_explicit_disabled_purchase(self):
        for purchase in ({}, {"can_purchase_credits": None}, {"can_purchase_credits": True}):
            with self.subTest(purchase=purchase):
                rows = credits.claude_resources({"extra_usage": {"is_enabled": False},
                                                "spend": {"enabled": False, **purchase}})
                for mode in ("strict", "observed"):
                    result = credits.gate({"allowed": True, "mode": mode, "reasons": [],
                                           "credit_resources": rows}, "claude")
                    self.assertFalse(result["allowed"])
                self.assertIsNone(rows[0]["used"])
        rows = credits.claude_resources({"extra_usage": {"is_enabled": False},
                    "spend": {"enabled": False, "can_purchase_credits": False}})
        self.assertEqual([], credits.native_reasons("claude", rows))

    def test_decimal_credit_amounts_round_trip_as_strings(self):
        rows = credits.claude_resources({"spend": {"enabled": False, "can_purchase_credits": False,
                   "used": money(Decimal("1234567890123.123456789"))}})
        stored = json.loads(json.dumps(rows))
        self.assertEqual("1234567890123.123456789", stored[0]["used"])
        self.assertEqual(rows, credits.validate_resources(stored, "claude"))

    def test_enabled_claude_preserves_currency_and_scale_without_dividing(self):
        rows = credits.claude_resources({"extra_usage": {"is_enabled": True}, "spend": {
            "enabled": True, "used": money(Decimal("14157.125"), "BRL", 2),
            "limit": None, "balance": money(20000, "BRL", 2),
            "can_purchase_credits": False, "auto_reload": {"enabled": False}}})
        row = rows[0]
        self.assertEqual(("14157.125", "BRL", 2), (row["used"], row["currency"], row["exponent"]))
        self.assertEqual("20000", row["balance"])
        self.assertIsNone(row["limit"])
        self.assertEqual("currency_minor", row["unit"])
        self.assertEqual(["native_paid_execution_unsupported"], credits.native_reasons("claude", rows))

    def test_legacy_claude_missing_scale_retains_native_units(self):
        row = credits.claude_resources({"extra_usage": {"is_enabled": True, "used_credits": 123.5,
                                    "monthly_limit": 5000, "currency": "USD"}})[0]
        self.assertEqual("provider_credits", row["unit"])
        self.assertEqual("123.5", row["used"])
        self.assertEqual("5000", row["limit"])
        self.assertIsNone(row["exponent"])

    def test_legacy_explicit_scale_is_preserved(self):
        row = credits.claude_resources({"extra_usage": {"is_enabled": True, "used_credits": 1500,
                                       "currency": "JPY", "decimal_places": 0}})[0]
        self.assertEqual("currency_minor", row["unit"])
        self.assertEqual(("1500", "JPY", 0), (row["used"], row["currency"], row["exponent"]))

    def test_purchase_reload_or_conflicting_enablement_deny_disabled_claude(self):
        for extra, spend in ((False, {"enabled": True}),
                             (False, {"enabled": False, "auto_reload": True}),
                             (False, {"enabled": False, "can_purchase_credits": True}),
                             (None, {"enabled": None})):
            with self.subTest(spend=spend):
                rows = credits.claude_resources({"extra_usage": {"is_enabled": extra}, "spend": spend})
                self.assertTrue(credits.native_reasons("claude", rows))

    def test_missing_claude_or_malformed_money_is_sanitized_and_denied(self):
        for data in ({}, {"extra_usage": "secret"}, {"extra_usage": {"is_enabled": "secret"}},
                     {"spend": {"enabled": False, "used": money("secret")}},
                     {"spend": {"enabled": False, "used": money(1), "balance": money(1, "EUR")}},
                     {"spend": {"enabled": False, "used": money(1, exponent=True)}}):
            with self.subTest(data=data):
                rows = credits.claude_resources(data)
                self.assertTrue(credits.native_reasons("claude", rows))
                self.assertNotIn("secret", json.dumps(rows))

    def test_nonfinite_negative_boolean_and_oversized_money_is_rejected(self):
        for value in (True, -1, float("inf"), float("nan"), "NaN", "-2", "1e40", "9" * 81, Decimal("0.0000000000000000001")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                credits.decimal_amount(value)

    def test_codex_preserves_credit_units_without_currency_or_eligibility(self):
        rows = credits.codex_resources({"account-secret": {"credits": {
            "hasCredits": True, "unlimited": False, "balance": "12.345", "apiKey": "secret"}}})
        row = rows[0]
        self.assertEqual("12.345", row["balance"])
        self.assertEqual("provider_credits", row["unit"])
        self.assertIsNone(row["currency"])
        self.assertIsNone(row["enabled"])
        self.assertNotIn("secret", json.dumps(rows))
        self.assertTrue(credits.native_reasons("codex", rows))

    def test_codex_zero_balance_does_not_prove_purchase_is_disabled(self):
        rows = credits.codex_resources({"main": {"credits": {"hasCredits": False, "unlimited": False, "balance": "0"}}})
        self.assertTrue(credits.native_reasons("codex", rows))
        self.assertTrue(credits.native_reasons("codex", credits.codex_resources({"main": {}})))


    def test_copilot_overage_and_controls_remain_server_defined(self):
        rows = credits.copilot_resources([{"pool": "premium", "overage": 0.125,
                  "overageAllowedWithExhaustedQuota": True, "usageAllowedWithExhaustedQuota": True,
                  "tokenBasedBilling": True, "hasQuota": True, "email": "secret"}])
        row = rows[0]
        self.assertEqual("0.125", row["used"])
        self.assertEqual("server_defined", row["unit"])
        self.assertIsNone(row["currency"])
        self.assertTrue(row["native_controls"]["tokenBasedBilling"])
        self.assertNotIn("secret", json.dumps(rows))
        self.assertTrue(credits.native_reasons("copilot", rows))

    def test_copilot_unknown_overage_or_malformed_flags_do_not_admit(self):
        for row in ({"pool": "p"}, {"pool": "p", "overageAllowedWithExhaustedQuota": "false"},
                    {"pool": "p", "overageAllowedWithExhaustedQuota": False, "tokenBasedBilling": "unknown"}):
            self.assertTrue(credits.native_reasons("copilot", credits.copilot_resources([row])))

    def test_antigravity_missing_eligibility_is_explicit(self):
        rows = credits.missing("antigravity")
        self.assertEqual("missing", rows[0]["metadata_status"])
        self.assertEqual(["credit_metadata_unverified"], credits.native_reasons("antigravity", rows))

    def test_persisted_contract_rejects_unknown_fields_and_forged_support(self):
        rows = credits.claude_resources({"extra_usage": {"is_enabled": False}})
        for key, value in (("secret", "secret"), ("paid_execution_supported", True),
                           ("source", "antigravity.native_usage"), ("enabled", "false"),
                           ("used", "NaN"), ("native_controls", {"raw": "secret"})):
            changed = copy.deepcopy(rows)
            changed[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                credits.validate_resources(changed, "claude")
        with self.assertRaises(ValueError):
            credits.validate_resources(rows + rows, "claude")


@unittest.skipIf(os.name == "nt", "Owner confirmation currently uses a POSIX authority")
class CodexOwnerPolicyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "policy/codex.json"
        self.auth = self.root / "auth.json"
        self.write_auth("test-account")
        for item in (patch.object(credits, "credit_policy_path", return_value=self.path),
                     patch.dict(os.environ, {"CODEX_HOME": str(self.root)})):
            item.start()
            self.addCleanup(item.stop)
        self.rows = credits.codex_resources({"account": {"credits": {
            "hasCredits": False, "unlimited": False, "balance": "0"}}, "model": {}})

    def write_auth(self, account):
        self.auth.write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {"account_id": account}}))
        self.auth.chmod(0o600)

    def confirm(self):
        return credits.configure_codex_policy(disabled=True)

    def test_confirmation_allows_zero_credits_without_changing_native_metadata(self):
        before = copy.deepcopy(self.rows)
        self.assertTrue(credits.native_reasons("codex", self.rows))
        result = self.confirm()
        self.assertTrue(result["account_matches"])
        self.assertEqual([], credits.native_reasons("codex", self.rows))
        self.assertEqual(before, self.rows)
        self.assertNotIn("test-account", self.path.read_text())
        self.assertIsNone(self.rows[0]["auto_reload"])
        self.rows[0]["balance"] = "0.00"
        self.assertEqual([], credits.native_reasons("codex", self.rows))
        if os.name != "nt":
            self.assertEqual(0o600, self.path.stat().st_mode & 0o777)

    def test_switching_account_or_api_auth_invalidates_confirmation(self):
        self.confirm()
        self.write_auth("other-account")
        self.assertTrue(credits.native_reasons("codex", self.rows))
        self.auth.write_text(json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": "test-only"}))
        self.assertIsNone(credits.codex_owner_policy())
        with self.assertRaises(ValueError):
            self.confirm()

    def test_revocation_restores_gate_without_other_state_writes(self):
        self.confirm()
        result = credits.configure_codex_policy(revoke=True)
        self.assertFalse(result["account_matches"])
        self.assertFalse(self.path.exists())
        self.assertTrue(credits.native_reasons("codex", self.rows))

    def test_positive_unknown_conflicting_and_malformed_credits_still_block(self):
        self.confirm()
        for change in ({"balance": "1"}, {"has_credits": True}, {"unlimited": True},
                       {"balance": None}, {"has_credits": None}, {"auto_reload": True},
                       {"can_purchase": True}, {"enabled": True}, {"metadata_status": "invalid"}):
            with self.subTest(change=change):
                rows = copy.deepcopy(self.rows)
                rows[0].update(change)
                self.assertTrue(credits.native_reasons("codex", rows))
        self.assertTrue(credits.native_reasons("codex", self.rows[1:]))
        rows = copy.deepcopy(self.rows)
        rows[1]["has_credits"] = True
        self.assertTrue(credits.native_reasons("codex", rows))

    def test_policy_cannot_clear_quota_strict_or_setup_denials(self):
        self.confirm()
        for reason in ("daily_budget_exhausted", "exact_request_bound_unavailable", "environment_setup_required", "stale_pool"):
            result = credits.gate({"allowed": False, "allowed_by_observed_threshold": False,
                                   "reasons": [reason], "credit_resources": self.rows}, "codex")
            self.assertFalse(result["allowed"])
            self.assertFalse(result["allowed_by_observed_threshold"])
            self.assertEqual([reason], result["reasons"])
            self.assertEqual("owner_confirmation", result["credit_policy"]["source"])

    def test_corrupt_future_symlink_and_public_policy_are_denied(self):
        self.confirm()
        value = json.loads(self.path.read_text())
        for change in ({"confirmed_at": float("nan")}, {"confirmed_at": credits.time.time() + 3600},
                       {"auto_top_up": True}, {"version": True}, {"source": "backend"}, {"extra": 1}):
            self.path.write_text(json.dumps({**value, **change}))
            self.assertIsNone(credits.codex_owner_policy())
        self.path.write_text('{"version":1,"version":1}')
        self.assertIsNone(credits.codex_owner_policy())
        self.path.write_text(json.dumps(value))
        if os.name != "nt":
            self.path.chmod(0o644)
            self.assertIsNone(credits.codex_owner_policy())
            self.path.chmod(0o600)
            target = self.path.with_suffix(".other")
            self.path.rename(target)
            self.path.symlink_to(target)
            self.assertIsNone(credits.codex_owner_policy())

    def test_cli_records_only_explicit_confirmation_and_supports_revoke(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, usage.main(["credit-policy", "codex"]))
            self.assertFalse(self.path.exists())
            self.assertEqual(0, usage.main(["credit-policy", "codex", "--auto-top-up", "disabled"]))
            self.assertTrue(self.path.exists())
            self.assertEqual(0, usage.main(["credit-policy", "codex", "--revoke-credit-policy"]))
            self.assertFalse(self.path.exists())



class CreditIntegrationTests(unittest.TestCase):
    def test_enabled_claude_metadata_no_longer_crashes_percentage_parser(self):
        data = claude_data()
        data["rate_limits"]["extra_usage"] = {"is_enabled": True, "monthly_limit": None,
                                              "used_credits": 10, "currency": "USD"}
        result = native_quota.claude_snapshot(stream(data), DEBUG, IDS, NOW)
        self.assertTrue(result["complete"])
        self.assertEqual([12, 18, 7], [row["used_percent"] for row in result["pools"]])
        self.assertTrue(credits.native_reasons("claude", result["credit_resources"]))

    def test_disabled_claude_nonzero_historical_spend_is_reported(self):
        data = claude_data()
        data["rate_limits"]["spend"] = {"enabled": False, "used": money(125), "balance": None,
                                          "auto_reload": None, "can_purchase_credits": False}
        result = native_quota.claude_snapshot(stream(data), DEBUG, IDS, NOW)
        self.assertEqual("125", result["credit_resources"][0]["used"])
        self.assertEqual([], credits.native_reasons("claude", result["credit_resources"]))

    def test_codex_snapshot_keeps_separate_credits_and_never_reset_redemptions(self):
        result = usage.codex_snapshot({"rateLimitsByLimitId": {"main": {
            "primary": {"usedPercent": 1, "windowDurationMins": 300, "resetsAt": NOW + 600},
            "credits": {"hasCredits": True, "unlimited": False, "balance": "200"}}},
            "rateLimitResetCredits": {"id": "secret-reset-credit"}}, now=NOW)
        self.assertEqual(1, len(result["pools"]))
        self.assertEqual("200", result["credit_resources"][0]["balance"])
        self.assertNotIn("secret-reset-credit", json.dumps(result))

    def test_copilot_snapshot_retains_overage_resource_for_unlimited_pool(self):
        result = usage.copilot_snapshot([{"pool": "included", "remainingPercentage": 90,
             "resetDate": "2030-01-01T00:00:00Z", "overageAllowedWithExhaustedQuota": False},
            {"pool": "unlimited", "entitlementRequests": -1, "overage": 2,
             "overageAllowedWithExhaustedQuota": True}], now=NOW, complete=True)
        self.assertEqual(1, len(result["pools"]))
        self.assertEqual(2, len(result["credit_resources"]))
        self.assertTrue(credits.native_reasons("copilot", result["credit_resources"]))

    def test_enabled_credit_guard_denies_even_when_refresh_claims_headroom(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "ledger.db")
            ledger.complete_setup(services=sorted(credits.SERVICES), api_services=[], source="test")
            for mode in ("strict", "observed"):
                ledger.set_mode(mode)
                result = {"allowed": True, "reasons": [], "credit_resources":
                          credits.claude_resources({"extra_usage": {"is_enabled": True}})}
                with patch("usage.refresh", return_value=result):
                    guarded = usage.require_admission("claude", ledger=ledger)
                self.assertFalse(guarded["allowed"])
                self.assertIn("native_paid_execution_unsupported", guarded["reasons"])

    def test_missing_credit_guard_denies_native_even_in_observed_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "ledger.db")
            ledger.complete_setup(services=sorted(credits.SERVICES), api_services=[], source="test")
            ledger.set_mode("observed")
            for service in credits.SERVICES:
                with self.subTest(service=service), patch("usage.refresh", return_value={"allowed": True, "reasons": []}):
                    self.assertFalse(usage.require_admission(service, ledger=ledger)["allowed"])

    def test_read_only_usage_output_has_only_normalized_credit_data(self):
        result = {"allowed": False, "reasons": [], "credit_resources":
                  credits.codex_resources({"main": {"credits": {"hasCredits": True,
                        "unlimited": False, "balance": "1.5", "secret": "secret-value"}}})}
        output = io.StringIO()
        with patch("usage.Ledger") as ledger, contextlib.redirect_stdout(output):
            ledger.return_value.check.return_value = result
            self.assertEqual(0, usage.main(["status", "codex"]))
        displayed = json.loads(output.getvalue())
        self.assertEqual("1.5", displayed["credit_resources"][0]["balance"])
        self.assertNotIn("secret-value", output.getvalue())

    def test_ledger_preserves_resources_and_omission_cannot_reuse_disabled_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.db"
            ledger = Ledger(path)
            ledger.complete_setup(services=["claude"], api_services=[], source="test")
            ledger.set_mode("observed")
            data = usage.snapshot("claude", [{"pool": "weekly", "used_percent": 10,
                                  "resets_at": NOW + 86400}], "fixture", now=NOW)
            data["credit_resources"] = credits.claude_resources({"extra_usage": {"is_enabled": False}})
            self.assertTrue(ledger.record(data, now=NOW, initialize=True)["allowed"])
            self.assertEqual(data["credit_resources"], Ledger(path).check("claude", now=NOW)["credit_resources"])
            del data["credit_resources"]
            data["observed_at"] = NOW + 1
            result = ledger.record(data, now=NOW + 1)
            self.assertFalse(result["allowed"])
            self.assertIn("credit_metadata_unverified", result["reasons"])

    def test_claude_malformed_credit_block_keeps_percentage_evidence_but_denies(self):
        data = claude_data()
        data["rate_limits"]["spend"] = {"enabled": False, "balance": {"secret": "secret-value"}}
        result = native_quota.claude_snapshot(stream(data), DEBUG, IDS, NOW)
        self.assertTrue(result["complete"])
        self.assertEqual(3, len(result["pools"]))
        self.assertEqual("invalid", result["credit_resources"][0]["metadata_status"])
        self.assertTrue(credits.native_reasons("claude", result["credit_resources"]))
        self.assertNotIn("secret-value", json.dumps(result))


class AntigravitySettingsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "settings.json"
        mocked = patch("credits.antigravity_settings_path", return_value=self.path)
        mocked.start()
        self.addCleanup(mocked.stop)

    def test_explicit_false_has_local_provenance_and_no_invented_balances(self):
        self.path.write_text('{"useG1Credits": false, "unrelated": "private-value"}')
        rows = credits.antigravity_resources()
        self.assertEqual([], credits.native_reasons("antigravity", rows))
        self.assertEqual("antigravity.cli_settings", rows[0]["source"])
        self.assertEqual({"useG1Credits": False}, rows[0]["native_controls"])
        self.assertIsNone(rows[0]["balance"])
        self.assertIsNone(rows[0]["can_purchase"])
        self.assertNotIn("private-value", json.dumps(rows))
        self.assertEqual(rows, credits.validate_resources(rows, "antigravity"))

    def test_absent_key_and_file_use_documented_disabled_default(self):
        for content in (None, '{}'):
            if content is not None:
                self.path.write_text(content)
            rows = credits.antigravity_resources()
            self.assertEqual("reported", rows[0]["metadata_status"])
            self.assertEqual("antigravity.cli_defaults", rows[0]["source"])
            self.assertIs(rows[0]["enabled"], False)
            self.assertIsNone(rows[0]["balance"])
            self.assertIsNone(rows[0]["can_purchase"])
            self.assertEqual([], credits.native_reasons("antigravity", rows))

    def test_sparse_persistence_preserves_disabled_admission(self):
        self.path.write_text('{"useG1Credits": false, "theme": "dark"}')
        rows = credits.antigravity_resources()
        self.path.write_text('{"theme": "dark"}')
        self.assertEqual([], credits.native_reasons("antigravity", rows))
        self.path.unlink()
        self.assertEqual([], credits.native_reasons("antigravity", rows))

    def test_symlink_and_read_errors_are_not_defaults(self):
        self.path.symlink_to(self.path.with_name("absent"))
        self.assertEqual("invalid", credits.antigravity_resources()[0]["metadata_status"])
        self.path.unlink()
        self.path.write_text('{}')
        for error in (PermissionError(), FileNotFoundError()):
            with patch("credits.os.open", side_effect=error):
                self.assertEqual("invalid", credits.antigravity_resources()[0]["metadata_status"])

    def test_symlink_swap_after_lstat_is_rejected(self):
        self.path.write_text('{}')
        original = self.path.lstat()
        self.path.unlink()
        target = self.path.with_name('other.json')
        target.write_text('{"useG1Credits":false}')
        self.path.symlink_to(target)
        with patch.object(Path, "lstat", return_value=original):
            self.assertEqual("invalid", credits.antigravity_resources()[0]["metadata_status"])

    def test_non_directory_parent_and_permission_errors_deny(self):
        self.path.write_text('file')
        with patch("credits.antigravity_settings_path", return_value=self.path / 'settings.json'):
            self.assertEqual("invalid", credits.antigravity_resources()[0]["metadata_status"])
            with patch.object(Path, "lstat", side_effect=FileNotFoundError()):
                self.assertEqual("invalid", credits.antigravity_resources()[0]["metadata_status"])
        with patch.object(Path, "lstat", side_effect=PermissionError()):
            self.assertEqual("invalid", credits.antigravity_resources()[0]["metadata_status"])

    def test_invalid_state_recovers_and_encoding_is_checked(self):
        for raw in (b'{', b'\xff'):
            self.path.write_bytes(raw)
            self.assertEqual("invalid", credits.antigravity_resources()[0]["metadata_status"])
            self.path.write_bytes(b'\xef\xbb\xbf{}')
            self.assertEqual([], credits.native_reasons("antigravity", credits.antigravity_resources()))

    def test_malformed_controls_fail_closed(self):
        for content in ('{"useG1Credits": null}', '{"useG1Credits": 0}',
                        '{"useG1Credits": "false"}', '[]', '{',
                        '{} {}', '{} trailing',
                        '{"useG1Credits":true,"useG1Credits":false}', ' ' * (256 * 1024 + 1)):
            with self.subTest(content=content[:50]):
                self.path.write_text(content)
                rows = credits.antigravity_resources()
                self.assertEqual("invalid", rows[0]["metadata_status"])
                self.assertEqual(["credit_metadata_invalid"], credits.native_reasons("antigravity", rows))

    def test_gate_rereads_settings_and_never_reuses_disabled_evidence(self):
        self.path.write_text('{"useG1Credits": false}')
        rows = credits.antigravity_resources()
        for content, reason in (('{"useG1Credits":true}', "native_paid_execution_unsupported"),
                                ('{', "credit_metadata_invalid")):
            self.path.write_text(content)
            result = credits.gate({"allowed": True, "allowed_by_observed_threshold": True,
                                   "reasons": [], "credit_resources": rows}, "antigravity")
            self.assertFalse(result["allowed"])
            self.assertFalse(result["allowed_by_observed_threshold"])
            self.assertIn(reason, result["reasons"])

    def test_disabled_setting_cannot_make_missing_quota_admissible(self):
        self.path.write_text('{"useG1Credits": false}')
        result = credits.gate({"allowed": False, "reasons": ["missing_quota"],
                               "credit_resources": credits.antigravity_resources()}, "antigravity")
        self.assertFalse(result["allowed"])
        self.assertEqual(["missing_quota"], result["reasons"])
        self.assertTrue(credits.native_reasons("antigravity", credits.missing("antigravity")))

    def test_refresh_attaches_setting_without_changing_native_quota_evidence(self):
        self.path.write_text('{"useG1Credits": false}')
        observed = usage.snapshot("antigravity", [], "antigravity.native_usage", complete=False)
        with patch("native_quota.read_snapshot", return_value=observed), patch("usage.Ledger") as factory:
            ledger = factory.return_value
            ledger.path = self.path.with_name('fixture-ledger.sqlite3')
            ledger.record.side_effect = lambda value, **kw: dict(value, allowed=False, reasons=["missing_quota"])
            result = usage.refresh("antigravity", ledger=ledger)
        self.assertFalse(result["complete"])
        self.assertEqual([], result["pools"])
        self.assertFalse(result["allowed"])
        self.assertEqual("antigravity.cli_settings", result["credit_resources"][0]["source"])


if __name__ == "__main__":
    unittest.main()
