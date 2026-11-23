import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from integrated_news import IntegratedNews
import news_assessor as na

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 23, 10, 0, tzinfo=UTC)
TITLE = 'Infosys announces buyback of Rs 9,300 crore'
SUMMARY = 'Board approves share buyback at Rs 1,800 per share.'


def item(n=1, available='2026-11-23T09:05:00+00:00', **over):
    base = dict(id=f'{n:064d}', source='nse', title=TITLE, summary=SUMMARY, url='https://example.test/x',
                publishedAt='2026-11-23T09:00:00+00:00', availableAt=available, symbols=['INFY'])
    base.update(over)
    return base


REPLY = json.dumps(dict(sentiment='bullish', eventType='corporate action', confidence=0.6,
                        symbols=['INFY'], quote='Board approves share buyback',
                        rationale='Buyback at a stated price.'))


class Completer:
    def __init__(self, reply=REPLY):
        self.reply, self.calls = reply, 0

    def __call__(self, prompt):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


class AssessorTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / 'assess.sqlite'
        self.clock = Clock()
        self.complete = Completer()

    def tearDown(self):
        self.dir.cleanup()

    def make(self, **kw):
        kw.setdefault('complete', self.complete)
        kw.setdefault('clock', self.clock)
        return na.NewsAssessor(self.path, **kw)

    def test_disabled_makes_no_calls_and_says_so(self):
        service = self.make(enabled=False)
        service.tick([item()])
        self.assertEqual(self.complete.calls, 0)
        self.assertEqual(service.summary()['status'], 'disabled')

    def test_new_items_are_assessed_once_and_stored(self):
        service = self.make(enabled=True)
        service.tick([item(1), item(2)])
        service.tick([item(1), item(2)])
        self.assertEqual(self.complete.calls, 2)
        found = service.assessments()
        self.assertEqual(found[item(1)['id']]['assessment']['sentiment'], 'bullish')
        self.assertIs(found[item(1)['id']]['executionAllowed'], False)

    def test_revised_item_is_assessed_again(self):
        service = self.make(enabled=True)
        service.tick([item(1)])
        service.tick([item(1, available='2026-11-23T09:50:00+00:00')])
        self.assertEqual(self.complete.calls, 2)

    def test_cycle_cap_limits_calls_and_the_rest_wait_for_the_next_tick(self):
        service = self.make(enabled=True, cycle_limit=2)
        service.tick([item(n) for n in range(1, 6)])
        self.assertEqual(self.complete.calls, 2)
        service.tick([item(n) for n in range(1, 6)])
        self.assertEqual(self.complete.calls, 4)

    def test_daily_cap_survives_restart_and_resets_next_day(self):
        self.make(enabled=True, daily_limit=3).tick([item(n) for n in range(1, 3)])
        restarted = self.make(enabled=True, daily_limit=3)
        restarted.tick([item(n) for n in range(3, 8)])
        self.assertEqual(self.complete.calls, 3)
        self.assertEqual(restarted.summary()['usedToday'], 3)
        self.clock.now += dt.timedelta(days=1)
        restarted.tick([item(n) for n in range(3, 8)])
        self.assertGreater(self.complete.calls, 3)

    def test_provider_failure_is_recorded_not_raised_and_retried_later(self):
        self.complete.reply = TimeoutError('slow')
        service = self.make(enabled=True)
        service.tick([item(1)])
        self.assertEqual(service.assessments(), {})
        self.assertEqual(service.summary()['unavailable'], 1)
        self.complete.reply = REPLY
        service.tick([item(1)])
        self.assertEqual(service.assessments(), {})  # still backing off
        self.clock.now += dt.timedelta(minutes=2)
        service.tick([item(1)])
        self.assertIn(item(1)['id'], service.assessments())

    def test_rejected_replies_are_not_retried_every_cycle(self):
        self.complete.reply = 'not json'
        service = self.make(enabled=True)
        service.tick([item(1)])
        service.tick([item(1)])
        self.assertEqual(self.complete.calls, 1)
        self.assertEqual(service.assessments(), {})
        self.assertEqual(service.summary()['rejected'], 1)

    def test_no_article_text_or_quote_is_written_to_disk(self):
        service = self.make(enabled=True)
        service.tick([item(1)])
        raw = b''.join(p.read_bytes() for p in Path(self.dir.name).glob('assess.sqlite*'))
        for text in (TITLE, 'buyback', 'Board approves'):
            self.assertNotIn(text.encode(), raw)

    def test_symbols_come_only_from_the_items_own_mapped_symbols(self):
        self.complete.reply = REPLY
        service = self.make(enabled=True)
        service.tick([item(1, symbols=[])])  # unmapped item: model may not name a symbol
        self.assertEqual(service.assessments(), {})
        self.assertEqual(service.summary()['rejected'], 1)

    def test_failing_items_back_off_so_later_items_are_not_starved(self):
        self.complete.reply = TimeoutError('slow')
        service = self.make(enabled=True, cycle_limit=2)
        batch = [item(n) for n in (1, 2, 3)]
        service.tick(batch)
        self.assertEqual(self.complete.calls, 2)   # items 1 and 2 failed
        service.tick(batch)
        self.assertEqual(self.complete.calls, 3)   # only item 3 is tried; 1 and 2 are backing off
        self.clock.now += dt.timedelta(hours=2)
        service.tick(batch)
        self.assertEqual(self.complete.calls, 5)   # backoff expired: two more attempts (cycle cap)

    def test_negative_or_bad_limits_in_settings_fall_back_instead_of_crashing(self):
        env = {'TRADELAB_NEWS_AI_DAILY_LIMIT': '-1', 'TRADELAB_NEWS_AI_CYCLE_LIMIT': 'abc'}
        service = na.from_environment(env, self.path, clock=self.clock)
        summary = service.summary()
        self.assertEqual((summary['dailyLimit'], summary['cycleLimit']), (100, 5))

    def test_labels_for_a_revised_item_are_not_shown_until_the_new_revision_is_assessed(self):
        service = self.make(enabled=True)
        service.tick([item(1)])
        old, new = item(1), item(1, available='2026-11-23T09:50:00+00:00')
        self.assertIn(old['id'], service.assessments_for([old]))
        self.assertEqual(service.assessments_for([new]), {})

    def test_from_environment_requires_both_flag_and_key(self):
        off = na.from_environment({}, self.path, clock=self.clock)
        self.assertEqual(off.summary()['status'], 'disabled')
        half = na.from_environment({'TRADELAB_NEWS_AI': 'true'}, self.path, clock=self.clock)
        self.assertEqual(half.summary()['status'], 'missing-key')
        half.tick([item(1)])
        self.assertEqual(half.summary()['usedToday'], 0)


class HubMerge(unittest.TestCase):
    def test_hub_attaches_assessments_without_changing_item_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = na.NewsAssessor(Path(tmp) / 'a.sqlite', complete=Completer(), enabled=True, clock=Clock())
            service.tick([item(1)])
            rss = SimpleNamespace(status=lambda instruments=(), source=None: dict(
                items=[item(1), item(2)], sources=[], status='fetched', stale=False, partial=False))
            licensed = SimpleNamespace(status=lambda instruments=(): dict(items=[], sources=[dict(
                collectorRunning=False, lastSuccess=None, stale=True)]))
            hub = IntegratedNews(rss, licensed, assessor=service)
            result = hub.status()
            first, second = result['items']
            self.assertEqual(first['assessment']['sentiment'], 'bullish')
            self.assertNotIn('assessment', second)
            self.assertEqual(result['intelligence']['status'], 'enabled')
            self.assertIs(result['executionAllowed'], False)

    def test_hub_does_not_attach_a_label_made_for_an_older_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = na.NewsAssessor(Path(tmp) / 'a.sqlite', complete=Completer(), enabled=True, clock=Clock())
            service.tick([item(1)])
            revised = item(1, available='2026-11-23T09:50:00+00:00')
            rss = SimpleNamespace(status=lambda instruments=(), source=None: dict(
                items=[revised], sources=[], status='fetched', stale=False, partial=False))
            licensed = SimpleNamespace(status=lambda instruments=(): dict(items=[], sources=[dict(
                collectorRunning=False, lastSuccess=None, stale=True)]))
            self.assertNotIn('assessment', IntegratedNews(rss, licensed, assessor=service).status()['items'][0])

    def test_hub_without_assessor_is_unchanged(self):
        rss = SimpleNamespace(status=lambda instruments=(), source=None: dict(
            items=[item(1)], sources=[], status='fetched', stale=False, partial=False))
        licensed = SimpleNamespace(status=lambda instruments=(): dict(items=[], sources=[dict(
            collectorRunning=False, lastSuccess=None, stale=True)]))
        result = IntegratedNews(rss, licensed).status()
        self.assertNotIn('intelligence', result)
        self.assertNotIn('assessment', result['items'][0])


if __name__ == '__main__':
    unittest.main()


class LazyStorageTests(unittest.TestCase):
    def test_disabled_service_never_touches_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sub' / 'a.sqlite'
            svc = na.NewsAssessor(path)
            self.assertEqual(svc.assessments_for([item()]), {})
            self.assertEqual(svc.summary()['status'], 'disabled')
            svc.tick([item()])
            self.assertFalse(path.parent.exists())

    def test_unwritable_path_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / 'file'
            blocker.write_text('x')
            path = blocker / 'a.sqlite'
            svc = na.NewsAssessor(path, complete=lambda *a, **k: REPLY, enabled=True)
            svc.tick([item()])
            self.assertEqual(svc.assessments_for([item()]), {})
            self.assertEqual(svc.assessments(), {})
            summary = svc.summary()
            self.assertEqual(summary['status'], 'unavailable')
            self.assertIn('reason', summary)

    def test_malformed_result_does_not_raise_in_integrated_news(self):
        news = IntegratedNews.__new__(IntegratedNews)
        news.assessor = na.NewsAssessor(Path(tempfile.gettempdir()) / 'nope-never-created' / 'a.sqlite')
        self.assertEqual(news._with_assessments({'items': None}).get('items'), None)


class ConcurrencyAndRecoveryTests(unittest.TestCase):
    def make(self, tmp, complete=None, name='a.sqlite'):
        return na.NewsAssessor(Path(tmp) / name, complete=complete or (lambda *a, **k: REPLY), enabled=True)

    def test_reads_do_not_wait_for_slow_provider_tick(self):
        import threading
        import time
        started, release = threading.Event(), threading.Event()

        def slow(*a, **k):
            started.set()
            release.wait(5)
            return REPLY
        with tempfile.TemporaryDirectory() as tmp:
            svc = self.make(tmp, slow)
            worker = threading.Thread(target=svc.tick, args=([item()],))
            worker.start()
            try:
                self.assertTrue(started.wait(5))
                t0 = time.monotonic()
                svc.assessments_for([item()])
                svc.assessments()
                svc.summary()
                self.assertLess(time.monotonic() - t0, 0.5)
                self.assertTrue(worker.is_alive())
                svc.tick([item(2)])  # single flight: skipped, never blocks
                self.assertLess(time.monotonic() - t0, 0.5)
            finally:
                release.set()
                worker.join(10)

    def test_locked_database_reads_fail_soft(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            svc = self.make(tmp)
            svc.summary()
            blocker = sqlite3.connect(svc.path)
            blocker.execute('BEGIN EXCLUSIVE')
            try:
                svc.timeout = 0.05
                self.assertEqual(svc.assessments_for([item()]), {})
                self.assertEqual(svc.summary()['status'], 'enabled')
            finally:
                blocker.rollback()
                blocker.close()

    def test_deleted_database_is_recreated(self):
        with tempfile.TemporaryDirectory() as tmp:
            svc = self.make(tmp)
            svc.tick([item()])
            self.assertEqual(svc.summary()['assessed'], 1)
            svc.path.unlink()
            for extra in ('-wal', '-shm'):
                Path(str(svc.path) + extra).unlink(missing_ok=True)
            self.assertEqual(svc.summary()['status'], 'unavailable')  # one failing call resets
            svc.tick([item()])
            self.assertEqual(svc.summary()['assessed'], 1)

    def test_directory_in_place_of_database_file_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'a.sqlite').mkdir()
            svc = self.make(tmp)
            svc.tick([item()])
            self.assertEqual(svc.summary()['status'], 'unavailable')
            self.assertEqual(svc.assessments_for([item()]), {})

    def test_lazy_init_creates_once_under_threads(self):
        import sqlite3
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            svc = self.make(tmp)
            real = sqlite3.connect
            created = []

            def counting(path, *a, **k):
                db = real(path, *a, **k)
                if not svc.ready:
                    created.append(1)
                return db
            na.sqlite3.connect = counting
            try:
                threads = [threading.Thread(target=svc.summary) for _ in range(8)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
            finally:
                na.sqlite3.connect = real
            self.assertEqual(len(created), 1)

    def test_with_assessments_normal_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            svc = self.make(tmp)
            svc.tick([item()])
            news = IntegratedNews.__new__(IntegratedNews)
            news.assessor = svc
            out = news._with_assessments({'items': [item()]})
            self.assertEqual(out['items'][0]['assessment']['sentiment'], 'bullish')
            self.assertEqual(out['intelligence']['assessed'], 1)
