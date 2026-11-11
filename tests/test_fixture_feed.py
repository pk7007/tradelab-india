import json
import tempfile
import unittest
from pathlib import Path
from paper import PaperEngine
from test_paper import CONFIG
from test_trader_suite import bars

class FixtureBoundaryTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.engine=PaperEngine(Path(folder.name)/'test.sqlite')
        self.id=self.engine.create(CONFIG)['id']
        self.instrument=self.engine.fixture_link(self.id,True)['instrument']
        self.engine.control(self.id,'start')

    def test_wrong_instrument_or_raw_import_cannot_fill(self):
        with self.assertRaises(ValueError):self.engine.fixture_batch(self.id,'OTHER',bars(),True)
        with self.assertRaises(ValueError):self.engine.ingest(self.id,bars(),True)
        self.assertEqual(self.engine.reconcile(self.id)['fills'],0)

    def test_rebuild_detects_drift_and_blocks_another_fill(self):
        self.engine.fixture_batch(self.id,self.instrument,bars()[:20],True)
        with self.engine.db() as db:
            s=self.engine.load(db,self.id);s['cash']+=1
            db.execute('UPDATE accounts SET body=? WHERE id=?',(json.dumps(s),self.id))
        self.assertFalse(self.engine.reconcile(self.id)['matches'])
        with self.assertRaisesRegex(ValueError,'ledger mismatch'):
            self.engine.fixture_batch(self.id,self.instrument,bars()[20:21],True)
        self.assertEqual(self.engine.reconcile(self.id)['fills'],0)

    def test_receipt_unique_and_permission_required(self):
        batch=bars()[:21]
        with self.assertRaises(ValueError):self.engine.fixture_batch(self.id,self.instrument,batch,False)
        self.engine.fixture_batch(self.id,self.instrument,batch,True)
        self.engine.fixture_batch(self.id,self.instrument,batch,True)
        with self.engine.db() as db:
            receipts=db.execute('SELECT * FROM receipts WHERE account=?',(self.id,)).fetchall()
        self.assertEqual(len(receipts),21)
        self.assertTrue(all(r['received'] and r['instrument']==self.instrument for r in receipts))
        self.assertTrue(self.engine.reconcile(self.id)['matches'])
