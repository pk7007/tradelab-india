import json
import sqlite3
import unittest
from unittest.mock import patch

import entry_gate
import lineage_store
from paper import PaperEngine
from test_auto_selector import SelectionTests

BLOCK = dict(allowed=False, reasons=['required evidence failed (test)'], lineage=[])


class LineageIntegrationTests(unittest.TestCase):
    setUp = SelectionTests.setUp
    start = SelectionTests.start
    advance = SelectionTests.advance

    def test_entry_writes_durable_lineage_with_times_and_gate_result(self):
        self.start()
        self.selector.tick()
        self.selector.tick()
        self.advance(10)
        identity = self.selector.worker.account
        with self.engine.db() as db:
            rows = db.execute('SELECT domain,source,observed_at,available_at,input_hash,revision,state '
                              'FROM lineage_tasks ORDER BY seq').fetchall()
            self.assertGreaterEqual(len(rows), 5)
            for row in rows:
                self.assertTrue(row['available_at'] and row['input_hash'] and row['source'] and row['observed_at'])
                self.assertEqual(row['revision'], 1)
            review = json.loads(db.execute("SELECT body FROM entry_reviews WHERE state='consumed' AND account=?",
                                           (identity,)).fetchone()[0])
            self.assertTrue(review['lineage']['allowed'])
            self.assertEqual(review['lineage']['lineage'][-1], review['handoffs']['finalTaskId'])
        self.assertGreater(self.engine.reconcile(identity)['quantity'], 0)

    def test_failed_lineage_blocks_new_entry(self):
        self.start()
        with patch.object(entry_gate, 'check_entry', return_value=BLOCK):
            self.selector.tick()
            self.selector.tick()
            self.advance(10)
        identity = self.selector.worker.account
        self.assertEqual(self.engine.reconcile(identity)['quantity'], 0)
        with self.engine.db() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM entry_reviews WHERE state='consumed'").fetchone())
            rejected = db.execute("SELECT body FROM entry_reviews WHERE state='rejected'").fetchall()
            self.assertTrue(any('Lineage gate' in row[0] for row in rejected))

    def test_lineage_failure_never_blocks_protective_exit_or_reconciliation(self):
        self.start()
        self.selector.tick()
        self.selector.tick()
        self.advance(10)
        identity = self.selector.worker.account
        self.assertGreater(self.engine.reconcile(identity)['quantity'], 0)
        self.rows[23] = dict(self.rows[23], low=90)  # crosses the stop
        with patch.object(lineage_store, 'record_handoffs', side_effect=sqlite3.OperationalError('lineage store down')):
            self.advance(5)
        with self.engine.db() as db:
            self.assertEqual(self.engine.load(db, identity)['quantity'], 0)
        self.assertTrue(self.engine.reconcile(identity)['matches'])

    def test_real_store_failure_blocks_new_entry_and_says_why(self):
        self.start()
        with patch.object(lineage_store, 'record_handoffs', side_effect=sqlite3.OperationalError('disk')):
            self.selector.tick()
            self.selector.tick()
            self.advance(10)
        identity = self.selector.worker.account
        self.assertEqual(self.engine.reconcile(identity)['quantity'], 0)
        with self.engine.db() as db:
            bodies = [row[0] for row in db.execute("SELECT body FROM entry_reviews WHERE state='rejected'")]
        self.assertTrue(any('Lineage store unavailable (OperationalError)' in body for body in bodies))

    def test_failed_handoff_is_stored_as_a_defect_and_no_entry_opens(self):
        self.start()
        from agent_handlers import execute

        def handler(capability, payload):
            if capability.startswith('technical-indicators'):
                raise RuntimeError('handler down')
            return execute(capability, payload)
        self.engine.workflow_handler = handler
        self.selector.tick()
        self.selector.tick()
        self.advance(10)
        identity = self.selector.worker.account
        self.assertEqual(self.engine.reconcile(identity)['quantity'], 0)
        with self.engine.db() as db:
            states = {row['domain']: row['state'] for row in db.execute(
                'SELECT domain,state FROM lineage_tasks WHERE revision=1')}
        self.assertEqual(states.get('technical-indicators'), 'failed')
        self.assertEqual(states.get('instrument-reference'), 'reviewed')

    def test_restart_keeps_lineage_and_is_idempotent(self):
        self.start()
        self.selector.tick()
        self.selector.tick()
        self.advance(10)
        with self.engine.db() as db:
            before = db.execute('SELECT COUNT(*) FROM lineage_tasks').fetchone()[0]
            tasks = [json.loads(row[0])['handoffs']['tasks'] for row in db.execute('SELECT body FROM entry_reviews')]
        restarted = PaperEngine(self.engine.path)
        with restarted.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lineage_tasks').fetchone()[0], before)
            lineage_store.record_handoffs(db, dict(tasks=tasks[0]), now='2026-01-02T12:00:00+05:30')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lineage_tasks').fetchone()[0], before)


del SelectionTests  # keep unittest discovery from re-running the borrowed fixture's own tests

if __name__ == '__main__':
    unittest.main()
