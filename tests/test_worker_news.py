import datetime as dt
from types import SimpleNamespace
import unittest
import test_paper_worker
from worker_runtime import WorkerRuntime


class WorkerNewsTests(unittest.TestCase):
    setUp=test_paper_worker.WorkerTests.setUp
    state=test_paper_worker.WorkerTests.state
    def runtime(self,feed):
        service=SimpleNamespace(status=lambda instruments:feed)
        runtime=WorkerRuntime(self.engine,SimpleNamespace(master=[]),service)
        runtime.worker.clock=lambda:self.now
        runtime.worker.lease_seconds=300
        runtime.worker.start(self.account,self.instrument,self.calendar,True,True)
        return runtime

    def test_matching_context_has_no_order_authority(self):
        now=dt.datetime.now(dt.timezone.utc)-dt.timedelta(seconds=5)
        item=dict(title='Demo results',url='https://www.nseindia.com/',publishedAt=now.isoformat(),availableAt=now.isoformat(),symbols=['DEMO'])
        runtime=self.runtime(dict(status='fetched',stale=False,items=[item]))
        runtime.record_news(self.instrument)
        context=runtime.status()['newsContext']
        self.assertEqual(context['attached'],1)
        self.assertFalse(context['executionAllowed'])
        self.assertIsNone(self.state()['pending'])
        self.assertNotIn('Demo results',str(context))

    def test_unavailable_news_does_not_create_signal(self):
        runtime=self.runtime(dict(status='unavailable',stale=True,items=[]))
        runtime.record_news(self.instrument)
        self.assertEqual(runtime.status()['newsContext']['status'],'unavailable')
        self.assertIsNone(self.state()['pending'])

    def test_future_or_unmapped_news_excluded(self):
        future=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=1)).isoformat()
        item=dict(title='Future',url='https://www.nseindia.com/',publishedAt=future,availableAt=future,symbols=['DEMO'])
        runtime=self.runtime(dict(status='fetched',stale=False,items=[item]))
        runtime.record_news(self.instrument)
        self.assertEqual(runtime.status()['newsContext']['attached'],0)

    def test_feed_failure_is_redacted(self):
        runtime=self.runtime({})
        def failed(*args):raise ValueError('secret-feed-key')
        runtime.announcements.status=failed
        runtime.record_news(self.instrument)
        self.assertEqual(runtime.status()['newsContext']['status'],'unavailable')
        self.assertNotIn('secret-feed-key',str(runtime.status()))
