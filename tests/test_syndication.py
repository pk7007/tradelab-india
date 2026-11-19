import datetime as dt
import tempfile
from pathlib import Path
import unittest
from syndication import SyndicationCache,RateLimiter


class NoWait:
    def wait(self): pass


class SyndicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.now=dt.datetime.fromisoformat('2026-11-20T06:30:00+00:00')
        self.payload={}
        self.cache=SyndicationCache(Path(self.temp.name)/'cache.sqlite',lambda endpoint,params:self.payload[endpoint],clock=lambda:self.now,limiter=NoWait())
        self.item=dict(article_id='article1',status='published',published_at='2026-11-20T06:00:00Z',updated_at='2026-11-20T06:00:00Z',tickers=['TCS'],headline='Fixture',body='Licensed fixture text',summary='Fixture')

    def sync(self,items=None,revisions=None):
        self.payload={'/feeds/news':dict(cursor=self.now.isoformat(),items=items or []),'/feeds/revisions':dict(cursor=self.now.isoformat(),revisions=revisions or [])}
        return self.cache.sync_once()

    def test_idempotence_and_no_fake_sentiment(self):
        self.sync([self.item,self.item]);self.assertEqual(len(self.cache.articles()),1)
        self.assertIsNone(self.cache.articles()[0]['sentiment_score'])

    def test_retraction_survives_old_news_and_restart(self):
        self.sync([self.item])
        self.sync([self.item],[dict(article_id='article1',status='retracted',event_timestamp='2026-11-20T06:10:00Z')])
        self.assertEqual(self.cache.articles(),[])
        self.cache=SyndicationCache(self.cache.path,self.cache.transport,clock=lambda:self.now,limiter=NoWait())
        self.sync([self.item]);self.assertEqual(self.cache.articles(),[])

    def test_updated_revision_removes_old_text_until_full_new_record(self):
        self.sync([self.item])
        revision=dict(article_id='article1',status='updated',event_timestamp='2026-11-20T06:10:00Z')
        self.sync([self.item],[revision]);self.assertEqual(self.cache.articles(),[])
        updated=dict(self.item,updated_at='2026-11-20T06:10:00Z',headline='Corrected',tickers=['INFY'])
        self.sync([updated]);self.assertEqual(self.cache.articles()[0]['tickers'],['INFY'])
        self.assertEqual(self.cache.articles()[0]['headline'],'Corrected')

    def test_malformed_page_rolls_back_content_and_cursor(self):
        self.sync([self.item]);old=self.cache.articles()
        self.now+=dt.timedelta(minutes=1)
        self.payload['/feeds/news']=dict(cursor=self.now.isoformat(),items=[dict(self.item,headline='Changed'),{'article_id':'invalid'}])
        with self.assertRaises(ValueError):self.cache.poll('/feeds/news')
        self.assertEqual(self.cache.articles(),old)
        with self.cache.db() as db:self.assertNotEqual(self.cache.state(db,'/feeds/news'),self.now.isoformat())

    def test_overdue_revision_poll_purges_content(self):
        self.sync([self.item]);self.now+=dt.timedelta(hours=6)
        self.assertEqual(self.cache.articles(),[])
        with self.cache.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM mc_articles').fetchone()[0],0)

    def test_revision_failure_blocks_delivery_and_preserves_cursor(self):
        self.sync([self.item]);self.payload['/feeds/revisions']={'cursor':'invalid','revisions':[]}
        with self.assertRaises(ValueError):self.cache.poll('/feeds/revisions')
        self.assertEqual(self.cache.articles(),[])

    def test_older_retraction_overrides_newer_update_marker(self):
        self.sync([self.item])
        self.sync([],[dict(article_id='article1',status='updated',event_timestamp='2026-11-20T06:20:00Z')])
        self.sync([dict(self.item,updated_at='2026-11-20T06:20:00Z')])
        self.sync([],[dict(article_id='article1',status='retracted',event_timestamp='2026-11-20T06:10:00Z')])
        self.sync([dict(self.item,updated_at='2026-11-20T06:25:00Z')])
        self.assertEqual(self.cache.articles(),[])

    def test_response_cursor_is_checked_against_response_receipt_not_request_start(self):
        self.sync([self.item])
        def response(endpoint,params):
            self.now+=dt.timedelta(seconds=1)
            return dict(cursor=self.now.isoformat(),items=[])
        self.cache.transport=response
        self.cache.poll('/feeds/news')

    def test_full_revision_page_does_not_certify_complete_sweep(self):
        self.sync([self.item])
        rows=[dict(article_id='other'+str(i),status='updated',event_timestamp='2026-11-20T06:10:00Z') for i in range(50)]
        self.sync([self.item],rows)
        self.assertEqual(self.cache.articles(),[])

    def test_competing_instance_cannot_regress_committed_cursor(self):
        self.sync([self.item]);old=self.now
        other=SyndicationCache(self.cache.path,lambda endpoint,params:dict(cursor=(old+dt.timedelta(minutes=2)).isoformat(),items=[]),clock=lambda:old+dt.timedelta(minutes=2),limiter=NoWait())
        def stale_response(endpoint,params):
            other.poll('/feeds/news')
            return dict(cursor=(old+dt.timedelta(minutes=1)).isoformat(),items=[])
        self.cache.transport=stale_response;self.now=old+dt.timedelta(minutes=3)
        with self.assertRaisesRegex(ValueError,'Concurrent'):
            self.cache.poll('/feeds/news')
        with self.cache.db() as db:self.assertEqual(self.cache.state(db,'/feeds/news'),(old+dt.timedelta(minutes=2)).isoformat())

    def test_invalid_rate_interval_rejected(self):
        for value in (True,float('nan'),float('inf'),0):
            with self.assertRaises(ValueError):RateLimiter(value)

    def test_duplicate_update_revision_preserves_already_corrected_record(self):
        self.sync([self.item])
        revision=dict(article_id='article1',status='updated',event_timestamp='2026-11-20T06:10:00Z')
        corrected=dict(self.item,updated_at='2026-11-20T06:10:00Z',headline='Corrected')
        self.sync([corrected],[revision])
        self.sync([],[revision])
        self.assertEqual(self.cache.articles()[0]['headline'],'Corrected')
