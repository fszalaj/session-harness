"""Explicit text-only API routes and allowlisted model/accounting metadata."""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json
import os
import re
import time
from urllib.parse import quote, urlencode

from api_transport import APIError, MAX_BODY, request_json, validate_request

# Protocol version headers are independent of dynamically selected model IDs.
SERVICES = {
    'openai': ('https://api.openai.com', '/v1', 'OPENAI_API_KEY'),
    'anthropic': ('https://api.anthropic.com', '/v1', 'ANTHROPIC_API_KEY'),
    'gemini': ('https://generativelanguage.googleapis.com', '/v1beta', 'GEMINI_API_KEY'),
    'xai': ('https://api.x.ai', '/v1', 'XAI_API_KEY'),
    'deepseek': ('https://api.deepseek.com', '', 'DEEPSEEK_API_KEY'),
    'kimi': ('https://api.moonshot.ai', '/v1', 'MOONSHOT_API_KEY'),
    'zai': ('https://api.z.ai', '/api/paas/v4', 'ZAI_API_KEY'),
    'openrouter': ('https://openrouter.ai', '/api/v1', 'OPENROUTER_API_KEY'),
}
EXACT_COST_SERVICES = frozenset({'xai', 'openrouter'})
SAFE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}\Z')
MAX_TOKENS = 1_048_576
MAX_MONEY_TICKS = 10 ** 25
TOKEN_CLASSES = frozenset({'input_tokens', 'output_tokens', 'cache_read_tokens',
                          'cache_write_tokens', 'cache_write_5m_tokens',
                          'cache_write_1h_tokens', 'reasoning_tokens'})


@dataclass(frozen=True)
class PreparedRequest:
    service: str
    model: str
    max_output_tokens: int
    digest: str
    origin: str
    path: str
    headers: dict = field(repr=False, compare=False)
    body: bytes = field(repr=False)


def _service(service):
    if not isinstance(service, str) or service not in SERVICES:
        raise APIError('unsupported_api_service')
    return SERVICES[service]


def _model(model):
    if (not isinstance(model, str) or not SAFE_ID.fullmatch(model)
            or any(part in {'.', '..', ''} for part in model.split('/'))):
        raise APIError('invalid_api_model')
    return model


def _headers(service):
    _, _, variable = _service(service)
    key = os.environ.get(variable)
    if (not isinstance(key, str) or not key.strip() or len(key) > 8192
            or not key.isascii() or re.search(r'[\x00-\x20\x7f]', key)):
        raise APIError('api_key_unavailable')
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if service == 'anthropic':
        headers.update({'x-api-key': key, 'anthropic-version': '2023-06-01'})
    elif service == 'gemini':
        headers['x-goog-api-key'] = key
    else:
        headers['Authorization'] = 'Bearer ' + key
    return headers


def preflight(service, model, prompt, max_output_tokens, effort=None):
    """Validate locally before money reservation; retain credentials only in memory."""
    origin, prefix, _ = _service(service)
    model = _model(model)
    if service == 'gemini' and model.startswith('models/'):
        model = _model(model[7:])
    if (type(max_output_tokens) is not int or not 1 <= max_output_tokens <= MAX_TOKENS):
        raise APIError('invalid_api_output_limit')
    if effort is not None:
        raise APIError('unsupported_api_effort')
    if isinstance(prompt, bytes):
        try:
            prompt = prompt.decode('utf-8')
        except UnicodeError:
            raise APIError('invalid_api_prompt') from None
    if not isinstance(prompt, str) or not prompt.strip():
        raise APIError('invalid_api_prompt')
    try:
        if len(prompt.encode('utf-8')) > MAX_BODY // 2:
            raise APIError('api_prompt_too_large')
    except UnicodeError:
        raise APIError('invalid_api_prompt') from None
    headers = _headers(service)
    if service == 'anthropic':
        path = prefix + '/messages'
        body = {'model': model, 'messages': [{'role': 'user', 'content': prompt}],
                'max_tokens': max_output_tokens, 'stream': False}
    elif service == 'gemini':
        path = prefix + '/models/' + quote(model, safe='') + ':generateContent'
        body = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                'generationConfig': {'maxOutputTokens': max_output_tokens, 'candidateCount': 1}}
    else:
        path = prefix + '/chat/completions'
        limit = 'max_completion_tokens' if service in {'openai', 'kimi'} else 'max_tokens'
        body = {'model': model, 'messages': [{'role': 'user', 'content': prompt}],
                limit: max_output_tokens, 'stream': False}
        if service in {'openai', 'xai', 'deepseek', 'kimi', 'openrouter'}:
            body['tool_choice'] = 'none'
        if service in {'openai', 'openrouter'}:
            body['n'] = 1
        if service == 'openrouter':
            body['usage'] = {'include': True}
            body['provider'] = {'allow_fallbacks': False, 'require_parameters': True}
    encoded = json.dumps(body, ensure_ascii=True, separators=(',', ':'), sort_keys=True).encode()
    validate_request(origin, path, 'POST', headers, encoded, 120)
    digest = hashlib.sha256(service.encode() + b'\0' + path.encode() + b'\0' + encoded).hexdigest()
    return PreparedRequest(service, model, max_output_tokens, digest, origin, path, headers, encoded)


def _count(value):
    if type(value) is not int or not 0 <= value <= 10 ** 12:
        raise APIError('invalid_api_usage')
    return value


def _decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise APIError('invalid_api_cost')
    try:
        number = Decimal(value)
        if not number.is_finite() or number < 0 or number > MAX_MONEY_TICKS:
            raise APIError('invalid_api_cost')
        return number
    except (InvalidOperation, OverflowError):
        raise APIError('invalid_api_cost') from None


def cost_ticks(service, usage):
    if not isinstance(usage, dict):
        return None
    value = usage.get('cost_in_usd_ticks') if service == 'xai' else usage.get('cost') if service == 'openrouter' else None
    if value is None:
        return None
    amount = _decimal(value)
    if len(amount.as_tuple().digits) > 256:
        raise APIError('invalid_api_cost')
    if service == 'openrouter':
        sign, digits, exponent = amount.as_tuple()
        amount = Decimal((sign, digits, exponent + 10))
    if amount > MAX_MONEY_TICKS:
        raise APIError('invalid_api_cost')
    return int(amount.to_integral_value(rounding=ROUND_CEILING))


def _details(usage, key, allowed):
    value = usage.get(key, {})
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise APIError('unknown_api_usage_class')
    for count in value.values():
        _count(count)
    return value


def normalize_usage(service, data):
    """Return disjoint billable token classes; never sum overlapping reasoning."""
    usage = data.get('usageMetadata' if service == 'gemini' else 'usage')
    if not isinstance(usage, dict):
        raise APIError('missing_api_usage')
    result = {}
    if service == 'openai' and data.get('service_tier') not in (None, 'default'):
        raise APIError('unknown_api_usage_class')
    if service == 'anthropic':
        allowed = {'input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens',
                   'cache_creation', 'server_tool_use', 'service_tier', 'inference_geo'}
        if set(usage) - allowed:
            raise APIError('unknown_api_usage_class')
        tools = usage.get('server_tool_use')
        if tools is not None:
            if (not isinstance(tools, dict) or set(tools) - {'web_search_requests', 'web_fetch_requests'}
                    or any(_count(value) != 0 for value in tools.values())):
                raise APIError('unexpected_api_tools')
        if usage.get('service_tier') not in (None, 'standard'):
            raise APIError('unknown_api_usage_class')
        result = {'input_tokens': _count(usage.get('input_tokens')),
                  'output_tokens': _count(usage.get('output_tokens')),
                  'cache_read_tokens': _count(usage.get('cache_read_input_tokens', 0))}
        writes = _count(usage.get('cache_creation_input_tokens', 0))
        if usage.get('cache_creation') is not None:
            details = _details(usage, 'cache_creation', {'ephemeral_5m_input_tokens', 'ephemeral_1h_input_tokens'})
            short = details.get('ephemeral_5m_input_tokens', 0)
            long = details.get('ephemeral_1h_input_tokens', 0)
            if short + long != writes:
                raise APIError('invalid_api_usage')
            result.update(cache_write_5m_tokens=short, cache_write_1h_tokens=long)
        elif writes:
            result['cache_write_tokens'] = writes
    elif service == 'gemini':
        allowed = {'promptTokenCount', 'candidatesTokenCount', 'totalTokenCount', 'cachedContentTokenCount',
                   'thoughtsTokenCount', 'toolUsePromptTokenCount', 'promptTokensDetails',
                   'cacheTokensDetails', 'candidatesTokensDetails', 'toolUsePromptTokensDetails',
                   'trafficType'}
        if set(usage) - allowed or usage.get('toolUsePromptTokenCount', 0) != 0:
            raise APIError('unknown_api_usage_class')
        for key in ('promptTokensDetails', 'cacheTokensDetails', 'candidatesTokensDetails', 'toolUsePromptTokensDetails'):
            for row in usage.get(key, []):
                if not isinstance(row, dict) or row.get('modality') != 'TEXT':
                    raise APIError('unknown_api_usage_class')
                _count(row.get('tokenCount'))
        prompt = _count(usage.get('promptTokenCount'))
        cache = _count(usage.get('cachedContentTokenCount', 0))
        output = _count(usage.get('candidatesTokenCount', 0))
        thoughts = _count(usage.get('thoughtsTokenCount', 0))
        total = _count(usage.get('totalTokenCount'))
        if cache > prompt or total != prompt + output + thoughts:
            raise APIError('invalid_api_usage')
        result = {'input_tokens': prompt - cache, 'cache_read_tokens': cache,
                  'output_tokens': output, 'reasoning_tokens': thoughts}
    else:
        allowed = {'prompt_tokens', 'completion_tokens', 'total_tokens', 'prompt_tokens_details',
                   'completion_tokens_details', 'prompt_cache_hit_tokens', 'prompt_cache_miss_tokens',
                   'cost', 'cost_in_usd_ticks', 'cost_details', 'is_byok'}
        if set(usage) - allowed:
            raise APIError('unknown_api_usage_class')
        prompt = _count(usage.get('prompt_tokens'))
        output = _count(usage.get('completion_tokens'))
        if _count(usage.get('total_tokens')) != prompt + output:
            raise APIError('invalid_api_usage')
        details = _details(usage, 'prompt_tokens_details', {'cached_tokens', 'cache_write_tokens', 'audio_tokens'})
        completion = _details(usage, 'completion_tokens_details',
                              {'reasoning_tokens', 'audio_tokens', 'accepted_prediction_tokens', 'rejected_prediction_tokens'})
        if details.get('audio_tokens', 0) or any(completion.get(k, 0) for k in
                    ('audio_tokens', 'accepted_prediction_tokens', 'rejected_prediction_tokens')):
            raise APIError('unknown_api_usage_class')
        if completion.get('reasoning_tokens', 0) > output:
            raise APIError('invalid_api_usage')
        cache = _count(usage.get('prompt_cache_hit_tokens', details.get('cached_tokens', 0)))
        writes = details.get('cache_write_tokens', 0)
        if ('prompt_cache_hit_tokens' in usage and 'cached_tokens' in details
                and usage['prompt_cache_hit_tokens'] != details['cached_tokens']):
            raise APIError('invalid_api_usage')
        if cache + writes > prompt or ('prompt_cache_miss_tokens' in usage
                and _count(usage['prompt_cache_miss_tokens']) + cache != prompt):
            raise APIError('invalid_api_usage')
        result = {'input_tokens': prompt - cache - writes, 'cache_read_tokens': cache,
                  'output_tokens': output}
        if writes:
            result['cache_write_tokens'] = writes
    return result


def _text_result(service, data):
    if service == 'anthropic':
        if data.get('type') != 'message' or data.get('role') != 'assistant':
            raise APIError('unexpected_api_content')
        blocks = data.get('content')
        if not isinstance(blocks, list) or not blocks:
            raise APIError('unexpected_api_content')
        texts = []
        for block in blocks:
            if not isinstance(block, dict) or block.get('type') != 'text' or not isinstance(block.get('text'), str):
                raise APIError('unexpected_api_content')
            texts.append(block['text'])
        return ''.join(texts), data.get('model'), data.get('id'), data.get('stop_reason')
    if service == 'gemini':
        candidates = data.get('candidates')
        if not isinstance(candidates, list) or len(candidates) != 1:
            raise APIError('unexpected_api_content')
        candidate = candidates[0]
        content = candidate.get('content', {})
        if content.get('role') != 'model' or not isinstance(content.get('parts'), list):
            raise APIError('unexpected_api_content')
        text = []
        for part in content['parts']:
            if not isinstance(part, dict) or set(part) - {'text', 'thought', 'thoughtSignature'} or not isinstance(part.get('text'), str):
                raise APIError('unexpected_api_content')
            if not part.get('thought', False):
                text.append(part['text'])
        return ''.join(text), data.get('modelVersion'), data.get('responseId'), candidate.get('finishReason')
    choices = data.get('choices')
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise APIError('unexpected_api_content')
    choice = choices[0]
    message = choice.get('message')
    if (not isinstance(message, dict) or message.get('role') != 'assistant'
            or message.get('tool_calls') or message.get('function_call')
            or not isinstance(message.get('content'), str)):
        raise APIError('unexpected_api_content')
    return message['content'], data.get('model'), data.get('id'), choice.get('finish_reason')


def normalize_response(service, data):
    if not isinstance(data, dict) or 'error' in data:
        raise APIError('invalid_api_response')
    actual = cost_ticks(service, data.get('usage'))
    result = {'text': None, 'model': None, 'response_id': None, 'usage': {},
              'usage_complete': False, 'actual_cost_ticks': actual, 'currency': 'USD',
              'cost_evidence': ('usage.cost_in_usd_ticks' if service == 'xai' else 'usage.cost') if actual is not None else None,
              'output_valid': False, 'status': 'unexpected_api_content', 'inference_verified': False}
    try:
        result['usage'] = normalize_usage(service, data)
        result['usage_complete'] = True
    except (APIError, TypeError, AttributeError):
        pass
    try:
        text, model, response_id, reason = _text_result(service, data)
        if not text.strip() or len(text.encode()) > MAX_BODY or not isinstance(reason, str):
            raise APIError('unexpected_api_content')
        if reason not in {'stop', 'length', 'end_turn', 'max_tokens', 'stop_sequence', 'STOP', 'MAX_TOKENS'}:
            raise APIError('unexpected_api_content')
        if not isinstance(response_id, str) or not re.fullmatch(r'[A-Za-z0-9._:/+=-]{1,256}', response_id):
            raise APIError('unexpected_api_content')
        result.update(text=text, model=_model(model), response_id=response_id,
                      output_valid=True, status='completed', inference_verified=True,
                      truncated=reason in {'length', 'max_tokens', 'MAX_TOKENS'})
    except (APIError, TypeError, AttributeError, UnicodeError):
        pass
    return result


def execute(prepared, timeout=120, *, admission=None):
    """Accept a single-use admission from the budgeted request coordinator."""
    from api_execution import _Admission
    if type(admission) is not _Admission:
        raise APIError('monetary_admission_required')
    if not isinstance(prepared, PreparedRequest):
        raise APIError('invalid_prepared_request')
    admission.claim(prepared)
    data = request_json(prepared.origin, prepared.path, 'POST', headers=prepared.headers,
                        body=prepared.body, timeout=timeout)
    return normalize_response(prepared.service, data)


def generate(service, model, prompt, max_output_tokens, effort=None, *, timeout=120):
    raise APIError('use_budgeted_api_execution')


def models(service, *, timeout=15):
    origin, prefix, _ = _service(service)
    base = {'service': service, 'models': [], 'inference_verified': False,
            'entitlement_verified': False, 'status': 'catalog_unavailable'}
    if service == 'zai':
        return base
    headers, seen, cursor, rows = _headers(service), set(), None, []
    deadline = time.monotonic() + timeout
    for _ in range(20):
        query = {}
        if service == 'anthropic':
            query = {'limit': 100}
            if cursor:
                query['after_id'] = cursor
        if service == 'gemini':
            query = {'pageSize': 100}
            if cursor:
                query['pageToken'] = cursor
        path = prefix + '/models' + ('?' + urlencode(query) if query else '')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise APIError('api_timeout')
        data = request_json(origin, path, headers=headers, timeout=remaining)
        if service == 'anthropic' and type(data.get('has_more')) is not bool:
            raise APIError('invalid_api_catalog')
        page = data.get('models' if service == 'gemini' else 'data')
        if not isinstance(page, list):
            raise APIError('invalid_api_catalog')
        for row in page:
            if not isinstance(row, dict):
                raise APIError('invalid_api_catalog')
            ident = _model(row.get('name' if service == 'gemini' else 'id'))
            if service == 'gemini' and ident.startswith('models/'):
                ident = ident[7:]
            if ident in seen:
                raise APIError('invalid_api_catalog')
            seen.add(ident)
            item = {'id': ident, 'service': service, 'account_visible': True if service == 'xai' else None,
                    'entitlement_verified': False, 'inference_verified': False,
                    'evidence': {'kind': 'authenticated_catalog', 'source': prefix + '/models'}}
            for key in ('context_length', 'inputTokenLimit', 'outputTokenLimit'):
                if key in row:
                    item[key] = _count(row[key])
            if service == 'gemini':
                methods = row.get('supportedGenerationMethods')
                if not isinstance(methods, list):
                    raise APIError('invalid_api_catalog')
                item['text_generation_supported'] = 'generateContent' in methods
            rows.append(item)
            if len(rows) > 2000:
                raise APIError('api_catalog_too_large')
        next_cursor = data.get('nextPageToken') if service == 'gemini' else data.get('last_id') if service == 'anthropic' and data.get('has_more') is True else None
        if not next_cursor:
            return dict(base, models=rows, status='catalog_metadata')
        if (not isinstance(next_cursor, str) or len(next_cursor) > 1000
                or next_cursor == cursor or not next_cursor.isascii()
                or re.search(r'[\x00-\x20\x7f]', next_cursor)):
            raise APIError('invalid_api_catalog')
        cursor = next_cursor
    raise APIError('api_catalog_too_large')
