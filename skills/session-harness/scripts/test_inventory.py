"""Metadata contract tests; no model inference or credentials."""
import json
import os
from pathlib import Path
import tempfile
import subprocess
import time
import unittest
from unittest.mock import patch, MagicMock

import inventory


class InventoryTests(unittest.TestCase):
    def test_vendor_and_generation_are_scoped(self):
        self.assertEqual(inventory.model_vendor('claude-opus-99.10'), 'anthropic')
        self.assertEqual(inventory.model_generation('gpt-99.10')['generation'], [99, 10])
        self.assertIsNone(inventory.model_vendor('future-vendor-99'))
        self.assertIsNone(inventory.model_generation('future-vendor-99'))

    def test_malformed_models_and_auth_denial(self):
        self.assertEqual(inventory.normalize_models({'models': None}, 'copilot'), [])
        self.assertEqual(inventory.normalize_models({'models': [{'id': 'gpt-99'}]}, 'copilot', False), [])
        rows = inventory.normalize_models({'models': [None, {'id': '../bad id'}, {'id': 'gpt-99'}, {'id': 'gpt-99'}]}, 'copilot')
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]['inference_verified'])
        self.assertEqual(rows[0]['native_controls']['reasoning_efforts'], [])

    def test_quota_drops_private_fields_and_invalid_values(self):
        raw = {'quotaSnapshots': {'premium_interactions': {'usedRequests': 5, 'remainingPercentage': 95,
                    'resetDate': '2026-10-01T00:00:00Z', 'tokenBasedBilling': True,
                    'email': 'secret@example.com', 'accountId': 'private', 'overage': float('nan')}}}
        rows = inventory.normalize_quota(raw)
        self.assertEqual(rows[0]['usedRequests'], 5)
        self.assertEqual(rows[0]['unit'], 'server_defined')
        self.assertNotIn('secret', json.dumps(rows))
        self.assertNotIn('private', json.dumps(rows))
        self.assertNotIn('overage', rows[0])
        self.assertEqual(inventory.normalize_quota({'quotaSnapshots': []}), [])

    def test_uninstalled_never_launches(self):
        with patch('inventory.shutil.which', return_value=None), patch('inventory.subprocess.Popen') as popen:
            self.assertEqual(inventory.discover_copilot()['status'], 'not_installed')
            self.assertEqual(inventory.discover_cursor()['status'], 'not_installed')
            popen.assert_not_called()

    def test_auth_false_no_further_metadata(self):
        client = MagicMock()
        client.request.side_effect = [{'version': '1.2.3'}, {'isAuthenticated': False, 'login': 'private'}]
        with patch('inventory.MetadataRPC', return_value=client):
            result = inventory.discover_copilot('/mock/copilot')
        self.assertEqual(result['status'], 'unauthenticated')
        self.assertEqual(client.request.call_count, 2)
        self.assertNotIn('private', json.dumps(result))
        client.close.assert_called_once()

    def test_model_visibility_survives_unavailable_quota(self):
        client = MagicMock()
        client.request.side_effect = [{}, {'isAuthenticated': True}, {'models': [{'id': 'gpt-99'}]}, ValueError('private')]
        with patch('inventory.MetadataRPC', return_value=client):
            result = inventory.discover_copilot('/mock/copilot')
        self.assertEqual(result['status'], 'account_metadata')
        self.assertEqual(result['quota_status'], 'unavailable')
        self.assertFalse(result['execution_supported'])
        self.assertNotIn('private', json.dumps(result))

    def test_rpc_forbids_inference_before_touching_process(self):
        client = inventory.MetadataRPC.__new__(inventory.MetadataRPC)
        with self.assertRaises(ValueError):
            client.request('session.create')
        with self.assertRaises(ValueError):
            client.request('session.send')

    def test_cursor_conservative_parser(self):
        rows = inventory.parse_cursor_models('Available models:\ngpt-99 - Model display name\nlogin required\n')
        self.assertEqual(rows, {'models': [{'id': 'gpt-99'}]})
        self.assertEqual(inventory.parse_cursor_models('{malformed'), {'models': []})

    def test_generic_agent_name_is_verified(self):
        completed = (0, 'Unrelated agent application', '')
        with patch('inventory.harness.run', return_value=completed) as run:
            result = inventory.discover_cursor('/mock/agent')
        self.assertEqual(result['status'], 'unrecognized_executable')
        self.assertEqual(run.call_count, 1)

    def test_complete_quota_rejects_dropped_or_invalid_pools(self):
        valid = {'entitlementRequests': 100, 'usedRequests': 5, 'remainingPercentage': 95,
                 'resetDate': '2026-10-01T00:00:00Z'}
        self.assertTrue(inventory.quota_complete({'quotaSnapshots': {'chat': valid}}))
        for bad in (None, {}, dict(valid, remainingPercentage=True),
                    dict(valid, resetDate='invalid'), dict(valid, usedRequests='unknown')):
            raw = {'quotaSnapshots': {'chat': valid, 'other': bad}}
            self.assertFalse(inventory.quota_complete(raw))
        self.assertTrue(inventory.quota_complete({'quotaSnapshots': {'chat': {'entitlementRequests': -1}}}))
        self.assertTrue(inventory.quota_complete({'quotaSnapshots': {'chat': {'isUnlimitedEntitlement': True}}}))
        self.assertFalse(inventory.quota_complete({'quotaSnapshots': {'chat': {'isUnlimitedEntitlement': 'true'}}}))

    def test_discovery_preserves_raw_incompleteness(self):
        valid = {'entitlementRequests': 100, 'usedRequests': 5, 'remainingPercentage': 95,
                 'resetDate': '2026-10-01T00:00:00Z'}
        client = MagicMock()
        client.request.side_effect = [{}, {'isAuthenticated': True}, {'models': [{'id': 'gpt-99'}]},
                                      {'quotaSnapshots': {'chat': valid, 'other': None}}]
        with patch('inventory.MetadataRPC', return_value=client):
            result = inventory.discover_copilot('/mock/copilot')
        self.assertEqual(len(result['quota']), 1)
        self.assertFalse(result['quota_complete'])

    def test_child_environment_preserves_auth_paths(self):
        env = {'PATH': '/bin', 'COPILOT_HOME': '/native/home', 'HOME': '/home/user',
               'OPENAI_API_KEY': 'private', 'COPILOT_PROVIDER_BASE_URL': 'private',
               'COPILOT_MODEL': 'private', 'CURSOR_API_KEY': 'private'}
        self.assertEqual(inventory.child_env(env),
                         {'PATH': '/bin', 'COPILOT_HOME': '/native/home', 'HOME': '/home/user'})

    @unittest.skipUnless(os.name == "posix", "POSIX executable fixture; Windows RPC/job coverage is separate")
    def test_rpc_timeout_cleans_owned_child(self):
        with tempfile.TemporaryDirectory() as temp:
            child_pid = Path(temp) / 'child.pid'
            script = Path(temp) / 'mock-client'
            script.write_text('#!/usr/bin/env python3\n'
                              'import subprocess,time,pathlib,sys\n'
                              'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"])\n'
                              f'pathlib.Path({str(child_pid)!r}).write_text(str(child.pid))\n'
                              'time.sleep(60)\n')
            script.chmod(0o700)
            rpc = inventory.MetadataRPC(str(script), timeout=0.3)
            try:
                # Wait for the fixture to own its child before exercising the timeout: interpreter
                # start-up alone exceeds 0.3 s on some hosts (0.35-0.47 s measured on macOS with a
                # Homebrew Python), and racing it would kill the client before child.pid exists.
                deadline = time.monotonic() + 10
                while not child_pid.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(child_pid.exists(), 'mock client never reported its child')
                with self.assertRaises(TimeoutError):
                    rpc.request('status.get')
            finally:
                rpc.close()
            self.assertIsNotNone(rpc.process.poll())
            pid = int(child_pid.read_text())
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                status = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='],
                                        capture_output=True, text=True).stdout.strip()
                if not status or status.startswith('Z'):
                    break
                time.sleep(0.02)
            else:
                self.fail('Owned ordinary child survived process-group cleanup')


if __name__ == '__main__':
    unittest.main()
