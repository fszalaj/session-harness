"""Legacy pool migration retains usage and rejects missing unit evidence."""
import json
from pathlib import Path
import tempfile
import time
import unittest

import copilot_migration
from quota import Ledger


class MigrationTests(unittest.TestCase):
    def test_migration_retains_history_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory)/'ledger.db')
            now=time.time()
            ledger.record({'service':'copilot','source':'copilot.account.getQuota','observed_at':now,'complete':True,
                           'pools':[{'pool':'chat','used_percent':5,'resets_at':now+86400},
                                    {'pool':'premium_interactions','used_percent':100,'resets_at':now+86400}]},initialize=True)
            ledger.record({'service':'copilot','source':'copilot.account.getQuota','observed_at':now+1,'complete':True,
                           'pools':[{'pool':'chat','used_percent':8,'resets_at':now+86400},
                                    {'pool':'premium_interactions','used_percent':100,'resets_at':now+86400}]},now=now+1)
            data={'authenticated':True,'quota_complete':True,'quota':[
                {'pool':'chat','hasQuota':True,'tokenBasedBilling':True},
                {'pool':'premium_interactions','hasQuota':False,'tokenBasedBilling':True}]}
            with ledger._connect() as db:
                original = ledger._service(db, 'copilot')
                overlapping = json.loads(json.dumps(original))
                overlapping['pools']['chat:token_billing'] = dict(overlapping['pools']['chat'])
                overlapping['days'][ledger._day(now)]['chat:token_billing'] = dict(consumed=1, unknown=False, history_partial=True)
                db.execute('UPDATE state SET value=? WHERE key=?', (json.dumps(overlapping), 'service:copilot'))
            with self.assertRaisesRegex(ValueError, 'Overlapping'):
                copilot_migration.migrate(ledger,data)
            with ledger._connect() as db:
                self.assertEqual(ledger._service(db, 'copilot'), overlapping)
                db.execute('UPDATE state SET value=? WHERE key=?', (json.dumps(original), 'service:copilot'))
            copilot_migration.migrate(ledger,data)
            copilot_migration.migrate(ledger,data)
            with ledger._connect() as db:
                state=ledger._service(db,'copilot')
                archive=json.loads(db.execute("SELECT value FROM state WHERE key='migration:copilot-billing-v1'").fetchone()[0])
            self.assertEqual(set(state['pools']),{'chat:token_billing'})
            self.assertEqual(state['days'][ledger._day(now)]['chat:token_billing']['consumed'],3)
            self.assertEqual(archive['days'][ledger._day(now)]['chat']['consumed'],3)
            self.assertNotIn('chat', state['days'][ledger._day(now)])
            self.assertIn('premium_interactions', state['days'][ledger._day(now)])
            with self.assertRaises(ValueError): copilot_migration.migrate(ledger,{'authenticated':False})


if __name__ == '__main__': unittest.main()
