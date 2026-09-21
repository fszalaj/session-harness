"""Budgeted Jev decisions through OpenRouter's separate alpha protocol."""
from decimal import Decimal
import hashlib
import json
import math
import re

from api_transport import APIError, decode_json, request_json, validate_request

ORIGIN = 'https://openrouter.ai'
PATH = '/api/alpha/decisions'
CATALOG_PATH = '/api/v1/models?output_modalities=decisions'
LATEST = '~typesafe/jev-latest'
MAX_BYTES = 24 * 1024


def catalog():
    data = request_json(ORIGIN, CATALOG_PATH, timeout=20)
    rows = data.get('data')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5000:
        raise APIError('invalid_decision_catalog')
    models, target, seen = [], None, set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or row['id'] in seen:
            raise APIError('invalid_decision_catalog')
        seen.add(row['id'])
        if row['id'] == LATEST:
            alias = row.get('alias_target')
            target = alias.get('slug') if isinstance(alias, dict) else None
        elif re.fullmatch(r'typesafe/jev-[0-9]+(?:\.[0-9]+)+(?:-[0-9]{8})?', row['id']):
            from api_providers import _model
            canonical = _model(row.get('canonical_slug'))
            architecture = row.get('architecture')
            if (not canonical.startswith('typesafe/jev-') or not isinstance(architecture, dict)
                    or architecture.get('output_modalities') != ['decisions']):
                raise APIError('invalid_decision_catalog')
            models.append({'id': row['id'], 'canonical_slug': canonical})
    default = target if target in {row['id'] for row in models} else None
    return {'status': 'decision_catalog', 'models': models, 'default_model': default,
            'source': ORIGIN + CATALOG_PATH, 'inference_verified': False,
            'entitlement_verified': False}


def _text(value):
    return isinstance(value, (str, dict, list)) and bool(value)


def _questions(value):
    if not isinstance(value, dict) or not 1 <= len(value) <= 128:
        raise APIError('invalid_decision_questions')
    for ident, question in value.items():
        if (not isinstance(ident, str) or not ident.strip() or len(ident) > 256
                or not isinstance(question, dict)
                or set(question) - {'type', 'instructions', 'criteria'}
                or not _text(question.get('instructions'))):
            raise APIError('invalid_decision_question')
        kind, criteria = question.get('type'), question.get('criteria')
        if kind == 'noul':
            valid = 'criteria' not in question or (
                isinstance(criteria, dict) and set(criteria) == {'true', 'false'}
                and all(_text(v) for v in criteria.values()))
        elif kind == 'choice':
            valid = (isinstance(criteria, dict) and 1 <= len(criteria) <= 255
                     and all(isinstance(k, str) and k.strip() and (v is None or _text(v))
                             for k, v in criteria.items()))
        elif kind == 'score':
            valid = isinstance(criteria, list) and 2 <= len(criteria) <= 10 and all(map(_text, criteria))
        else:
            valid = False
        if not valid:
            raise APIError('invalid_decision_criteria')


def preflight(service, model, prompt, max_output_tokens, effort=None):
    from api_providers import PreparedRequest, _headers
    if service != 'openrouter' or max_output_tokens is not None or effort is not None:
        raise APIError('unsupported_decision_route')
    if not isinstance(prompt, (str, bytes)) or len(prompt) > 262144:
        raise APIError('invalid_decision_input')
    payload = decode_json(prompt)
    if set(payload) != {'state', 'questions'} or not _text(payload['state']):
        raise APIError('invalid_decision_input')
    _questions(payload['questions'])
    headers = _headers(service)
    metadata = catalog()
    selected = model or metadata['default_model']
    row = next((row for row in metadata['models'] if row['id'] == selected), None)
    if row is None:
        raise APIError('decision_model_unavailable_pass_explicit_model')
    try:
        original = (prompt.decode('utf-8') if isinstance(prompt, bytes) else prompt).strip()
        if not original.startswith('{'):
            raise APIError('invalid_decision_input')
        envelope = json.dumps({'model': selected, 'provider': {
            'allow_fallbacks': False, 'require_parameters': True}}, separators=(',', ':'))
        # Preserve validated input numbers without a float round trip.
        encoded = (envelope[:-1] + ',' + original[1:]).encode('utf-8')
    except (ValueError, UnicodeError, RecursionError):
        raise APIError('invalid_decision_input') from None
    if len(encoded) > MAX_BYTES:
        raise APIError('decision_input_exceeds_24_kib')
    validate_request(ORIGIN, PATH, 'POST', headers, encoded, 120)
    digest = hashlib.sha256(service.encode() + b'\0' + PATH.encode() + b'\0' + encoded).hexdigest()
    return PreparedRequest(service, selected, 0, digest, ORIGIN, PATH, headers, encoded,
                           expected_models=(row['id'], row['canonical_slug']))


def _number(value, maximum=1):
    if (isinstance(value, bool) or not isinstance(value, (int, Decimal))
            or not 0 <= value <= maximum):
        raise APIError('invalid_decision_number')
    return value


def _answers(questions, answers):
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise APIError('invalid_decision_answers')
    for ident, question in questions.items():
        answer, kind = answers[ident], question['type']
        if not isinstance(answer, dict) or answer.get('type') != kind:
            raise APIError('invalid_decision_answer')
        allowed = {'type', kind} if kind == 'noul' else {'type', kind, 'confidence', 'probabilities'}
        if kind == 'score':
            allowed.add('legend')
        if set(answer) - allowed:
            raise APIError('invalid_decision_answer')
        if kind == 'noul':
            _number(answer.get('noul'))
            continue
        criteria = question['criteria']
        keys = set(criteria) if kind == 'choice' else {str(i) for i in range(len(criteria))}
        if kind == 'choice':
            if not isinstance(answer.get('choice'), str) or answer['choice'] not in keys:
                raise APIError('invalid_decision_choice')
        else:
            _number(answer.get('score'), len(criteria) - 1)
            if 'legend' in answer and answer['legend'] != {str(i): v for i, v in enumerate(criteria)}:
                raise APIError('invalid_decision_legend')
        if 'confidence' in answer:
            _number(answer['confidence'])
        if 'probabilities' in answer:
            probabilities = answer['probabilities']
            if not isinstance(probabilities, dict) or set(probabilities) != keys:
                raise APIError('invalid_decision_probabilities')
            total = sum(_number(p) for p in probabilities.values())
            if abs(total - 1) > Decimal('0.001'):
                raise APIError('invalid_decision_probabilities')
    return answers


def _json_numbers(value):
    if isinstance(value, Decimal):
        result = float(value)
        if not math.isfinite(result):
            raise APIError('invalid_decision_number')
        return result
    if isinstance(value, dict):
        return {k: _json_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_numbers(v) for v in value]
    return value


def normalize_response(prepared, data):
    from api_providers import _count, _model, cost_ticks
    if not isinstance(data, dict) or 'error' in data:
        raise APIError('invalid_decision_response')
    cost = cost_ticks('openrouter', data.get('usage'))
    result = {'actual_cost_ticks': cost, 'usage_complete': False, 'usage': {},
              'model': None, 'response_id': None, 'output_valid': False, 'answers': None}
    try:
        result['model'] = _model(data.get('model'))
        ident = data.get('id')
        if isinstance(ident, str) and re.fullmatch(r'[A-Za-z0-9._:/+=-]{1,256}', ident):
            result['response_id'] = ident
        usage = data.get('usage')
        if isinstance(usage, dict):
            result['usage'] = {key: _count(usage.get(key)) for key in ('input_tokens', 'output_tokens')}
            result['usage_complete'] = True
        if cost is None or result['model'] not in prepared.expected_models:
            return result
        questions = decode_json(prepared.body)['questions']
        result['answers'] = _json_numbers(_answers(questions, data.get('answers')))
        result['output_valid'] = True
    except (APIError, TypeError, ArithmeticError, RecursionError):
        pass
    return result
