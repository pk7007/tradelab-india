import datetime as dt
from contextlib import closing
from pathlib import Path
import tempfile
import sqlite3
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from integrated_news import IntegratedNews, LicensedNews
from research_context import attach_announcements
from syndication import SyndicationCache


class IntegratedNewsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'licensed.sqlite'
        self.now = dt.datetime.fromisoformat('2026-11-22T08:00:00+00:00')
        self.items = [dict(article_id='one', status='published',
            published_at='2026-11-22T07:55:00Z', updated_at='2026-11-22T07:55:00Z',
            tickers=['DEMO', 'UNMAPPED'], headline='Private headline',
            summary='Private summary', body='Private body')]
        self.revisions = []
        self.calls = []
        self.failed = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

        def transport(endpoint, params):
            self.calls.append(endpoint)
            self.entered.set()
            self.release.wait(3)
            if self.failed:
                raise ValueError('secret-token and licensed body')
            return dict(cursor=self.now.isoformat(), **(
                {'revisions': self.revisions} if endpoint.endswith('revisions') else {'items': self.items}))

        self.cache = SyndicationCache(self.path, transport, clock=lambda: self.now,
                                      limiter=SimpleNamespace(wait=lambda: None))
        self.licensed = LicensedNews({}, self.path, cache=self.cache, clock=lambda: self.now)
        self.licensed.feed_url = 'https://licensed.publisher.net/v1/feeds/news'
        self.master = [dict(exchange='NSE', instrument_type='EQ', tradingsymbol='DEMO')]
        self.rss = Mock()
        self.rss.status.side_effect = lambda *args, **kw: dict(items=[], staleItems=[],
            sources=[dict(source='nse', stale=True)], status='unavailable', stale=True,
            lastSuccess=None)
        self.hub = IntegratedNews(self.rss, self.licensed)

    def test_licensed_source_reaches_shared_research_context_without_copying_text(self):
        self.licensed.poll_due()
        feed = self.hub.status(self.master)
        values, summary = attach_announcements(dict(asOf=self.now.isoformat()), feed)
        self.assertEqual(summary['attached'], 1)
        self.assertEqual(values['records'][0]['symbols'], ['DEMO'])
        self.assertFalse(feed['executionAllowed'])
        self.assertNotIn('Private', str(feed))
        self.assertNotIn('Private', str(values))
        self.assertEqual(feed['sources'][-1]['status'], 'fetched')
        self.assertEqual(self.calls, ['/feeds/revisions', '/feeds/news'])
        self.licensed.poll_due()
        self.assertEqual(len(self.calls), 2)

    def test_retractions_and_failed_provider_remove_deliverable_evidence(self):
        self.licensed.poll_due()
        self.now += dt.timedelta(seconds=60)
        self.revisions = [dict(article_id='one', status='retracted', event_timestamp=self.now.isoformat())]
        self.licensed.poll_due()
        self.assertEqual(self.hub.status(self.master)['items'], [])
        self.assertEqual(self.cache.articles(), [])
        self.now += dt.timedelta(seconds=60)
        self.failed = True
        self.licensed.poll_due()
        feed = self.hub.status(self.master)
        self.assertTrue(feed['stale'])
        self.assertEqual(feed['items'], [])
        self.assertNotIn('secret-token', str(feed))
        self.assertEqual(self.licensed.health['failures'], 1)

    def test_reader_does_not_wait_for_network_and_polling_is_single_flight(self):
        self.release.clear()
        thread = threading.Thread(target=self.licensed.poll_due)
        thread.start()
        try:
            self.assertTrue(self.entered.wait(1))
            started = time.monotonic()
            snapshot = self.hub.status(self.master)
            self.assertLess(time.monotonic() - started, .5)
            self.assertTrue(snapshot['stale'])
            self.licensed.poll_due()
            self.assertEqual(len(self.calls), 1)
        finally:
            self.release.set()
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())

    def test_disabled_and_invalid_configuration_never_open_transport(self):
        for settings, status in (({}, 'disabled'),
                                 ({'SYNDICATION_ENABLED': 'true'}, 'blocked-configuration')):
            service = LicensedNews(settings, self.path)
            service.start()
            self.assertIsNone(service.thread)
            self.assertEqual(service.status()['sources'][0]['status'], status)

    def test_shared_lifecycle_and_nse_filter_preserve_existing_callers(self):
        self.licensed.start = Mock()
        self.licensed.stop = Mock()
        self.hub.start()
        self.hub.stop()
        self.rss.start.assert_called_once()
        self.rss.stop.assert_called_once()
        self.licensed.start.assert_called_once()
        self.licensed.stop.assert_called_once()
        self.assertEqual(len(self.hub.status(source='nse')['sources']), 1)

    def test_overdue_revision_cache_expires_when_collector_is_stopped(self):
        self.licensed.poll_due()
        self.now += dt.timedelta(hours=6)
        self.assertEqual(self.hub.status(self.master)['items'], [])
        with self.cache.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM mc_articles').fetchone()[0], 0)

    def test_storage_failure_isolated_from_existing_rss_snapshot(self):
        self.cache.articles = Mock(side_effect=ValueError('private location'))
        self.rss.status.side_effect = lambda *args, **kw: dict(items=[], staleItems=[],
            sources=[dict(source='nse', stale=False)], status='fetched', stale=False)
        feed = self.hub.status(self.master)
        self.assertFalse(feed['stale'])
        self.assertTrue(feed['partial'])
        self.assertNotIn('private location', str(feed))

    def test_external_database_writer_cannot_block_price_processing(self):
        self.licensed.poll_due()
        with closing(sqlite3.connect(self.path)) as writer:
            writer.execute('BEGIN EXCLUSIVE')
            started = time.monotonic()
            result = self.hub.status(self.master)
            self.assertLess(time.monotonic() - started, .5)
            self.assertTrue(result['stale'])
            self.assertEqual(result['items'], [])
            writer.rollback()

    def test_reader_limits_research_projection_to_one_hundred_records(self):
        self.items = [dict(self.items[0], article_id='item' + str(index)) for index in range(150)]
        self.licensed.poll_due()
        self.assertEqual(len(self.cache.articles()), 150)
        self.assertEqual(len(self.hub.status(self.master)['items']), 100)
