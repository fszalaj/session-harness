"""Select an admitted current Claude model without changing billing services."""
import copy

import model_scope


def candidates(capability, role):
    import harness
    primary = capability.get(role)
    if not primary or model_scope.tier(primary.get('model')) is None:
        return []
    result = [copy.deepcopy(primary)]
    major = harness.generation(primary['model'], 'claude')[0]
    models = {}
    for row in capability.get('models', []):
        ident = row.get('resolved_model', row.get('id'))
        if row.get('account_selectable') is not True or model_scope.tier(ident) is None:
            continue
        if harness.generation(ident, 'claude')[0] != major:
            continue
        efforts = row.get('efforts', row.get('native_controls', {}).get('reasoning_efforts', []))
        models[ident] = [e for e in models[ident] if e in efforts] if ident in models else list(efforts)
    tiers = ('opus',) if role == 'planner' else ('sonnet', 'opus')
    for tier in tiers:
        available = [m for m in models if model_scope.tier(m) == tier]
        if not available:
            continue
        ident = max(available, key=lambda m: (harness.generation(m, 'claude'), m))
        if ident == primary['model']:
            continue
        try:
            effort = harness.select_effort(models[ident], role)
        except harness.HarnessError:
            continue
        result.append(dict(model=ident, effort=effort,
                           basis='Current account-visible alternative after a model-specific quota stop.'))
    return result


def choose(capability, role, *, check=None, excluded=()):
    import coordination
    import supervision
    check = check or (lambda model: coordination.dispatch('check', 'claude', 'model-preflight', models=[model]))
    last = None
    for choice in candidates(capability, role):
        if choice['model'] in excluded:
            continue
        receipt = check(choice['model'])
        if (receipt.get('model_admission_version') != 1 or receipt.get('models') != [choice['model']]):
            raise supervision.Stop('claude', ['quota_admission_denied'])
        if receipt.get('allowed') is True:
            return choice, receipt
        last = supervision.Stop('claude', receipt.get('reasons', []), receipt=receipt)
        if not model_scope.scope_only_denial(receipt):
            raise last
    raise last or supervision.Stop('claude', ['quota_admission_denied'])


def worker_check(ledger, receipt):
    import harness
    import supervision
    if not model_scope.scope_only_denial(receipt, require_model=False):
        return receipt
    capability = harness.discover_provider('claude')
    try:
        choice, result = choose(capability, 'worker', check=lambda model: ledger.check('claude', models=[model]))
        result['worker_model'] = choice['model']
        return result
    except supervision.Stop:
        return receipt
