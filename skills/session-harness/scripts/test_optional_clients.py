import json
import unittest
from unittest.mock import patch

import inventory
import optional_clients


class OptionalClientsTests(unittest.TestCase):
    def test_absent_registry_never_launches(self):
        with patch('inventory.shutil.which', return_value=None), patch('inventory.harness.run') as run, patch('inventory.subprocess.Popen') as popen:
            results = inventory.discover_all()
        self.assertEqual(len(results), 8)
        self.assertTrue(all(row['status'] == 'not_installed' for row in results.values()))
        run.assert_not_called()
        popen.assert_not_called()
        for family in ('grok', 'deepseek', 'glm'):
            with self.assertRaises(ValueError):
                inventory.discover(family)

    def test_presence_does_not_launch_or_claim_auth(self):
        with patch('optional_clients.harness.run') as run:
            for service in ('kimi', 'opencode', 'aider', 'continue', 'gemini'):
                result = optional_clients.discover(service, '/mock/' + service)
                self.assertEqual(result['status'], 'installed_presence_only')
                self.assertIsNone(result['authenticated'])
                self.assertFalse(result['execution_supported'])
            run.assert_not_called()

    def test_loopback_only_and_local_not_entitlement(self):
        with patch.dict('os.environ', {'OLLAMA_HOST': 'https://private.invalid', 'HTTPS_PROXY': 'https://private.invalid'}), patch('optional_clients.harness.run', return_value=(0, 'NAME ID SIZE MODIFIED\nkimi-local:tag abcdef123456 1 GB now\n', 'private')) as run:
            result = optional_clients.discover('ollama', '/mock/ollama')
        self.assertEqual(run.call_args.args[0], ['/mock/ollama', 'list'])
        env = run.call_args.kwargs['env']
        self.assertEqual(env['OLLAMA_HOST'], 'http://127.0.0.1:11434')
        self.assertNotIn('HTTPS_PROXY', env)
        self.assertTrue(result['models'][0]['local'])
        self.assertIsNone(result['models'][0]['account_visible'])
        self.assertFalse(result['models'][0]['entitlement_verified'])
        self.assertNotIn('private', json.dumps(result))

    def test_catalog_is_not_authentication(self):
        row = inventory.normalize_models({'models': [{'id': 'xai/grok-next'}]}, 'opencode', True)[0]
        self.assertIsNone(row['account_visible'])
        self.assertIsNone(row['account_selectable'])
        self.assertTrue(row['advertised'])
        self.assertEqual(row['model_vendor'], 'xai')
        with patch('inventory.harness.run', side_effect=[(0, 'Cursor', ''), (0, 'gpt-next - Next', '')]):
            result = inventory.discover_cursor('/mock/cursor')
        self.assertIsNone(result['authenticated'])
        self.assertIsNone(result['models'][0]['account_visible'])

if __name__ == '__main__':
    unittest.main()
