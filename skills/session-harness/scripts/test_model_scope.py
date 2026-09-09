"""Model budgets stay distinct while common accounting remains authoritative."""
import json
import sqlite3
import credits
import tempfile
import unittest
from pathlib import Path

import model_scope as ms
from quota import Ledger

FABLE = "claude-fable-1"
OPUS = "claude-opus-1"
SONNET = "claude-sonnet-1"
FABLE_SCOPE = ms.native_scope(dict(id=FABLE, display_name="Claude Fable"))


def snap(ts=1000, daily_used=0, weekly_used=0, reset=100000, scope=None):
    daily = dict(pool="daily", used_percent=daily_used, resets_at=reset)
    if scope is not None:
        daily["model_scope"] = scope
    return dict(service="claude", observed_at=ts, complete=True, source=ms.OBSERVATION_SOURCE,
                pools=[dict(pool="weekly", used_percent=weekly_used, resets_at=100000), daily],
                credit_resources=credits.claude_resources({"extra_usage": {"is_enabled": False}}))


class ModelScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ledger.sqlite3"
        self.ledger = Ledger(self.path, timezone="UTC", reserve=10)
        self.ledger.complete_setup(services=["claude"], api_services=[], source="test")
        self.ledger.set_mode("observed")
        self.ledger.budget_defaults(strategy="fixed", now=0)

    def test_tier_and_date_validation(self):
        self.assertEqual(ms.tier("claude-fable-1"), "fable")
        self.assertEqual(ms.tier("claude-opus-3-5"), "opus")
        self.assertEqual(ms.tier("claude-haiku-1[1m]"), "haiku")
        self.assertEqual(ms.tier("claude-sonnet-1-20260228"), "sonnet")
        self.assertEqual(ms.tier("claude-fable-2-20240229"), "fable")
        for bad in ("claude-fable-1-20260229", "claude-fable-1-20261301", "claude-fable-0",
                    "claude-fable-1234", "claude-unknown-1", "x" * 129, None):
            self.assertIsNone(ms.tier(bad))

    def test_scope_and_model_validation(self):
        self.assertEqual(ms.native_scope(dict(id=FABLE, display_name="Claude Fable")), FABLE_SCOPE)
        self.assertIsNotNone(ms.native_scope(dict(id=None, display_name="Fable")))
        self.assertIsNone(ms.native_scope(dict(id=OPUS, display_name="Claude Fable")))
        self.assertIsNone(ms.native_scope(dict(id=FABLE, display_name="Unknown")))
        self.assertIsNone(ms.native_scope("bad"))
        self.assertEqual(ms.validate_scope(FABLE_SCOPE, "claude", ms.OBSERVATION_SOURCE), FABLE_SCOPE)
        for args in ((FABLE_SCOPE, "other", ms.OBSERVATION_SOURCE), (FABLE_SCOPE, "claude", "bad")):
            with self.assertRaises(ValueError):
                ms.validate_scope(*args)
        bad_scope = dict(FABLE_SCOPE, tiers=["fable", "fable"])
        with self.assertRaises(ValueError):
            ms.validate_scope(bad_scope, "claude", ms.OBSERVATION_SOURCE)
        self.assertIsNone(ms.validate_models(None, "claude"))
        self.assertEqual(ms.validate_models([FABLE, OPUS], "claude"), [FABLE, OPUS])
        for bad_m in ([], [FABLE, FABLE], ["bad-model"]):
            with self.assertRaises(ValueError):
                ms.validate_models(bad_m, "claude")

    def test_applicable_and_scope_only_denial_logic(self):
        self.assertTrue(ms.applicable(None, [FABLE]))
        self.assertTrue(ms.applicable(FABLE_SCOPE, None))
        self.assertTrue(ms.applicable(FABLE_SCOPE, [FABLE]))
        self.assertFalse(ms.applicable(FABLE_SCOPE, [OPUS]))
        pool_fable = dict(pool="daily", model_scope=FABLE_SCOPE, applicable=True, reasons=["daily_limit"])
        res = dict(allowed=False, model_admission_version=1, pools=[pool_fable], reasons=["daily:daily_limit"])
        self.assertTrue(ms.scope_only_denial(res))
        self.assertFalse(ms.scope_only_denial(dict(res, allowed=True)))
        self.assertFalse(ms.scope_only_denial(dict(res, reasons=["weekly:weekly_limit"])))

    def test_fable_daily_limit_scope_denial_allows_opus_sonnet(self):
        self.ledger.record(snap(1000, daily_used=0, weekly_used=0, scope=FABLE_SCOPE), now=1000, initialize=True)
        self.ledger.record(snap(2000, daily_used=20, weekly_used=0, scope=FABLE_SCOPE), now=2000)
        chk_fable = self.ledger.check("claude", models=[FABLE], now=2000)
        self.assertFalse(chk_fable["allowed"])
        self.assertTrue(ms.scope_only_denial(chk_fable))
        self.assertTrue(self.ledger.check("claude", models=[OPUS], now=2000)["allowed"])
        self.assertTrue(self.ledger.check("claude", models=[SONNET], now=2000)["allowed"])

    def test_unknown_and_none_models_still_denied(self):
        self.ledger.record(snap(1000, daily_used=0, weekly_used=0, scope=FABLE_SCOPE), now=1000, initialize=True)
        self.ledger.record(snap(2000, daily_used=20, weekly_used=0, scope=FABLE_SCOPE), now=2000)
        self.assertFalse(self.ledger.check("claude", models=None, now=2000)["allowed"])
        try:
            chk_unk = self.ledger.check("claude", models=["claude-unknown-1"], now=2000)
            self.assertFalse(chk_unk["allowed"])
        except ValueError:
            pass

    def test_common20_denies_all(self):
        self.ledger.record(snap(1000, daily_used=0, weekly_used=0, scope=FABLE_SCOPE), now=1000, initialize=True)
        self.ledger.record(snap(2000, daily_used=0, weekly_used=20, scope=FABLE_SCOPE), now=2000)
        for m in ([FABLE], [OPUS], [SONNET], None):
            chk = self.ledger.check("claude", models=m, now=2000)
            self.assertFalse(chk["allowed"])
            self.assertFalse(ms.scope_only_denial(chk))

    def test_fresh_excluded_scope_with_stale_reset_still_denies(self):
        self.ledger.record(snap(1000, daily_used=0, weekly_used=0, scope=FABLE_SCOPE), now=1000, initialize=True)
        self.ledger.record(snap(2000, daily_used=0, weekly_used=0, reset=1000, scope=FABLE_SCOPE), now=2000)
        chk = self.ledger.check("claude", models=[OPUS], now=2000)
        self.assertFalse(chk["allowed"])

    def test_scope_upgrade_keeps_pool_and_accounting_history(self):
        self.ledger.record(snap(1000, daily_used=0), now=1000, initialize=True)
        self.ledger.record(snap(1001, daily_used=20), now=1001)
        before = self.ledger.check('claude', now=1001)
        self.ledger.record(snap(1002, daily_used=20, scope=FABLE_SCOPE), now=1002)
        after = self.ledger.check('claude', now=1002, models=[OPUS])
        self.assertTrue(after['allowed'])
        self.assertEqual([(p['pool'], p['daily_consumed']) for p in before['pools']],
                         [(p['pool'], p['daily_consumed']) for p in after['pools']])
        self.assertEqual(before['reset_history'], after['reset_history'])
        self.assertEqual(before['grants'], after['grants'])
        self.ledger.set_mode('strict')
        self.assertFalse(self.ledger.check('claude', now=1002, models=[OPUS])['allowed'])

    def test_unknown_scope_and_paid_controls_never_create_headroom(self):
        self.ledger.record(snap(1000, daily_used=0), now=1000, initialize=True)
        self.ledger.record(snap(1001, daily_used=20), now=1001)
        self.assertFalse(self.ledger.check('claude', now=1001, models=[OPUS])['allowed'])
        data = snap(1002, scope=FABLE_SCOPE)
        data['credit_resources'] = credits.claude_resources({'extra_usage': {'is_enabled': True}})
        self.ledger.record(data, now=1002)
        result = self.ledger.check('claude', now=1002, models=[OPUS])
        self.assertFalse(result['allowed'])
        self.assertFalse(ms.scope_only_denial(result))


if __name__ == "__main__":
    unittest.main()
