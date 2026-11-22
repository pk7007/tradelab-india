import json
import unittest

import test_auto_selector
from agent_handlers import execute
from session_evidence import SessionEvidence


class TradeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_auto_selector.SelectionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def start(self):
        self.fixture.start()
        self.fixture.selector.tick()
        self.fixture.selector.tick()

    def failed_post_review(self, identity):
        SessionEvidence(self.fixture.engine)
        with self.fixture.engine.db() as db:
            db.execute('INSERT INTO session_evidence_runs VALUES(?,?,?,?,?,?)',
                       ('failure', identity, 'trade-risk', 'quarantined', '{}', self.fixture.now.isoformat()))

    def test_required_stages_have_durable_parentage_and_consumed_approval_lineage(self):
        self.start()
        self.fixture.advance(10)
        identity = self.fixture.selector.worker.account
        with self.fixture.engine.db() as db:
            review = json.loads(db.execute("SELECT body FROM entry_reviews WHERE account=? AND state='consumed'", (identity,)).fetchone()[0])
            tasks = review['handoffs']['tasks']
            self.assertEqual(len(tasks), 5)
            self.assertTrue(all(task['state'] == 'reviewed' for task in tasks))
            self.assertEqual(tasks[0]['parents'], [])
            for previous, task in zip(tasks, tasks[1:]):
                self.assertEqual(task['parents'], [previous['taskId']])
                self.assertEqual(task['accountId'], identity)
                self.assertEqual(len(task['verdictHash']), 64)
            events = [json.loads(row[0]) for row in db.execute('SELECT body FROM events WHERE account=?', (identity,))]
        consumed = next(event for event in events if event['type'] == 'entry-review-consumed')
        self.assertEqual(consumed['parentTaskId'], tasks[-1]['taskId'])
        evidence = SessionEvidence(self.fixture.engine).observe(self.fixture.selector.status())
        execution = next(task for task in evidence['tasks'] if task['domain'] == 'paper-execution')
        self.assertIn(tasks[-1]['taskId'], execution['checks']['parentTaskIds'])

    def test_failed_role_review_blocks_downstream_entry_tasks(self):
        calls = []
        def handler(capability, envelope):
            calls.append(capability)
            if capability == 'technical-indicators.independent-review':
                raise ValueError('private-provider-message')
            return execute(capability, envelope)
        self.fixture.engine.workflow_handler = handler
        self.start()
        self.fixture.advance(10)
        identity = self.fixture.selector.worker.account
        self.assertEqual(self.fixture.engine.reconcile(identity)['quantity'], 0)
        self.assertNotIn('position-sizing.analysis', calls)
        with self.fixture.engine.db() as db:
            reviews = [json.loads(row[0]) for row in db.execute('SELECT body FROM entry_reviews WHERE account=?', (identity,))]
        self.assertTrue(all(review['handoffs']['state'] == 'blocked' for review in reviews))
        self.assertNotIn('private-provider-message', str(reviews))

    def test_failed_post_review_revokes_existing_pending_buy(self):
        self.start()
        self.fixture.advance(5)
        identity = self.fixture.selector.worker.account
        with self.fixture.engine.db() as db:
            self.assertEqual(self.fixture.engine.load(db, identity)['pending']['side'], 'BUY')
        self.failed_post_review(identity)
        self.fixture.advance(5)
        self.assertEqual(self.fixture.engine.reconcile(identity)['quantity'], 0)
        with self.fixture.engine.db() as db:
            self.assertIsNone(self.fixture.engine.load(db, identity)['pending'])
            self.assertTrue(db.execute("SELECT 1 FROM entry_reviews WHERE state='invalidated'").fetchone())

    def test_failed_post_review_preserves_protective_sell(self):
        self.start()
        self.fixture.advance(10)
        identity = self.fixture.selector.worker.account
        self.assertGreater(self.fixture.engine.reconcile(identity)['quantity'], 0)
        self.failed_post_review(identity)
        self.fixture.rows[23] = dict(self.fixture.rows[23], low=90)
        self.fixture.advance(5)
        result = self.fixture.engine.reconcile(identity)
        self.assertEqual(result['quantity'], 0)
        self.assertTrue(result['matches'])
