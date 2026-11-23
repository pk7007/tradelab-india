from pathlib import Path
import tempfile
import time
import unittest

from agent_catalog import DOMAINS, RESPONSIBILITIES
from agent_handlers import NUMERIC_FIELDS, evidence_task
from agent_service import AgentService
from research import timestamp


def sample(domain):
    row = {key: 10 if key in NUMERIC_FIELDS else 'fixture' for key in DOMAINS[domain]}
    row.update(id='observation-1', source='fixture:domain-acceptance-v1',
               observedAt='2026-01-02T10:00:00+05:30', availableAt='2026-01-02T10:00:00+05:30')
    if domain == 'exchange-calendar':
        row.update(open='2026-01-02T09:15:00+05:30', close='2026-01-02T15:30:00+05:30')
    if domain == 'recovery-persistence':
        row['restoreVerified'] = True
    if domain == 'paper-execution':
        row['side'] = 'BUY'
    return row


class DomainAcceptanceTests(unittest.TestCase):
    def test_all_512_roles_have_working_domain_fixture_and_reject_future(self):
        cutoff = timestamp('2026-01-02T12:00:00+05:30')
        count = 0
        for domain in DOMAINS:
            row = sample(domain)
            payload = dict(permitted=True, records=[row], maxAgeSeconds=3600, baseline=[row])
            subject = evidence_task(domain+'.analysis', payload, cutoff)
            payload['subject'] = dict(capability=domain+'.analysis', output=subject)
            for responsibility in RESPONSIBILITIES:
                with self.subTest(domain=domain, responsibility=responsibility):
                    output = evidence_task(domain+'.'+responsibility, payload, cutoff)
                    self.assertFalse(output['executionAllowed'])
                    self.assertEqual(output['domain'], domain)
                    self.assertEqual(output['uniqueRecords'], 1)
                    future = dict(payload, records=[dict(row, availableAt='2026-01-03T00:00:00+05:30')])
                    with self.assertRaises(ValueError):
                        evidence_task(domain+'.'+responsibility, future, cutoff)
                    count += 1
        self.assertEqual(count, 512)


class RuntimeAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = AgentService(Path(self.temp.name)/'queue.sqlite')
        self.addCleanup(self.service.stop)

    def task(self, key='one', dependencies=None):
        return dict(capability='trade-risk.feature-calculation',
                    input=dict(permitted=True, records=[sample('trade-risk')]),
                    evidenceCutoff='2026-01-02T12:00:00+05:30', priority=1,
                    deadlineSeconds=60, budgetSeconds=10, idempotencyKey=key,
                    dependencies=dependencies or [])

    def review(self, identity):
        self.service.review(identity, 'human:independent-fixture-reviewer',
                            dict(correctness=True, evidence=True, reproducibility=True,
                                 completeness=True, budget=True))

    def test_dependency_waits_for_accepted_parent(self):
        parent = self.service.enqueue(self.task())
        child = self.service.enqueue(self.task('child', [parent]))
        self.assertEqual(self.service.run_once(), parent)
        self.assertIsNone(self.service.run_once())
        self.review(parent)
        self.assertEqual(self.service.run_once(), child)

    def test_failed_evidence_quarantines_despite_high_other_marks(self):
        identity = self.service.enqueue(self.task())
        self.service.run_once()
        self.service.review(identity, 'human:reviewer',
                            dict(correctness=True, evidence=False, reproducibility=True,
                                 completeness=True, budget=True))
        status = self.service.status()
        self.assertEqual(status['tasks'][0]['state'], 'rejected')
        self.assertEqual(next(r for r in status['roles'] if r['id']=='trade-risk.feature-calculation')['state'], 'quarantined')

    def test_process_deadline_terminates_without_committing_result(self):
        identity = self.service.enqueue(self.task())
        claim = self.service._claim
        def tiny_budget():
            row, lease, _expires = claim()
            return row, lease, time.time()+.001
        self.service._claim = tiny_budget
        self.service.run_once()
        self.assertEqual(self.service.status()['tasks'][0]['state'], 'expired')

    def test_background_consumers_complete_queue_without_http_run(self):
        self.service.enqueue(self.task())
        self.service.start()
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            if self.service.status()['tasks'][0]['state'] == 'review':
                break
            time.sleep(.05)
        self.assertEqual(self.service.status()['tasks'][0]['state'], 'review')
        self.assertLessEqual(self.service.status()['workerThreadsAlive'], 4)

    def test_malformed_dependency_and_duplicate_inputs_rejected(self):
        with self.assertRaises(ValueError):
            self.service.enqueue(self.task(dependencies=['unknown']))
        self.service.enqueue(self.task())
        changed = self.task()
        changed['input']['records'][0]['quantity'] = 20
        with self.assertRaises(ValueError):
            self.service.enqueue(changed)
