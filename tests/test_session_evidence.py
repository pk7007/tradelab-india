import json
import tempfile
import unittest
from pathlib import Path

from agent_handlers import execute
from paper import PaperEngine
from session_evidence import SessionEvidence
from test_intraday_paper import CONFIG, bars


class SessionEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.engine = PaperEngine(Path(temporary.name) / 'paper.sqlite')
        self.identity = self.engine.create(CONFIG)['id']
        self.service = SessionEvidence(self.engine)
        self.selection = dict(accountId=self.identity)

    def count_attempts(self):
        with self.engine.db() as db:
            return db.execute('SELECT COUNT(*) FROM session_evidence_attempts').fetchone()[0]

    def fill(self):
        self.engine.control(self.identity, 'start')
        self.engine.ingest(self.identity, bars(21), True)

    def test_registry_handlers_process_actual_fills_and_verify_descriptions(self):
        self.fill()
        before = self.engine.status()
        result = self.service.observe(self.selection)
        tasks = {task['domain']: task for task in result['tasks']}
        self.assertIn('paper-execution.analysis', result['rolesRun'])
        self.assertIn('trade-risk.independent-review', result['rolesRun'])
        self.assertFalse(result['executionAllowed'])
        self.assertTrue(all(task['review']['matches'] for task in tasks.values()))
        self.assertTrue(tasks['order-position-reconciliation']['checks']['matches'])
        self.assertTrue(tasks['position-sizing']['checks']['fills'][0]['fitsCashIncludingFees'])
        self.assertTrue(tasks['trade-risk']['checks']['fills'][0]['withinConfiguredTradeAllowance'])
        self.assertIn('News-to-signal validation', result['missingStages'])
        self.assertEqual(before, self.engine.status(), 'Evidence processing must never mutate account or orders.')
        cost = tasks['transaction-costs']['features']['features'][0]['totalModeledCost']
        self.assertGreater(cost, before['accounts'][0]['fees'], 'Price slippage is separately attributed.')

    def test_unchanged_evidence_reuses_durable_tasks_and_preserves_versions(self):
        self.fill()
        first = self.service.observe(self.selection)
        attempts = self.count_attempts()
        restarted = SessionEvidence(self.engine)
        self.assertEqual(restarted.observe(self.selection), first)
        self.assertEqual(self.count_attempts(), attempts)
        with self.engine.db() as db:
            history = list(db.execute('SELECT input_hash,attempt,body FROM session_evidence_attempts'))
        self.engine.ingest(self.identity, bars(22)[21:], True)
        self.service.observe(self.selection)
        self.assertGreater(self.count_attempts(), attempts)
        with self.engine.db() as db:
            for fingerprint, attempt, body in history:
                saved = db.execute('SELECT body FROM session_evidence_attempts WHERE input_hash=? AND attempt=?',
                                   (fingerprint, attempt)).fetchone()[0]
                self.assertEqual(saved, body)

    def test_failures_are_bounded_and_messages_are_not_persisted(self):
        def failing(*_):
            raise ValueError('secret-token-must-never-be-logged')
        service = SessionEvidence(self.engine, handler=failing)
        for _ in range(4):
            result = service.observe(self.selection)
        self.assertTrue(all(task['state'] == 'quarantined' for task in result['tasks']))
        self.assertTrue(all(task['attempt'] == 3 for task in result['tasks']))
        attempts = self.count_attempts()
        service.observe(self.selection)
        self.assertEqual(attempts, self.count_attempts())
        self.assertNotIn('secret-token', json.dumps(result))

    def test_review_rejects_changed_analysis_and_later_retry_preserves_failure(self):
        def changed(capability, envelope):
            output = execute(capability, envelope)
            if capability.endswith('.analysis'):
                output['numericSummary'] = {'fabricated': 1}
            return output
        failed = SessionEvidence(self.engine, handler=changed).observe(self.selection)
        self.assertTrue(all(task['state'] == 'retry-pending' for task in failed['tasks']))
        fixed = self.service.observe(self.selection)
        self.assertTrue(all(task['state'] == 'reviewed' and task['attempt'] == 2 for task in fixed['tasks']))
        with self.engine.db() as db:
            old = [json.loads(row[0]) for row in db.execute('SELECT body FROM session_evidence_attempts WHERE attempt=1')]
        self.assertTrue(all(row['state'] == 'retry-pending' for row in old))

    def test_ledger_failure_is_visible_even_when_description_review_matches(self):
        self.fill()
        with self.engine.db() as db:
            account = self.engine.load(db, self.identity)
            account['cash'] += 1
            self.engine.save(db, account, dict(type='test-corruption'))
        result = self.service.observe(self.selection)
        reconciliation = next(task for task in result['tasks'] if task['domain'] == 'order-position-reconciliation')
        self.assertTrue(reconciliation['review']['matches'])
        self.assertFalse(reconciliation['checks']['matches'])
        self.assertIn('cash', reconciliation['checks']['mismatches'])

    def test_no_account_does_not_fabricate_task_activity(self):
        result = self.service.observe({})
        self.assertEqual(result['rolesRun'], [])
        self.assertEqual(self.count_attempts(), 0)

    def test_real_worker_receipt_is_used_for_the_matching_completed_candle(self):
        self.fill()
        from paper_worker import PaperWorker
        PaperWorker(self.engine, lambda *_: [])
        received = '2026-01-02T11:00:01+05:30'
        with self.engine.db() as db:
            db.execute('INSERT INTO worker_receipts VALUES(?,?,?,?,?)',
                       (self.identity, bars(21)[-1]['date'], received, received, 'observed-candle-paper'))
        result = self.service.observe(self.selection)
        candle = next(task for task in result['tasks'] if task['domain'] == 'historical-candles')
        self.assertTrue(candle['checks']['receiptRecorded'])
        with self.engine.db() as db:
            payload = json.loads(db.execute('SELECT input FROM session_evidence_runs WHERE input_hash=?',
                                           (candle['inputHash'],)).fetchone()[0])
        self.assertEqual(payload['records'][0]['availableAt'], received)


if __name__ == '__main__':
    unittest.main()
