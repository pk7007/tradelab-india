import datetime as dt
from email.utils import format_datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from agent_service import AgentService,registry
from dashboard_news import DashboardNews
from news_agent import NewsAgent
from worker_runtime import WorkerRuntime

class SupervisedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'agents.sqlite'
        self.service=AgentService(self.path)

    def task(self):
        return dict(capability='strategy-research.analysis',input=dict(permitted=True,candles={'DEMO':[]},asOf='2026-01-02T12:00:00+05:30'),evidenceCutoff='2026-01-02T12:00:00+05:30',priority=1,budgetSeconds=10,deadlineSeconds=60,idempotencyKey='one')

    def test_registry_and_persisted_idempotency(self):
        self.assertEqual(len({r['id'] for r in registry()}),108)
        identity=self.service.enqueue(self.task())
        other=AgentService(self.path)
        self.assertEqual(other.enqueue(self.task()),identity)
        changed=self.task();changed['input']['asOf']='2026-01-03T12:00:00+05:30'
        with self.assertRaises(ValueError):other.enqueue(changed)

    def test_route_review_and_quarantine_preserve_history(self):
        identity=self.service.enqueue(self.task());self.service.run_once()
        checks=dict(correctness=True,evidence=True,reproducibility=True,completeness=True,budget=True)
        self.service.review(identity,'human:reviewer',checks,critical=True)
        result=self.service.status()
        self.assertEqual(result['tasks'][0]['state'],'rejected')
        self.assertEqual(next(r for r in result['roles'] if r['id']=='strategy-research.analysis')['state'],'quarantined')
        second=self.task();second['idempotencyKey']='two';self.service.enqueue(second)
        self.assertIsNone(self.service.run_once())

    def test_cancel_cannot_be_replayed(self):
        identity=self.service.enqueue(self.task());self.service.cancel(identity)
        self.assertIsNone(self.service.run_once())
        self.assertEqual(self.service.status()['tasks'][0]['state'],'cancelled')

    def test_worker_status_fault_is_contained_and_latched(self):
        runtime=WorkerRuntime.__new__(WorkerRuntime);runtime.worker=Mock()
        runtime.worker.status.side_effect=OSError('private error')
        runtime.tick_once();runtime.tick_once()
        runtime.worker.status.assert_called_once()
        self.assertEqual(runtime.runtime_fault['errorType'],'OSError')
        self.assertNotIn('private error',str(runtime.runtime_fault))

    def test_snapshot_returns_after_restart_without_duplicate_notifications(self):
        now=dt.datetime.now(dt.timezone.utc)-dt.timedelta(seconds=5)
        raw=('<rss><channel><item><title>Fixture</title><link>https://economictimes.indiatimes.com/fixture</link><pubDate>'+format_datetime(now)+'</pubDate></item></channel></rss>').encode()
        path=Path(self.temp.name)/'news.sqlite'
        a=NewsAgent(path,sources=('et',),fetch=lambda _:raw)
        self.assertEqual(len(a.poll_once()['items']),1)
        b=NewsAgent(path,sources=('et',),fetch=lambda _:raw)
        result=b.poll_once();self.assertEqual(result['items'],[])
        self.assertEqual(len(result['currentItems']),1)
        self.assertEqual(len(DashboardNews(path,b).status()['items']),1)

    def test_retirement_cancels_queue_and_cannot_self_reactivate(self):
        identity=self.service.enqueue(self.task())
        self.service.lifecycle('strategy-research.analysis','retired','Operator retirement')
        self.assertEqual(self.service.status()['tasks'][0]['state'],'cancelled')
        with self.assertRaises(ValueError):self.service.lifecycle('strategy-research.analysis','active','Retry')
        self.assertIsNone(self.service.run_once())

    def test_unimplemented_role_cannot_be_enabled(self):
        with self.assertRaises(ValueError):self.service.lifecycle('fundamentals.analysis','active','Missing handler')

    def test_expired_task_abstains_and_keeps_history(self):
        identity=self.service.enqueue(self.task())
        with self.service.db() as db:db.execute('UPDATE tasks SET deadline=0 WHERE id=?',(identity,))
        self.assertIsNone(self.service.run_once())
        self.assertEqual(self.service.status()['tasks'][0]['state'],'expired')
