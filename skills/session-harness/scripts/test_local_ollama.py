"""Local execution must retain ambiguous jobs and reject cloud residency."""
import tempfile
import time
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock

from api_transport import APIError
from quota import Ledger
import local_ollama as ollama


class LocalOllamaTests(unittest.TestCase):
    def test_transport_ignores_remote_host_and_proxy_overrides(self):
        connection = MagicMock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read1.side_effect = [b'{"models":[]}', b'']
        with patch.dict('os.environ', {'OLLAMA_HOST': 'https://remote.invalid', 'HTTPS_PROXY': 'https://proxy.invalid'}), \
                patch('http.client.HTTPConnection', return_value=connection) as factory:
            self.assertEqual(ollama.request('/api/tags', deadline=time.monotonic() + 5), {'models': []})
        self.assertEqual(factory.call_args.args, ('127.0.0.1', 11434))

    def test_local_contract_duplicate_cloud_and_timeout_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / 'local.sqlite3')
            calls = []
            remote, timeout = False, False

            def request(path, body=None, **kwargs):
                calls.append(path)
                if path == '/api/tags':
                    return {'models': [{'name': 'llama:1b', 'digest': 'a' * 64, 'size': 10,
                                        'details': {}}]}
                if path == '/api/show':
                    return {'model_info': {'general.architecture': 'llama', 'general.parameter_count': 100},
                            **({'remote_host': 'https://ollama.com'} if remote else {})}
                if timeout:
                    raise APIError('local_timeout')
                return {'model': 'llama:1b', 'done': True, 'done_reason': 'stop',
                        'message': {'role': 'assistant', 'content': 'private task response'},
                        'prompt_eval_count': 10, 'eval_count': 4}

            with patch.object(ollama, 'request', side_effect=request):
                result = ollama.execute('one', 'llama:1b', 'private prompt', ledger=ledger)
                self.assertEqual(result['billing_scope'], 'local:ollama')
                self.assertEqual(result['actual_model'], 'llama:1b')
                self.assertEqual(ollama.execute('one', 'llama:1b', 'private prompt', ledger=ledger)['status'],
                                 'duplicate_accounting_only')
                self.assertEqual(calls.count('/api/chat'), 1)
                with self.assertRaisesRegex(APIError, 'local_request_id_conflict'):
                    ollama.execute('one', 'llama:1b', 'changed', ledger=ledger)
                remote = True
                with self.assertRaisesRegex(APIError, 'local_model_residency_unverified'):
                    ollama.execute('cloud-alias', 'llama:1b', 'prompt', ledger=ledger)
                remote, timeout = False, True
                with self.assertRaisesRegex(APIError, 'local_timeout'):
                    ollama.execute('timed-out', 'llama:1b', 'prompt', ledger=ledger)
                timeout = False
                with self.assertRaisesRegex(APIError, 'local_request_unresolved'):
                    ollama.execute('next', 'llama:1b', 'prompt', ledger=ledger)
                with self.assertRaisesRegex(APIError, 'local_stop_confirmation_required'):
                    ollama.reconcile('timed-out', confirmed=False, ledger=ledger)
                ollama.reconcile('timed-out', confirmed=True, ledger=ledger)
                self.assertEqual(ollama.execute('next', 'llama:1b', 'prompt', ledger=ledger)['status'], 'completed')
            with ledger._connect() as db:
                rows = repr(db.execute('SELECT * FROM local_jobs').fetchall())
            self.assertNotIn('private', rows)
            self.assertFalse(ollama.local_record({}, 'model:cloud'))
            self.assertFalse(ollama.local_record({'details': {'remote_model': 'x'}}, 'alias'))


if __name__ == '__main__':
    unittest.main()
