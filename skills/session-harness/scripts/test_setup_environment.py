import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from quota import Ledger
from spend import SpendLedger
import setup_environment as setup


class Terminal(io.StringIO):
    def isatty(self):
        return True


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "ledger.sqlite3"

    def run_setup(self, *arguments, answers=None):
        output = io.StringIO()
        stream = io.StringIO() if answers is None else Terminal(answers)
        result = setup.main(["--ledger", str(self.path), *arguments],
                            input_stream=stream, output_stream=output)
        return result, output.getvalue()

    def test_cli_requires_confirmation_and_explicit_mode(self):
        self.assertEqual(self.run_setup("--services", "codex", "--mode", "strict")[0], 2)
        self.assertEqual(self.run_setup("--services", "codex", "--yes")[0], 2)
        self.assertFalse(self.path.exists())

    def test_native_completion_never_configures_money(self):
        with patch.object(setup, "SpendLedger", side_effect=AssertionError("native money mutation")):
            code, _ = self.run_setup("--services", "codex,claude", "--mode", "observed", "--yes",
                                     "--timezone", "Europe/Warsaw", "--workdays", "weekdays", "--cutoff", "09:20")
        self.assertEqual(code, 0)
        ledger = Ledger(self.path)
        self.assertTrue(ledger.setup_status()["complete"])
        self.assertEqual(ledger.setup_status()["services"], ["codex", "claude"])
        self.assertEqual(ledger.setup_status()["source"], "cli")
        self.assertEqual(ledger.policy["timezone"], "Europe/Warsaw")
        self.assertEqual(ledger.mode(), "observed")
        self.assertEqual(ledger.budget_calendar()["calendar"], {"workdays": [0, 1, 2, 3, 4], "reset_cutoff": "09:20"})

    def test_api_requires_positive_budget_and_explicit_mode(self):
        for extra in ([], ["--monthly-budget", "10"], ["--monthly-budget", "0", "--money-mode", "observed"],
                      ["--monthly-budget", "NaN", "--money-mode", "observed"]):
            with self.subTest(extra=extra):
                code, _ = self.run_setup("--api-services", "openai", "--mode", "strict", "--yes", *extra)
                self.assertEqual(code, 2)
                self.assertFalse(self.path.exists())

    def test_api_strict_completion_explains_dispatch_block(self):
        code, output = self.run_setup("--api-services", "xai,openrouter", "--mode", "strict", "--yes",
                                      "--monthly-budget", "12.345", "--money-mode", "strict")
        self.assertEqual(code, 0)
        self.assertIn("strict mode currently blocks", output)
        ledger = Ledger(self.path)
        self.assertEqual(ledger.setup_status()["api_services"], ["xai", "openrouter"])
        with ledger._connect() as db:
            self.assertEqual(db.execute("SELECT cap,mode FROM money_caps WHERE scope='total'").fetchone(),
                             (123450000000, "strict"))

    def test_interactive_eof_and_rejection_make_no_new_ledger(self):
        for answers in ("", "codex\n\n\n\n\nstrict\nlocal\n4\nno\n", "codex\n\n\n\n\nstrict\n"):
            with self.subTest(answers=answers):
                self.assertEqual(self.run_setup(answers=answers)[0], 130)
                self.assertFalse(self.path.exists())

    def test_interactive_preserves_defaults_and_existing_base_money_cap(self):
        ledger = Ledger(self.path, timezone="Europe/Warsaw")
        ledger.budget_calendar(workdays=[1, 3], reset_cutoff="10:45")
        ledger.set_mode("observed")
        ledger.budget_defaults(reserve=17, strategy="fixed", daily_limit=13)
        money = SpendLedger(ledger=ledger)
        money.configure("total", "20", mode="observed")
        money.add("total", "5", grant_id="existing-addition")
        ledger.complete_setup(services=["claude"], api_services=["xai"], source="cli")
        code, _ = self.run_setup(answers="\n" * 10 + "yes\n")
        self.assertEqual(code, 0)
        self.assertEqual(ledger.mode(), "observed")
        self.assertEqual(ledger.budget_calendar()["calendar"], {"workdays": [1, 3], "reset_cutoff": "10:45"})
        self.assertEqual(ledger.setup_status()["source"], "interactive")
        self.assertEqual(ledger.budget_defaults()["default_reserve"], 17)
        with ledger._connect() as db:
            self.assertEqual(db.execute("SELECT cap FROM money_caps WHERE scope='total'").fetchone()[0], 200000000000)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM money_additions").fetchone()[0], 1)

    def test_reset_only_removes_authorization(self):
        ledger = Ledger(self.path)
        ledger.set_mode("observed")
        ledger.complete_setup(services=["claude"], api_services=[], source="cli")
        code, _ = self.run_setup("--reset", "--yes")
        self.assertEqual(code, 0)
        self.assertFalse(ledger.setup_status()["complete"])
        self.assertEqual(ledger.mode(), "observed")

    def test_interactive_capacity_is_visible_and_existing_choice_is_preserved(self):
        code, output = self.run_setup(answers='claude\nnone\n\n\n\nobserved\nlocal\n8\nyes\n')
        self.assertEqual(0, code)
        self.assertIn('Concurrent sessions per service', output)
        self.assertEqual(8, setup.coordination.settings(Ledger(self.path))['max_sessions'])
        self.assertEqual(0, self.run_setup('--services', 'claude', '--mode', 'observed', '--yes')[0])
        self.assertEqual(8, setup.coordination.settings(Ledger(self.path))['max_sessions'])

    def test_invalid_capacity_does_not_revoke_existing_setup(self):
        ledger = Ledger(self.path)
        ledger.complete_setup(services=['claude'], api_services=[], source='test')
        self.assertEqual(2, self.run_setup('--services', 'codex', '--mode', 'observed', '--max-sessions', '0', '--yes')[0])
        self.assertEqual(['claude'], ledger.setup_status()['services'])

    def test_status_missing_ledger_is_read_only(self):
        code, output = self.run_setup("--status")
        self.assertEqual(code, 0)
        self.assertIn('"complete": false', output)
        self.assertFalse(self.path.exists())

    def test_invalid_changes_preserve_prior_authorization(self):
        ledger = Ledger(self.path, timezone="UTC")
        ledger.complete_setup(services=["claude"], api_services=[], source="cli")
        for extra in (["--timezone", "Europe/Warsaw"], ["--workdays", "never"], ["--cutoff", "25:00"],
                      ["--api-services", "not-a-provider"], ["--monthly-budget", "10"]):
            with self.subTest(extra=extra):
                self.assertEqual(self.run_setup("--services", "codex", "--mode", "strict", "--yes", *extra)[0], 2)
                self.assertEqual(ledger.setup_status()["services"], ["claude"])

    def test_write_failure_revokes_old_completion(self):
        ledger = Ledger(self.path)
        ledger.complete_setup(services=["claude"], api_services=[], source="cli")
        with patch.object(Ledger, "set_mode", side_effect=ValueError("fixture failure")):
            self.assertEqual(self.run_setup("--services", "codex", "--mode", "strict", "--yes")[0], 2)
        self.assertFalse(ledger.setup_status()["complete"])


if __name__ == "__main__":
    unittest.main()
