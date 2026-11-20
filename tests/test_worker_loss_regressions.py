"""Worker failures must remain actionable without retaining provider text."""
import copy
import datetime as dt
import json
import unittest

import test_paper_worker as fixtures
from test_intraday_paper import CONFIG, bars


class WorkerLossRegressionTests(unittest.TestCase):
    setUp = fixtures.WorkerTests.setUp
    start = fixtures.WorkerTests.start
    state = fixtures.WorkerTests.state

    def short_calendar(self):
        calendar = copy.deepcopy(self.calendar)
        calendar['sessions'] = {
            date: dict(open=date+'T09:15:00+05:30', close=date+'T15:15:00+05:30')
            for date in ('2026-01-02', '2026-01-05')
        }
        calendar['sessions'].update({'2026-01-03': None, '2026-01-04': None})
        return calendar

    def short_account(self):
        account = self.engine.create(dict(CONFIG, source='imported', squareOff='15:05',targetMultiple=20))['id']
        self.engine.control(account, 'start')
        return account

    def test_calendar_accepts_consecutive_complete_72_bar_sessions(self):
        account = self.short_account()
        rows = bars(72)
        rows += [dict(row, date=row['date'].replace('2026-01-02', '2026-01-05')) for row in bars(72)]
        result = self.engine.ingest(account, rows, True, session_calendar=self.short_calendar())
        self.assertEqual(result['processed'], 144)
        self.assertTrue(self.engine.reconcile(account)['matches'])

    def test_calendar_does_not_hide_missing_last_candle(self):
        account = self.short_account()
        self.engine.ingest(account, bars(71), True, session_calendar=self.short_calendar())
        next_open = dict(bars(1)[0], date='2026-01-05T09:15:00+05:30')
        with self.assertRaisesRegex(ValueError, 'Incomplete session boundary'):
            self.engine.ingest(account, [next_open], True, session_calendar=self.short_calendar())
        self.assertTrue(self.engine.reconcile(account)['matches'])

    def test_calendar_rejects_missing_whole_open_session(self):
        account = self.short_account()
        calendar = self.short_calendar()
        calendar['sessions']['2026-01-06'] = dict(open='2026-01-06T09:15:00+05:30', close='2026-01-06T15:15:00+05:30')
        calendar['sessions'].update({'2026-01-03': None, '2026-01-04': None})
        self.engine.ingest(account, bars(72), True, session_calendar=calendar)
        next_open = dict(bars(1)[0], date='2026-01-06T09:15:00+05:30')
        with self.assertRaisesRegex(ValueError, 'Missing open session'):
            self.engine.ingest(account, [next_open], True, session_calendar=calendar)
        self.assertTrue(self.engine.reconcile(account)['matches'])

    def test_calendar_requires_explicit_closed_intervening_dates(self):
        account = self.short_account()
        unknown = self.short_calendar()
        del unknown['sessions']['2026-01-03']
        self.engine.ingest(account, bars(72), True, session_calendar=unknown)
        next_open = dict(bars(1)[0], date='2026-01-05T09:15:00+05:30')
        with self.assertRaisesRegex(ValueError, 'Session unknown'):
            self.engine.ingest(account, [next_open], True, session_calendar=unknown)
        calendar = self.short_calendar()
        calendar['sessions'].update({'2026-01-03': None, '2026-01-04': None})
        self.assertEqual(self.engine.ingest(account, [next_open], True, session_calendar=calendar)['processed'], 1)

    def test_worker_rejects_squareoff_at_continuous_session_close(self):
        with self.assertRaisesRegex(ValueError, 'square-off'):
            self.worker.start(self.account, self.instrument, self.short_calendar(), True, True)
        self.assertEqual(self.state()['status'], 'paused')
        self.assertFalse(self.worker.status()['enabled'])

    def test_squareoff_bar_at_1505_settles_at_1510_and_auction_is_outside_request(self):
        self.calendar=self.short_calendar()
        too_late=self.engine.create(dict(CONFIG,source='imported',squareOff='15:10'))['id']
        with self.assertRaisesRegex(ValueError,'square-off'):
            self.worker.start(too_late,self.instrument,self.calendar,True,True)
        self.account=self.short_account()
        self.start()
        self.worker.tick()
        while self.now.strftime('%H:%M') < '15:09':
            self.now+=dt.timedelta(minutes=2)
            self.worker.tick()
        self.assertGreater(self.state()['quantity'],0)
        self.now+=dt.timedelta(minutes=1)
        self.worker.tick()
        self.assertEqual(self.state()['quantity'],0)
        self.assertEqual(self.state()['lastBar'][11:16],'15:05')
        with self.engine.db() as db:
            events=[json.loads(r[0]) for r in db.execute('SELECT body FROM events WHERE account=? ORDER BY seq',(self.account,))]
        fills=[e for e in events if e['type']=='fill' and e['side']=='SELL']
        self.assertEqual([(e['bar'][11:16],e['reason']) for e in fills],[('15:05','Session square-off or recovery')])
        for _ in range(3):
            self.now+=dt.timedelta(minutes=2)
            self.worker.tick()
        self.assertEqual(self.calls[-1][2].strftime('%H:%M:%S'),'15:14:59')
        self.assertEqual(self.state()['lastBar'][11:16],'15:10')
        self.assertTrue(self.engine.reconcile(self.account)['matches'])
        self.worker.stop()
        self.now=dt.datetime.fromisoformat('2026-01-05T09:20:00+05:30')
        self.rows.append(dict(self.rows[0],date='2026-01-05T09:15:00+05:30'))
        self.start()
        self.worker.tick()
        self.assertEqual([(start.day,end.strftime('%H:%M:%S')) for _,start,end in self.calls[-2:]],
                         [(2,'15:14:59'),(5,'09:20:00')])
        self.assertEqual(self.state()['lastBar'],'2026-01-05T09:15:00+05:30')

    def test_second_account_cannot_arm_while_another_lease_is_live(self):
        self.start()
        with self.assertRaisesRegex(ValueError,'Another worker'):
            self.worker.start(self.short_account(),self.instrument,self.calendar,True,True)
        self.assertEqual(self.worker.status()['accountId'],self.account)

    def test_arm_checks_later_manifest_dates_before_writing_state(self):
        calendar = self.short_calendar()
        calendar['sessions']['2026-01-02']['close'] = '2026-01-02T15:30:00+05:30'
        with self.assertRaisesRegex(ValueError, 'square-off'):
            self.worker.start(self.account, self.instrument, calendar, True, True)
        self.assertEqual(self.state()['status'], 'paused')
        with self.engine.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM paper_workers').fetchone()[0], 0)

    def test_short_session_worker_passes_calendar_to_ingestion(self):
        self.account = self.short_account()
        self.calendar = self.short_calendar()
        self.start()
        ingest = self.engine.ingest
        supplied = []
        def capture(*args, **kwargs):
            supplied.append(kwargs['session_calendar'])
            return ingest(*args, **kwargs)
        self.engine.ingest = capture
        self.assertEqual(self.worker.tick()['processed'], 20)
        self.assertEqual(supplied, [self.calendar])
        self.assertTrue(self.engine.reconcile(self.account)['matches'])

    def test_calendar_rejects_bar_at_close_and_preserves_legacy_boundary(self):
        account = self.short_account()
        at_close = dict(bars(1)[0], date='2026-01-02T15:15:00+05:30')
        with self.assertRaisesRegex(ValueError, 'calendar'):
            self.engine.ingest(account, [at_close], True, session_calendar=self.short_calendar())
        self.engine.ingest(account, bars(72), True)
        next_open = dict(bars(1)[0], date='2026-01-05T09:15:00+05:30')
        with self.assertRaisesRegex(ValueError, 'Incomplete session boundary'):
            self.engine.ingest(account, [next_open], True)

    def test_revised_completed_bar_is_identified_and_never_overwritten(self):
        self.start()
        self.worker.tick()
        before = self.state()
        revised = copy.deepcopy(self.rows[19])
        revised['volume'] += 1
        self.worker.fetch = lambda *args: [revised]
        with self.assertRaisesRegex(ValueError, 'processed candle changed'):
            self.worker.tick()
        result = self.worker.status()
        self.assertEqual(result['lastErrorCode'], 'REVISED_PROCESSED_CANDLE')
        self.assertEqual(result['failureStage'], 'ingestion')
        self.assertEqual(self.state(), before)
        self.assertTrue(self.engine.reconcile(self.account)['matches'])

    def test_provider_text_is_not_copied_to_diagnostics(self):
        self.start()
        self.worker.fetch = lambda *args: (_ for _ in ()).throw(ValueError('private-token-123'))
        with self.assertRaises(ValueError):
            self.worker.tick()
        result = self.worker.status()
        self.assertEqual(result['lastErrorCode'], 'PROVIDER_FETCH_FAILED')
        self.assertEqual(result['failureStage'], 'provider-fetch')
        self.assertNotIn('private-token-123', json.dumps(result))
        with self.engine.db() as db:
            body = db.execute('SELECT body FROM paper_workers WHERE account=?', (self.account,)).fetchone()[0]
        self.assertNotIn('private-token-123', body)

    def test_missing_interval_is_distinguished_from_revised_candle(self):
        self.start()
        self.worker.tick()
        self.now += dt.timedelta(minutes=4)
        self.worker.fetch = lambda *args: [copy.deepcopy(self.rows[19])]
        self.worker.tick()
        self.now += dt.timedelta(minutes=2)
        self.worker.fetch = lambda *args: [copy.deepcopy(self.rows[21])]
        before = self.state()
        with self.assertRaisesRegex(ValueError, 'Missing five-minute'):
            self.worker.tick()
        self.assertEqual(self.worker.status()['lastErrorCode'], 'MISSING_CANDLE')
        self.assertEqual(self.state(), before)


if __name__ == '__main__':
    unittest.main()
