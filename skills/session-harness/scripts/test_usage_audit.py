import json
from pathlib import Path
import tempfile
import unittest

import usage_audit


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def write(self, name, rows):
        path = self.home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('\n'.join(json.dumps(row) for row in rows))

    def test_copied_codex_forks_do_not_multiply_responses(self):
        record = {'type': 'token_usage_record', 'timestamp': '2026-05-01T12:00:00Z',
                  'payload': {'response_id': 'response-a', 'usage': {
                      'input_tokens': 100, 'cached_input_tokens': 80, 'output_tokens': 10, 'total_tokens': 110}}}
        for name in ['parent', 'child']:
            self.write('.codex/sessions/' + name + '.jsonl', [
                {'type': 'turn_context', 'payload': {'model': 'example-model'}}, record])
        rows = usage_audit.token_history(self.home)['codex']['rows']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['total_tokens'], 110)
        self.assertEqual(rows[0]['input_tokens'], 100)

    def test_claude_stream_and_session_copies_deduplicate(self):
        record = {'type': 'assistant', 'timestamp': '2026-05-01T12:00:00Z', 'sessionId': 'one',
                  'message': {'id': 'message-a', 'model': 'example-model',
                              'content': 'PRIVATE PROMPT MUST NOT APPEAR',
                              'usage': {'input_tokens': 10, 'output_tokens': 2}}}
        self.write('.claude/projects/one/a.jsonl', [record])
        record['sessionId'] = 'copy'
        record['message']['usage']['output_tokens'] = 7
        self.write('.claude/projects/copy/a.jsonl', [record,
            {'type': 'cost-state', 'sessionId': 'one', 'totalCostUSD': 0.4}])
        result = usage_audit.token_history(self.home)
        self.assertEqual(result['claude']['rows'][0]['output_tokens'], 7)
        self.assertEqual(result['claude']['rows'][0]['input_tokens'], 10)
        self.assertNotIn('PRIVATE PROMPT', json.dumps(result))
        self.assertEqual(result['claude']['cost_estimate_usd_examined_sessions'], 0.4)
        self.assertIn('not date-filtered charges', result['claude']['cost_estimate_scope'])

    def test_missing_and_malformed_data_are_coverage_gaps(self):
        path = self.home / '.codex/sessions/a.jsonl'
        path.parent.mkdir(parents=True)
        path.write_text('invalid\n[]\n')
        result = usage_audit.token_history(self.home)
        self.assertEqual(result['codex']['malformed_records'], 2)
        self.assertEqual(result['claude']['files'], 0)
        self.assertIn('no verified', result['antigravity']['coverage'])
        with self.assertRaises(ValueError):
            usage_audit.token_history(self.home, 'yesterday')


if __name__ == '__main__':
    unittest.main()
