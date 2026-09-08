"""Allowlisted Claude initialize metadata; no user message or inference probe."""
import json
import re
import tempfile
import uuid

import harness
from inventory import EFFORTS, SAFE_ID, normalize_models


def resolved_model(alias, value):
    if value is None:
        return None
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ValueError('Invalid resolved model identifier')
    match = re.fullmatch(r'claude-([a-z]+)-(\d+(?:[-.]\d+)*)(?:\[1m\])?', value)
    if not match:
        raise ValueError('Resolved model must be concrete')
    if harness.generation(value, 'claude') is None:
        raise ValueError('Invalid resolved model generation')
    tier = match[1]
    if tier not in {'fable', 'opus', 'sonnet', 'haiku'}:
        return None
    alias_tier = re.fullmatch(r'(?:claude-)?(fable|opus|sonnet|haiku)(?:-\d+(?:[-.]\d+)*)?(?:\[1m\])?', alias)
    if alias_tier and alias_tier[1] != tier:
        raise ValueError('Resolved model tier differs from alias')
    if harness.generation(alias, 'claude') is not None:
        expected, actual = alias.removesuffix('[1m]'), value.removesuffix('[1m]')
        if actual != expected and not re.fullmatch(re.escape(expected) + r'-\d{8}', actual):
            raise ValueError('Concrete model resolution changed')
    return value


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate metadata field')
        result[key] = value
    return result


def parse_initialize(stdout, request_id):
    events = [json.loads(line, object_pairs_hook=unique_fields)
              for line in stdout.splitlines() if line.strip()]
    if len(events) != 1 or not isinstance(events[0], dict) or events[0].get('type') != 'control_response':
        raise ValueError('Unexpected initialize event')
    response = events[0].get('response')
    if (not isinstance(response, dict) or response.get('subtype') != 'success'
            or response.get('request_id') != request_id or 'error' in response):
        raise ValueError('Invalid initialize response')
    payload = response.get('response')
    if not isinstance(payload, dict) or not isinstance(payload.get('models'), list):
        raise ValueError('Missing selectable model metadata')
    safe, seen = [], set()
    for row in payload['models']:
        if not isinstance(row, dict):
            raise ValueError('Invalid model metadata')
        ident = row.get('value')
        if not isinstance(ident, str) or not SAFE_ID.fullmatch(ident) or ident in seen:
            raise ValueError('Invalid model identifier')
        seen.add(ident)
        efforts = row.get('supportedEffortLevels', [])
        if not isinstance(efforts, list) or any(not isinstance(e, str) or e not in EFFORTS for e in efforts):
            raise ValueError('Invalid reasoning metadata')
        models = normalize_models({'models': [{'id': ident, 'supportedReasoningEfforts': efforts}]},
                                  'claude', evidence_kind='client_selectable_metadata',
                                  source='initialize.response.models')
        model = models[0]
        model['alias_resolution'] = 'unresolved'
        resolved = resolved_model(ident, row.get('resolvedModel'))
        if resolved:
            model.update(resolved_model=resolved, alias_resolution='client_initialize',
                         resolution_source='initialize.response.models.resolvedModel')
        for key in ('supportsEffort', 'supportsAdaptiveThinking', 'supportsFastMode', 'supportsAutoMode'):
            if key in row:
                if type(row[key]) is not bool:
                    raise ValueError('Invalid capability metadata')
                model['native_controls'][key] = row[key]
        safe.append(model)
    return safe


def discover(executable, authenticated=None):
    result = {'models': [], 'status': 'auth_unverified', 'entitlement_verified': False,
              'inference_verified': False, 'evidence': {'kind': 'client_selectable_metadata'}}
    if authenticated is not True:
        return result
    ident = uuid.uuid4().hex
    argv = [executable, '--safe-mode', '--no-session-persistence', '--no-chrome',
            '--strict-mcp-config', '--setting-sources', '', '--tools', '',
            '--permission-mode', 'dontAsk', '--input-format', 'stream-json',
            '--output-format', 'stream-json', '--verbose', '--debug-file', '/dev/stderr', '-p']
    request = {'type': 'control_request', 'request_id': ident, 'request': {'subtype': 'initialize'}}
    try:
        with tempfile.TemporaryDirectory(prefix='session-harness-models-') as directory:
            code, stdout, _ = harness.run(argv, stdin=(json.dumps(request) + '\n').encode(),
                                          timeout=15, cwd=directory, env=harness.child_env(leaf=True))
        if code:
            raise ValueError('Initialize failed')
        result['models'] = parse_initialize(stdout, ident)
        for model in result['models']:
            model['account_selectable'] = True
        result['status'] = 'client_selectable_metadata'
    except (OSError, ValueError, TypeError, harness.HarnessError):
        result['status'] = 'metadata_unavailable'
    return result
