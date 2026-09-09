"""Reviewed coding models intersected with fresh public OpenRouter metadata."""
import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from api_providers import _model
from api_transport import APIError, decode_json, request_json

DEFAULT_POLICY = Path(__file__).resolve().parent.parent / 'references' / 'coding-models.json'
ORIGIN = 'https://openrouter.ai'
CATALOG_PATH = '/api/v1/models'


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('invalid_coding_date')
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise ValueError('invalid_coding_date') from None


def load_policy(path=DEFAULT_POLICY):
    try:
        with Path(path).open('rb') as source:
            raw = source.read(65537)
        if len(raw) > 65536:
            raise ValueError('coding_policy_too_large')
        policy = decode_json(raw)
        if (set(policy) != {'schema_version', 'service', 'min_context_tokens', 'models'}
                or type(policy['schema_version']) is not int or policy['schema_version'] != 1
                or policy['service'] != 'openrouter'
                or type(policy['min_context_tokens']) is not int
                or not 65536 <= policy['min_context_tokens'] <= 2 ** 24
                or not isinstance(policy['models'], list) or not 1 <= len(policy['models']) <= 64):
            raise ValueError('invalid_coding_policy')
        seen = set()
        for row in policy['models']:
            if not isinstance(row, dict) or set(row) != {'id', 'family', 'publisher', 'reviewed_at', 'expires_at', 'evidence'}:
                raise ValueError('invalid_coding_policy')
            ident = _model(row['id'])
            if ident in seen or '/' not in ident or ident.split('/')[0] != row['publisher']:
                raise ValueError('invalid_coding_policy')
            seen.add(ident)
            if not isinstance(row['family'], str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,49}', row['family']):
                raise ValueError('invalid_coding_policy')
            reviewed, expires = _day(row['reviewed_at']), _day(row['expires_at'])
            if not 1 <= (expires - reviewed).days <= 90:
                raise ValueError('invalid_coding_policy')
            if not isinstance(row['evidence'], list) or not 1 <= len(row['evidence']) <= 8:
                raise ValueError('invalid_coding_policy')
            for item in row['evidence']:
                if (not isinstance(item, dict) or set(item) != {'kind', 'url', 'note'}
                        or item['kind'] not in {'vendor_report', 'benchmark_author'}
                        or not isinstance(item['note'], str) or not 1 <= len(item['note']) <= 700
                        or not isinstance(item['url'], str) or len(item['url']) > 1000):
                    raise ValueError('invalid_coding_policy')
                url = urlsplit(item['url'])
                if url.scheme != 'https' or not url.hostname or url.username or url.password:
                    raise ValueError('invalid_coding_policy')
        return policy, hashlib.sha256(raw).hexdigest()
    except (OSError, TypeError, KeyError, APIError):
        raise ValueError('invalid_coding_policy') from None


def _positive_int(value):
    if type(value) is not int or not 1 <= value <= 2 ** 24:
        raise ValueError('coding_capability_unknown')
    return value


def _price(value):
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
        raise ValueError('coding_price_unknown')
    try:
        number = Decimal(value)
        if not number.is_finite() or not 0 <= number <= 1000:
            raise ValueError('coding_price_unknown')
        return str(number)
    except InvalidOperation:
        raise ValueError('coding_price_unknown') from None


def catalog(path=DEFAULT_POLICY, *, now=None):
    policy, digest = load_policy(path)
    today = now or dt.datetime.now(dt.timezone.utc).date()
    checked_at = time.time()
    data = request_json(ORIGIN, CATALOG_PATH, headers={'Accept': 'application/json'}, timeout=20)
    if (not isinstance(data, dict) or 'error' in data or data.get('has_more')
            or data.get('nextPageToken') or data.get('next_cursor')
            or not isinstance(data.get('data'), list) or not 1 <= len(data['data']) <= 5000):
        raise ValueError('invalid_coding_catalog')
    live = {}
    for row in data['data']:
        ident = row.get('id') if isinstance(row, dict) else None
        if (not isinstance(ident, str) or not 1 <= len(ident) <= 300
                or re.search(r'[\x00-\x20\x7f]', ident) or ident in live):
            raise ValueError('invalid_coding_catalog')
        live[ident] = row
    eligible, excluded = [], []
    for entry in policy['models']:
        ident = entry['id']
        reasons = []
        if not _day(entry['reviewed_at']) <= today < _day(entry['expires_at']):
            reasons.append('coding_review_expired_or_future')
        row = live.get(ident)
        metadata = {}
        if row is None:
            reasons.append('coding_model_not_in_live_catalog')
        else:
            try:
                params = row.get('supported_parameters')
                if (not isinstance(params, list) or any(not isinstance(x, str) for x in params)
                        or not {'tools', 'tool_choice', 'max_tokens'}.issubset(params)):
                    raise ValueError('coding_tools_unverified')
                provider = row.get('top_provider')
                if not isinstance(provider, dict):
                    raise ValueError('coding_capability_unknown')
                context = min(_positive_int(row.get('context_length')),
                              _positive_int(provider.get('context_length')))
                output = min(_positive_int(provider.get('max_completion_tokens')), context)
                if context < policy['min_context_tokens']:
                    raise ValueError('coding_context_too_small')
                expiration = row.get('expiration_date')
                if expiration is not None and _day(expiration) <= today:
                    raise ValueError('coding_model_retired')
                pricing = row.get('pricing')
                if not isinstance(pricing, dict):
                    raise ValueError('coding_price_unknown')
                rates = {key: _price(pricing.get(key)) for key in ('prompt', 'completion')}
                metadata = {'context_tokens': context, 'max_output_tokens': output,
                            'catalog_usd_per_token': rates,
                            'catalog_price_is_spending_cap': False}
            except ValueError as exc:
                reasons.append(str(exc))
        if reasons:
            excluded.append({'id': ident, 'reasons': reasons})
        else:
            eligible.append(dict(entry, **metadata, billing_service='openrouter',
                                 account_access_verified=False, inference_verified=False,
                                 execution_role='supervised_text_worker'))
    return {'status': 'coding_catalog', 'service': 'openrouter', 'models': eligible,
            'excluded': excluded, 'policy_sha256': digest, 'checked_at': checked_at,
            'catalog_source': ORIGIN + CATALOG_PATH, 'catalog_kind': 'public_metadata',
            'execution_requires': ['api_setup', 'api_key', 'monthly_money_admission'],
            'quality_note': 'Reviewed coding evidence is not a common benchmark ranking or local acceptance.'}


def require_model(service, model, max_output_tokens, path=DEFAULT_POLICY):
    if service != 'openrouter':
        raise ValueError('unsupported_coding_service')
    result = catalog(path)
    row = next((row for row in result['models'] if row['id'] == model), None)
    if row is None:
        raise ValueError('coding_model_not_eligible')
    if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= row['max_output_tokens']:
        raise ValueError('coding_output_limit_exceeded')
    return {'policy_sha256': result['policy_sha256'], 'checked_at': result['checked_at'],
            'model_family': row['family'], 'billing_service': 'openrouter',
            'requested_model': model, 'requires_manager_inspection': True}
