import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import usage_audit
from quota import Ledger
from spend import SpendLedger


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

    def test_offset_dates_and_invalid_first_mirror(self):
        payload = {'response_id': 'a', 'usage': {'input_tokens': 4}}
        self.write('.codex/sessions/a.jsonl', [
            {'type': 'token_usage_record', 'timestamp': 'invalid', 'payload': payload},
            {'type': 'token_usage_record', 'timestamp': '2026-05-02T00:30:00+02:00', 'payload': payload}])
        rows = usage_audit.token_history(self.home)['codex']['rows']
        self.assertEqual(rows[0]['day'], '2026-05-01')
        self.assertEqual(rows[0]['response_count'], 1)
        self.assertEqual([], usage_audit.token_history(self.home, since='2026-05-02')['codex']['rows'])

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

    def test_mirrored_parent_records_keep_origin_role_and_one_response(self):
        record = {'type': 'token_usage_record', 'timestamp': '2026-05-01T12:00:00Z',
                  'payload': {'session_id': 'parent', 'response_id': 'one', 'usage': {'input_tokens': 50}}}
        self.write('.codex/sessions/child.jsonl', [
            {'type': 'session_meta', 'payload': {'id': 'child', 'source': {'subagent': {}}}}, record])
        self.write('.codex/sessions/parent.jsonl', [
            {'type': 'session_meta', 'payload': {'id': 'parent', 'source': 'vscode'}}, record])
        result = usage_audit.token_history(self.home)['codex']
        self.assertEqual(result['rows'][0]['response_count'], 1)
        self.assertEqual(result['sessions'][0]['session_id'], 'parent')
        self.assertEqual(result['sessions'][0]['role'], 'manager')
        self.assertEqual(result['sessions'][0]['input_tokens'], 50)

    def test_authority_audit_separates_work_charges_and_pending_liability(self):
        money = SpendLedger(self.home / 'ledger.db')
        money.ledger.complete_setup(services=[], api_services=['openrouter'], source='test')
        money.configure('total', '10', mode='observed')
        money.authorize('api:openrouter', '0.01', 'USD', 'a' * 64, 'settled')
        money.settle('settled', 100, 'provider:fixture')
        money.authorize('api:openrouter', '0.02', 'USD', 'b' * 64, 'pending')
        money.unresolved('pending')
        import balance
        with money.ledger._connect() as db:
            balance._table(db)
            db.execute('INSERT INTO balance_jobs VALUES (?,?,?,?,?)',
                       ('worker', 'claude', '2026-05-01', 'completed', '{"private_prompt":"DO NOT LEAK"}'))
        report = usage_audit.account_report(money.ledger, '2026-05-01')
        self.assertEqual(report['work_receipts'][0]['count'], 1)
        settled = next(r for r in report['api_requests'] if r['status'] == 'SETTLED')
        pending = next(r for r in report['api_requests'] if r['status'] == 'UNRESOLVED')
        self.assertEqual(settled['charged_ticks'], 100)
        self.assertEqual(pending['pending_ticks'], 200000000)
        self.assertNotIn('DO NOT LEAK', json.dumps(report))

    def test_remote_audit_failure_never_claims_local_counters_are_authoritative(self):
        ledger = Ledger(self.home / 'ledger.db')
        with patch.object(usage_audit.coordination, 'settings', return_value={'authority': 'fixture'}), \
                patch.object(usage_audit.coordination, 'balance_dispatch', side_effect=ValueError('unsupported')):
            result = usage_audit.report(ledger, home=self.home)
        self.assertEqual(result['accounting_status'], 'authority_unavailable')
        self.assertEqual(result['quota_history'], {})
        self.assertIn('local_accounting', result)


if __name__ == '__main__':
    unittest.main()
