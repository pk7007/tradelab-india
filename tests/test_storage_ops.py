from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest

from storage_ops import restore, snapshot, verify
from paper import PaperEngine
from test_intraday_paper import CONFIG, bars


class StorageTests(unittest.TestCase):
    def test_paper_restore_preserves_partial_exit_and_reconciles_without_changing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / 'paper.sqlite'
            engine = PaperEngine(source)
            account_id = engine.create(CONFIG)['id']
            engine.control(account_id, 'start')
            engine.ingest(account_id, bars(21), True)
            engine.control(account_id, 'close_position')
            partial = bars(22)[21]
            partial['volume'] = 20
            original = engine.ingest(account_id, [partial], True)['account']
            self.assertEqual(original['quantity'], 7)
            self.assertEqual(original['pending']['side'], 'SELL')
            source_status = engine.status()

            snapshot([source], base / 'backup')
            restored = restore(base / 'backup', base / 'restored')
            restored_path = base / 'restored' / restored['databases'][0]['file']
            recovered = PaperEngine(restored_path)
            with recovered.db() as db:
                account = recovered.load(db, account_id)
            self.assertEqual(account['status'], 'paused')
            for field in ('cash', 'quantity', 'fees', 'basis', 'realized', 'pending', 'protection'):
                self.assertEqual(account[field], original[field], field)
            self.assertTrue(recovered.reconcile(account_id)['matches'])
            # Restart alone cannot manufacture an exit. Future accepted liquidity
            # closes the remaining shares only in the isolated restored ledger.
            recovered.control(account_id, 'start')
            closed = recovered.ingest(account_id, bars(23)[22:], True)['account']
            self.assertEqual(closed['quantity'], 0)
            self.assertIsNone(closed['pending'])
            self.assertTrue(recovered.reconcile(account_id)['matches'])
            self.assertEqual(engine.status(), source_status)

    def test_restore_preserves_committed_state_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / 'paper.sqlite'
            with closing(sqlite3.connect(source)) as db, db:
                db.execute('CREATE TABLE shares(quantity INTEGER)')
                db.execute('INSERT INTO shares VALUES(7)')
            result = snapshot([source], base / 'backup')
            self.assertTrue(result['complete'])
            restored = restore(base / 'backup', base / 'restored')
            path = base / 'restored' / restored['databases'][0]['file']
            self.assertEqual(verify(path)['tables'], {'shares': 1})
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT quantity FROM shares').fetchone()[0], 7)
            with self.assertRaises(FileExistsError):
                restore(base / 'backup', base / 'restored')
            (base / 'backup' / result['databases'][0]['file']).write_bytes(b'broken')
            with self.assertRaises(ValueError):
                restore(base / 'backup', base / 'tampered')

    def test_failed_snapshot_cannot_be_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with self.assertRaises(FileNotFoundError):
                snapshot([base / 'missing.sqlite'], base / 'backup')
            with self.assertRaises(ValueError):
                restore(base / 'backup', base / 'restored')
