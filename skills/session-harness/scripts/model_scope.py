"""Explicit native model scopes; unknown identities retain every quota gate."""
from datetime import date
import re

TIERS = ('fable', 'opus', 'sonnet', 'haiku')
SOURCE = 'claude.native_limit_scope'
OBSERVATION_SOURCE = 'claude.native_backend_refresh'
RESOURCE_REASONS = {'daily_limit', 'native_growth_limit', 'reserve_floor'}
LABELS = {label: tier for tier in TIERS for label in (tier.title(), 'Claude ' + tier.title())}


def tier(model):
    if not isinstance(model, str) or len(model) > 128:
        return None
    match = re.fullmatch(r'claude-(fable|opus|sonnet|haiku)-([0-9]+(?:[-.][0-9]+)*)(?:\[1m\])?', model)
    if not match:
        return None
    parts = re.split(r'[-.]', match[2])
    if len(parts[-1]) == 8:
        if len(parts) < 2:
            return None
        stamp = parts.pop()
        try:
            date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:]))
        except ValueError:
            return None
    if not parts or any(len(part) > 3 for part in parts) or int(parts[0]) == 0:
        return None
    return match[1]


def native_scope(model):
    if not isinstance(model, dict) or set(model) != {'id', 'display_name'}:
        return None
    label = model['display_name']
    named = LABELS.get(label) if isinstance(label, str) else None
    if named is None or (model['id'] is not None and tier(model['id']) != named):
        return None
    return dict(version=1, family='anthropic', tiers=[named], source=SOURCE)


def validate_scope(scope, service, source):
    if (not isinstance(scope, dict) or set(scope) != {'version', 'family', 'tiers', 'source'}
            or type(scope['version']) is not int or scope['version'] != 1
            or scope['family'] != 'anthropic' or scope['source'] != SOURCE
            or service != 'claude' or source != OBSERVATION_SOURCE
            or not isinstance(scope['tiers'], list) or not 1 <= len(scope['tiers']) <= len(TIERS)
            or any(not isinstance(t, str) or t not in TIERS for t in scope['tiers'])
            or len(set(scope['tiers'])) != len(scope['tiers'])):
        raise ValueError('invalid native model scope')
    return scope


def validate_models(models, service):
    if models is None:
        return None
    if (service != 'claude' or not isinstance(models, list) or not 1 <= len(models) <= 16
            or any(tier(m) is None for m in models) or len(set(models)) != len(models)):
        raise ValueError('invalid concrete admission models')
    return models


def applicable(scope, models):
    if scope is None or models is None:
        return True
    validate_scope(scope, 'claude', OBSERVATION_SOURCE)
    validate_models(models, 'claude')
    return any(tier(model) in scope['tiers'] for model in models)


def scope_only_denial(result, *, require_model=True):
    """Only a positive complete receipt can authorize another same-service model."""
    if (not isinstance(result, dict) or result.get('allowed') is not False
            or (require_model and result.get('model_admission_version') != 1) or not result.get('pools')
            or not result.get('reasons')):
        return False
    permitted = set()
    for pool in result['pools']:
        if pool.get('model_scope') and pool.get('applicable') is True:
            permitted.update(pool['pool'] + ':' + r for r in pool.get('reasons', []) if r in RESOURCE_REASONS)
    return bool(permitted) and set(result['reasons']).issubset(permitted)
