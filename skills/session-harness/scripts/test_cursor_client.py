"""Cursor quota, routing and receipt boundaries."""
import copy
import json
import time
import unittest
import tempfile
from pathlib import Path
from quota import Ledger
from unittest.mock import patch

import credits
import cursor_client
import harness


def quota():
    now = time.time()
    return {'observed_at': now, 'account_fingerprint': 'a' * 64,
            'plan': {'planName': 'Free'}, 'hard_limit': {'noUsageBasedAllowed': True},
            'usage': {'billingCycleStart': str(int((now-86400)*1000)),
                      'billingCycleEnd': str(int((now+86400*29)*1000)),
                      'planUsage': {'remainingBonus': False, 'totalPercentUsed': 12,
                                    'autoPercentUsed': 10, 'apiPercentUsed': 2},
                      'spendLimitUsage': {'limitType': 'user', 'pooledLimit': 0, 'pooledRemaining': 0,
                                         'individualLimit': 0, 'overallLimit': 0, 'overallRemaining': 0}},
            'limits': {'usageLimitPolicyStatus': {}}, 'grants': {}}


class CursorTests(unittest.TestCase):
    def test_quota_and_paid_controls(self):
        snap = cursor_client.quota_snapshot(quota())
        self.assertEqual(snap['pools'][0]['used_percent'], 12)
        self.assertEqual(credits.native_reasons('cursor', snap['credit_resources']), [])
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / 'quota.sqlite3')
            recorded = ledger.record(snap, initialize=True)
            self.assertEqual(recorded['pools'][0]['remaining_percent'], 88)
        for key, value in [('observed_at', time.time()-31), ('grants', {'balance': 1}),
                           ('hard_limit', {}), ('plan', {'planName': 'Pro'}),
                           ('limits', {'activeGrants': []})]:
            data = quota(); data[key] = value
            with self.assertRaises((ValueError, KeyError)): cursor_client.quota_snapshot(data)
        data = quota(); data['usage']['planUsage']['totalPercentUsed'] = float('nan')
        with self.assertRaises(ValueError): cursor_client.quota_snapshot(data)
        data = quota(); data['usage']['spendLimitUsage']['overallRemaining'] = 1
        with self.assertRaises(ValueError): cursor_client.quota_snapshot(data)

    def test_stream_and_denied_permissions(self):
        cap = {'executable': '/mock/cursor', 'planner': {'model':'auto', 'effort':None},
               'models':[{'id':'auto', 'display_name':'Auto'}]}
        events = [{'type':'system','subtype':'init','apiKeySource':'login','model':'Auto','session_id':'test-id'},
                  {'type':'assistant','session_id':'test-id','message':{'content':[{'type':'text','text':'checked'}]}},
                  {'type':'result','subtype':'success','is_error':False,'result':'checked','session_id':'test-id',
                   'request_id':'request-id','usage':{'inputTokens':10,'outputTokens':2,'cacheReadTokens':0,'cacheWriteTokens':0}}]
        def run(argv, **kwargs):
            from pathlib import Path
            policy=json.loads((Path(kwargs['cwd'])/'.cursor/cli.json').read_text())
            self.assertIn('Mcp(*:*)', policy['permissions']['deny'])
            self.assertEqual(kwargs['quota_service'], 'cursor')
            self.assertIn(b'check', kwargs['stdin'])
            self.assertNotIn('check', argv)
            self.assertEqual(kwargs['env']['SESSION_HARNESS_LEAF'], '1')
            self.assertTrue(Path(kwargs['env']['CURSOR_CONFIG_DIR']).is_dir())
            self.assertEqual(kwargs['env']['CURSOR_FORCED_SHELL_EGRESS_ALLOW_WEB_TOOLS'], '0')
            for event in run.events: kwargs['on_stdout_line'](json.dumps(event))
            return ''
        run.events=events
        with patch.object(harness, 'checked', side_effect=run), patch.object(cursor_client, 'metadata', return_value=quota()):
            result=cursor_client.execute(b'check', 15, cap, task=True)
            self.assertEqual(result['completion_tokens'], 2)
            self.assertIsNone(result['actual_model'])
            for changes in [{'model':'Unexpected'}, {'apiKeySource':'apiKey'}]:
                run.events=copy.deepcopy(events);run.events[0].update(changes)
                with self.assertRaises(harness.HarnessError): cursor_client.execute(b'check',15,cap,task=True)
            run.events=events[:1]+[{'type':'tool_call','session_id':'test-id'}]
            with self.assertRaises(harness.HarnessError): cursor_client.execute(b'check',15,cap,task=True)
            run.events=events[:2]
            with self.assertRaises(harness.HarnessError): cursor_client.execute(b'check',15,cap,task=True)
            for malformed in [[], {'type':'assistant','session_id':'test-id','message':{'content':[None]}}]:
                run.events=events[:1]+[malformed]
                with self.assertRaises(harness.HarnessError): cursor_client.execute(b'check',15,cap,task=True)

    def test_launch_rejects_routing_override(self):
        cap={'status':'available','planner':{'model':'composer-9','effort':None},'executable':'cursor-agent'}
        for flag in ['--endpoint=https://elsewhere.invalid','--api-key=x','--header=Authorization:x','--model=auto','-p',
                     '-ehttps://elsewhere.invalid', '-HAuthorization:x', 'worker', 'bedrock']:
            with self.assertRaises(harness.HarnessError): harness.launch_plan('cursor','planner',cap,[flag])
        self.assertEqual(harness.launch_plan('cursor','planner',cap)['argv'], ['cursor-agent','--model','composer-9'])

    def test_discovery_free_route_strips_catalog_markers(self):
        with patch.object(harness, 'checked', side_effect=['{"isAuthenticated":true}', 'auto - Auto (default)\ncomposer-9 - Composer 9 (current)']), \
             patch.object(cursor_client, 'metadata', return_value=quota()):
            result=cursor_client.discover('/mock/cursor')
        self.assertEqual(result['worker']['model'], 'auto')
        self.assertEqual(result['models'][0]['display_name'], 'Auto')


if __name__ == '__main__': unittest.main()
