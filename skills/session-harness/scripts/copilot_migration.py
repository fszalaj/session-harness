"""Preserve legacy Copilot accounting while adopting verified billing pool IDs."""
import copy
import json


def migrate(ledger, data):
    if data.get('quota_complete') is not True or data.get('authenticated') is not True:
        raise ValueError('Fresh complete Copilot metadata is required')
    rows = {row['pool']: row for row in data['quota']}
    with ledger._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        state = ledger._service(db, 'copilot')
        if not state:
            return
        old_names = set(state['pools']) & {'chat', 'completions', 'premium_interactions'}
        if not old_names:
            return
        if state['source'] != 'copilot.account.getQuota' or not old_names <= rows.keys():
            raise ValueError('Unverified legacy Copilot pools')
        original, config = copy.deepcopy(state), ledger._budgets(db)
        for old in old_names:
            row = rows[old]
            if type(row.get('hasQuota')) is not bool or type(row.get('tokenBasedBilling')) is not bool:
                raise ValueError('Unverified legacy Copilot billing unit')
            previous = state['pools'].pop(old)
            if row['hasQuota']:
                new = old + (':token_billing' if row['tokenBasedBilling'] else ':requests')
                if new in state['pools'] and state['pools'][new]['observed_at'] < previous['observed_at']:
                    raise ValueError('Out-of-order Copilot aliases require reconciliation')
                state['pools'].setdefault(new, previous)
                for entries in state['days'].values():
                    if old not in entries:
                        continue
                    source = entries.pop(old)
                    target = entries.setdefault(new, dict(consumed=0, unknown=False, history_partial=True))
                    if source['consumed'] and target['consumed']:
                        raise ValueError('Overlapping Copilot alias consumption requires reconciliation')
                    target['consumed'] += source['consumed']
                    target['unknown'] |= source['unknown']
                    target['history_partial'] = True
                pools = config['services'].get('copilot', {}).get('pools', {})
                if old in pools:
                    if new in pools and pools[new] != pools[old]:
                        raise ValueError('Conflicting Copilot pool policy requires reconciliation')
                    pools[new] = pools.pop(old)
                for grant in config['grants']:
                    if grant['service'] == 'copilot' and old in grant['pools']:
                        if new in grant['pools']:
                            raise ValueError('Conflicting Copilot grants require reconciliation')
                        grant['pools'][new] = grant['pools'].pop(old)
        state['missing_pools'] = sorted(set(state['missing_pools']) - old_names)
        ledger._validate_accounting(state)
        db.execute('INSERT INTO state VALUES (?, ?)', ('migration:copilot-billing-v1', json.dumps(original)))
        db.execute('UPDATE state SET value=? WHERE key=?', (json.dumps(state), 'service:copilot'))
        ledger._save_budgets(db, config)
