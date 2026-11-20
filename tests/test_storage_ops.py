from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest

from storage_ops import restore, snapshot, verify


class StorageTests(unittest.TestCase):
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
