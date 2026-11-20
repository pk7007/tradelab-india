import datetime as dt
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from email.utils import format_datetime
from dashboard_news import DashboardNews
from news_agent import NewsAgent, UTC
from research_context import attach_announcements


class DashboardNewsTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime.now(UTC)
        now=self.now.isoformat()
        self.item=dict(id='one',source='nse',sourceName='NSE',title='DEMO LIMITED',summary='Results',url='https://www.nseindia.com/',publishedAt=now,receivedAt=now)
        self.payload=dict(sources=[dict(source='nse',status='fetched')],items=[self.item])
        self.calls=0
        def poll(sources):
            self.calls+=1
            return self.payload
        self.service=DashboardNews(None,SimpleNamespace(poll_once=poll,sources=('nse',)),lambda:self.now)
        self.master=[dict(exchange='NSE',instrument_type='EQ',name='DEMO LIMITED',tradingsymbol='DEMO')]

    def test_reads_and_simultaneous_ticks_share_collection(self):
        self.assertTrue(self.service.status()['stale'])
        self.assertEqual(self.calls,0)
        self.service.poll_due()
        self.assertEqual(self.service.status(self.master)['items'][0]['symbols'],['DEMO'])
        for _ in range(50):
            self.service.status(self.master)
            self.service.poll_due()
        self.assertEqual(self.calls,1)
        self.master.append(dict(self.master[0],tradingsymbol='DIFFERENT'))
        self.assertEqual(self.service.status(self.master)['items'][0]['symbols'],[])

    def test_related_headlines_keep_individual_attribution(self):
        self.payload['items']=[dict(self.item,id=key,storyKey=story) for key,story in
                               [('first','same'),('second','same'),('third','other')]]
        self.service.poll_due()
        rows=self.service.status()['items']
        self.assertEqual([row['sourceIds'] for row in rows],[['first','second'],['first','second'],['third']])

    def test_outage_retains_stale_items_outside_eligible_evidence_and_recovers(self):
        self.service.poll_due()
        self.now+=dt.timedelta(seconds=300)
        self.payload=dict(sources=[dict(source='nse',status='unavailable',retryAfterSeconds=1300)],items=[])
        self.service.poll_due()
        snapshot=self.service.status(self.master)
        self.assertTrue(snapshot['stale'])
        self.assertEqual(snapshot['items'],[])
        self.assertEqual(len(snapshot['staleItems']),1)
        _,context=attach_announcements(dict(asOf=self.now.isoformat()),snapshot)
        self.assertEqual(context['attached'],0)
        self.now+=dt.timedelta(seconds=1299)
        self.service.poll_due()
        self.assertEqual(self.calls,2)
        self.now+=dt.timedelta(seconds=1)
        self.payload=dict(sources=[dict(source='nse',status='fetched')],items=[],currentItems=[])
        self.service.poll_due()
        recovered=self.service.status()
        self.assertFalse(recovered['stale'])
        self.assertEqual(recovered['items']+recovered['staleItems'],[])

    def test_collector_polls_without_readers_and_readers_do_not_wait_for_io(self):
        entered=threading.Event()
        release=threading.Event()
        def fetch(sources):
            self.calls+=1
            entered.set()
            release.wait(3)
            return self.payload
        self.service.agent.poll_once=fetch
        self.service.start()
        try:
            self.assertTrue(entered.wait(2))
            self.service.start()
            self.service.poll_due()
            self.assertEqual(self.calls,1)
            self.assertEqual(self.service.status()['items'],[])
        finally:
            release.set()
            self.service.stop()
        snapshot=self.service.status(self.master)
        _,context=attach_announcements(dict(asOf=self.now.isoformat()),snapshot)
        self.assertEqual(context['attached'],1)
        self.assertFalse(snapshot['collectorRunning'])

    def test_unavailable_provider_without_retry_header_recovers_on_schedule(self):
        with tempfile.TemporaryDirectory() as folder:
            def offline(_):
                raise OSError('fixture outage')
            agent=NewsAgent(Path(folder)/'state.sqlite',sources=('et',),fetch=offline)
            service=DashboardNews(None,agent,lambda:self.now)
            service.poll_due()
            failed=service.status()['sources'][0]
            self.assertEqual(failed['status'],'unavailable')
            self.assertEqual(failed['failures'],1)
            self.now+=dt.timedelta(seconds=600)
            agent.fetch=lambda _:b'<rss><channel/></rss>'
            service.poll_due()
            self.assertFalse(service.status()['stale'])

    def test_collector_restart_rehydrates_items_without_redelivering_new_notifications(self):
        xml=('<rss><channel><item><title>Nifty</title><link>https://economictimes.indiatimes.com/item</link><pubDate>'+format_datetime(self.now)+'</pubDate></item></channel></rss>').encode()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.sqlite'
            for _ in range(2):
                agent=NewsAgent(path,sources=('et',),fetch=lambda _:xml)
                service=DashboardNews(path,agent)
                service.poll_due()
                self.assertEqual(len(service.status(self.master)['items']),1)
                self.assertEqual(service.status(self.master)['items'][0]['symbols'],[])
                self.assertFalse(service.status()['executionAllowed'])
                self.assertEqual(agent.poll_once()['items'],[])
