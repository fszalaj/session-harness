"""Model-aware selection, private hook state and exact-session recovery."""
from contextlib import closing
import copy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid

import claude_admission as admission
import claude_session as session
import coordination
import harness
import model_scope
import supervision

FABLE, OPUS, SONNET = 'claude-fable-99-1', 'claude-opus-99', 'claude-sonnet-99'


def receipt(model, allowed=True, common=False):
    scope = model_scope.native_scope({'id': None, 'display_name': 'Fable'})
    return dict(allowed=allowed, model_admission_version=1, models=[model],
        reasons=[] if allowed else ['weekly:daily_limit' if common else 'fable:daily_limit'],
        pools=[dict(pool='fable', model_scope=scope, applicable=True, reasons=['daily_limit'])])


def capability():
    return dict(executable='mock-claude', auth={'status': 'subscription'},
        model_switch_hooks_supported=True, planner={'model': FABLE, 'effort': 'max'},
        worker={'model': SONNET, 'effort': 'medium'},
        models=[dict(id=m, account_selectable=True, efforts=['low', 'medium', 'high', 'max'])
                for m in (FABLE, OPUS, SONNET, 'claude-opus-98')])


class SelectionTests(unittest.TestCase):
    def test_scope_stop_selects_current_opus_with_common_admission(self):
        checks = []
        def check(model):
            checks.append(model)
            return receipt(model, model == OPUS)
        choice, _ = admission.choose(capability(), 'planner', check=check)
        self.assertEqual(checks, [FABLE, OPUS])
        self.assertEqual(choice['model'], OPUS)
        self.assertEqual(choice['effort'], 'max')

    def test_common_or_legacy_denial_does_not_try_another_model(self):
        for value in (receipt(FABLE, False, True), {'allowed': True}):
            with patch('coordination.dispatch', return_value=value) as check:
                with self.assertRaises(supervision.Stop):
                    admission.choose(capability(), 'planner')
                self.assertEqual(check.call_count, 1)

    def test_worker_effort_and_duplicate_alias_intersection(self):
        cap = capability()
        cap['models'].append(dict(id='opus', resolved_model=OPUS, account_selectable=True,
                                 efforts=['low', 'medium']))
        choices = admission.candidates(cap, 'worker')
        self.assertEqual([c['model'] for c in choices], [SONNET, OPUS])
        self.assertEqual([c['effort'] for c in choices], ['medium', 'low'])
        self.assertEqual(admission.candidates(cap, 'planner')[-1]['effort'], 'medium')

    def test_old_remote_authority_cannot_drop_models(self):
        class Result:
            returncode = 0
            stdout = b'{"allowed":true}'
        with tempfile.TemporaryDirectory() as directory:
            from quota import Ledger
            ledger = Ledger(Path(directory) / 'ledger.db')
            ledger.complete_setup(services=['claude'], api_services=[], source='test')
            coordination.configure(ledger, authority='trusted-host')
            with patch('subprocess.run', return_value=Result()), patch('platform_runtime.which', return_value='ssh'):
                with self.assertRaisesRegex(ValueError, 'model admission'):
                    coordination.dispatch('check', 'claude', 'test', ledger, models=[OPUS])


@unittest.skipUnless(os.name == 'posix', 'POSIX interactive model tracking')
class SessionTests(unittest.TestCase):
    def exercise(self, mutation=None, extra=(), normal=False):
        cap = capability()
        response = harness.launch_plan('claude', 'planner', cap, list(extra))
        calls = []
        def terminal(argv, env, service, **kwargs):
            calls.append(argv)
            path = env[session.ENV]
            identity = argv[argv.index('--session-id') + 1] if '--session-id' in argv else argv[argv.index('--resume') + 1]
            if len(calls) == 1:
                session.hook({'hook_event_name': 'SessionStart', 'session_id': identity}, path, 'test')
                self.identity = identity
                if normal:
                    return 0
                stop = supervision.Stop('claude', ['fable:daily_limit'], receipt=receipt(FABLE, False))
                stop.inference_interrupted = True
                stop.session_cleanup = {'state': 'stopped', 'owner_retained': False, 'errors': []}
                kwargs['on_stop'](stop)
                if mutation:
                    mutation(stop)
                session.hook({'hook_event_name': 'SessionEnd', 'session_id': identity}, path, 'test')
                raise stop
            self.assertEqual(argv[argv.index('--resume') + 1], self.identity)
            self.assertEqual(argv[argv.index('--model') + 1], OPUS)
            self.assertEqual(kwargs['models'](), [OPUS])
            return 0
        with patch('supervision.run_terminal', side_effect=terminal), \
                patch('harness.discover_provider', return_value=cap), \
                patch('harness.require_role', return_value={'allowed': True}), \
                patch('coordination.dispatch', side_effect=lambda action, service, owner, **kw: receipt(kw['models'][0])):
            result = session.run(cap, response, {})
        return result, calls

    def test_scoped_stop_resumes_exact_session_once_after_cleanup(self):
        result, calls = self.exercise()
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 2)

    def test_explicit_resume_keeps_requested_identity(self):
        result, calls = self.exercise(extra=('--resume', str(uuid.uuid4())))
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 2)

    def test_normal_exit_never_restarts(self):
        self.assertEqual(len(self.exercise(normal=True)[1]), 1)

    def test_unsafe_or_normal_exit_evidence_never_restarts(self):
        mutations = [lambda s: setattr(s, 'model_scope_stop', False),
                     lambda s: setattr(s, 'inference_interrupted', False),
                     lambda s: s.session_cleanup.update(state='unknown', owner_retained=True),
                     lambda s: s.session_cleanup.update(errors=[{'stage': 'terminal_attributes'}]),
                     lambda s: s.model_session.update(ended=True),
                     lambda s: s.model_session.update(started=False)]
        for mutate in mutations:
            with self.subTest(mutation=mutate), self.assertRaises(supervision.Stop):
                self.exercise(mutation=mutate)
        self.assertIsNone(session.recovery_arguments(['claude', '--model', FABLE, '--effort', 'max', 'a prompt']))

    def test_hook_model_switch_children_and_unknown_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.db'
            path.touch(mode=0o600)
            identity = str(uuid.uuid4())
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE state(value TEXT)')
                db.execute('INSERT INTO state VALUES (?)', (json.dumps(dict(session=identity, model=OPUS,
                    role='planner', children=[], started=True, ended=False)),))
            def event(name, **extra):
                return session.hook(dict(hook_event_name=name, session_id=identity, **extra), path, 'test')
            with patch('harness.require_role', return_value={}), \
                    patch('coordination.dispatch', return_value=receipt(FABLE, False)) as check:
                denial = event('PreModelSwitch', to_model=FABLE)
                self.assertEqual(denial['hookSpecificOutput']['permissionDecision'], 'deny')
                self.assertEqual(session.models(path), [OPUS])
                event('PostModelSwitch', to_model=SONNET)
                self.assertEqual(session.models(path), [SONNET])
                event('SubagentStart', agent_id='child')
                self.assertIsNone(session.models(path))
                event('PreToolUse', tool_name='Agent')
                self.assertNotIn('models', check.call_args.kwargs)
                event('SubagentStop', agent_id='child')
                event('PostModelSwitch', to_model='unknown')
                with self.assertRaises(ValueError):
                    session.models(path)


if __name__ == '__main__':
    unittest.main()
