"""Explicit environment authorization guards every inference coordinator."""
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import api_execution
import api_providers
import harness
import usage
from quota import Ledger
from spend import SpendLedger


class SetupAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'ledger.db'
        self.ledger = Ledger(self.path)
        default = patch('quota.default_path', return_value=self.path)
        default.start()
        self.addCleanup(default.stop)

    def complete(self, services=None, apis=None):
        self.ledger.complete_setup(services=services or [], api_services=apis or [], source='test')

    def test_fresh_or_reopened_ledger_and_modes_never_imply_setup(self):
        self.ledger.set_mode('observed')
        for ledger in (self.ledger, Ledger(self.path)):
            self.assertFalse(ledger.setup_status()['complete'])
            with patch.object(usage, 'refresh') as refresh:
                result = usage.require_admission('claude', ledger=ledger)
                self.assertFalse(result['allowed'])
                self.assertIn('environment_setup_required', result['reasons'])
                refresh.assert_not_called()

    def test_all_native_launches_stop_before_discovery_until_setup(self):
        with patch.object(harness, 'discover_provider') as discover, redirect_stdout(StringIO()):
            for service in ('codex', 'claude', 'antigravity'):
                self.assertEqual(2, harness.main(['launch', service, '--execute']))
                self.assertEqual(2, harness.main(['launch', service]))
            discover.assert_not_called()

    def test_missing_api_setup_precedes_credentials_and_network(self):
        money = SpendLedger(ledger=self.ledger)
        money.configure('total', '100', mode='observed')
        with patch.object(api_providers, 'preflight') as preflight:
            with self.assertRaisesRegex(ValueError, 'environment_setup_required'):
                api_execution.execute('xai', 'model', 'text', 10, '0.01', ledger=money)
            preflight.assert_not_called()
        self.assertEqual([], money.status()['unfinished'])

    def test_native_setup_cannot_authorize_api_or_unselected_native(self):
        self.complete(['claude'])
        self.ledger.require_setup('native', 'claude')
        for route, service in [('api', 'xai'), ('native', 'codex')]:
            with self.assertRaisesRegex(ValueError, 'service_not_configured'):
                self.ledger.require_setup(route, service)

    def test_api_setup_still_requires_a_monthly_cap(self):
        self.complete(apis=['xai'])
        money = SpendLedger(ledger=self.ledger)
        with self.assertRaisesRegex(ValueError, 'total'):
            money.authorize('api:xai', '0.01', 'USD', 'a' * 64)
        self.assertEqual([], money.status()['unfinished'])

    def test_invalid_setup_is_fail_closed_and_can_be_reset(self):
        for value in ['null', '{}', '{broken', json.dumps({'version': 2, 'complete': True})]:
            with self.ledger._connect() as db:
                db.execute("INSERT OR REPLACE INTO state VALUES ('setup_v1', ?)", (value,))
            self.assertFalse(usage.require_admission('claude', ledger=self.ledger)['allowed'])
        self.ledger.reset_setup()
        self.assertFalse(self.ledger.setup_status()['complete'])

    def test_setup_reset_preserves_money_and_policy(self):
        self.complete(['claude'])
        money = SpendLedger(ledger=self.ledger)
        money.configure('total', '100', mode='observed')
        self.ledger.set_mode('observed')
        self.ledger.reset_setup()
        self.assertEqual('observed', Ledger(self.path).mode())
        self.assertEqual('100.0000000000', money.status()['caps'][0]['cap'])

    def test_transport_claim_is_durable_single_use_and_revocation_blocks(self):
        self.complete(apis=['xai'])
        money = SpendLedger(ledger=self.ledger)
        money.configure('total', '100', mode='observed')
        with patch.dict(os.environ, {'XAI_API_KEY': 'fixture-key'}):
            prepared = api_providers.preflight('xai', 'model', 'text', 10)
        auth = money.authorize('api:xai', '0.01', 'USD', prepared.digest)
        first = api_execution._Admission(money, auth['id'], prepared.digest)
        first.claim(prepared)
        with self.assertRaisesRegex(ValueError, 'already claimed'):
            api_execution._Admission(money, auth['id'], prepared.digest).claim(prepared)
        second = money.authorize('api:xai', '0.01', 'USD', prepared.digest)
        self.ledger.reset_setup()
        with self.assertRaisesRegex(ValueError, 'environment_setup_required'):
            api_execution._Admission(money, second['id'], prepared.digest).claim(prepared)


if __name__ == '__main__':
    unittest.main()
