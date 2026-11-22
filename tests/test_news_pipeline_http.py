"""Real HTTP source snapshot -> paper context -> independently reviewed evidence."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

import test_intraday_http
from integrated_news import IntegratedNews, LicensedNews
from session_evidence import SessionEvidence
from syndication import SyndicationCache


class NewsPipelineHTTPTests(unittest.TestCase):
    def test_http_worker_and_registered_review_share_dated_event_lineage(self):
        case = test_intraday_http.IntradayHTTPTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        fixture = case.fixture
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        now = fixture.now.astimezone(dt.timezone.utc)
        published = (now - dt.timedelta(minutes=5)).isoformat()
        retracted = False

        def transport(endpoint, params):
            if endpoint.endswith('revisions'):
                return dict(cursor=now.isoformat(), revisions=[dict(article_id='one', status='retracted',
                    event_timestamp=now.isoformat())] if retracted else [])
            return dict(cursor=now.isoformat(), items=[dict(article_id='one', status='published',
                published_at=published, updated_at=published, tickers=['DEMO'],
                headline='Private licensed headline', body='Private licensed content', summary='')])

        path = Path(temporary.name) / 'licensed.sqlite'
        cache = SyndicationCache(path, transport, clock=lambda: now, limiter=SimpleNamespace(wait=lambda: None))
        licensed = LicensedNews({}, path, cache=cache, clock=lambda: now)
        licensed.feed_url = 'https://licensed.publisher.net/v1/feeds/news'
        licensed.poll_due()
        rss = SimpleNamespace(status=lambda *args, **kw: dict(items=[], sources=[], stale=True, status='unavailable'))
        hub = IntegratedNews(rss, licensed)
        case.namespace['NEWS_AGENT'] = hub
        fixture.selector.announcements = hub
        code, feed = case.request('/api/news-agent')
        self.assertEqual(code, 200)
        self.assertEqual(feed['items'][0]['symbols'], ['DEMO'])
        self.assertEqual(case.start()[0], 200)
        fixture.selector.tick()
        fixture.selector.tick()
        fixture.advance(10)
        identity = fixture.selector.worker.account
        self.assertGreater(fixture.engine.reconcile(identity)['quantity'], 0)
        evidence = SessionEvidence(fixture.engine)
        tasks = evidence.observe(fixture.selector.status())['tasks']
        mapping = next(task for task in tasks if task['domain'] == 'event-entity-mapping')
        self.assertEqual(mapping['state'], 'reviewed')
        self.assertTrue(mapping['review']['matches'])
        self.assertTrue(mapping['checks']['metadataOnly'])
        with fixture.engine.db() as db:
            event = json.loads(db.execute("SELECT body FROM events WHERE account=? AND body LIKE '%worker-news-context%' ORDER BY seq DESC LIMIT 1", (identity,)).fetchone()[0])
            self.assertEqual(mapping['checks']['sourceInputHashes'][0], event['detail']['evidence'][0]['inputHash'])
            journal = [row[0] for row in db.execute('SELECT body FROM events WHERE account=?', (identity,))]
            self.assertNotIn('Private licensed', str(journal))

        # A retraction withdraws event metadata. Exits continue on available price
        # observations even when the optional news source later fails.
        retracted = True
        now += dt.timedelta(seconds=60)
        licensed.poll_due()
        self.assertEqual(case.request('/api/news-agent')[1]['items'], [])
        cache.transport = lambda *_: (_ for _ in ()).throw(ValueError('private credential'))
        now += dt.timedelta(seconds=60)
        licensed.poll_due()
        fixture.rows[23] = dict(fixture.rows[23], low=90)
        fixture.advance(5)
        self.assertEqual(fixture.engine.reconcile(identity)['quantity'], 0)
        self.assertTrue(fixture.engine.reconcile(identity)['matches'])
        case.broker_order.assert_not_called()
