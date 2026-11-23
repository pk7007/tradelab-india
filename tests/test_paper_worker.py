import copy
import json
import datetime as dt
from pathlib import Path
import tempfile
import unittest

from paper import PaperEngine
from paper_worker import PaperWorker
from test_intraday_paper import CONFIG, bars


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'paper.sqlite';self.engine=PaperEngine(self.path)
        self.account=self.engine.create(dict(CONFIG,source='imported'))['id']
        self.now=dt.datetime.fromisoformat('2026-01-02T10:59:00+05:30')
        self.rows=bars(75);self.calls=[]
        self.instrument=dict(exchange='NSE',symbol='DEMO',token=123)
        self.calendar=dict(exchange='NSE',segment='EQ',version='fixture-1',source='https://example.invalid/calendar',availableAt='2026-01-01T00:00:00+05:30',sessions={'2026-01-02':dict(open='2026-01-02T09:15:00+05:30',close='2026-01-02T15:30:00+05:30')})
        def fetch(instrument,start,end):
            self.calls.append((instrument,start,end))
            return copy.deepcopy([r for r in self.rows if start<=dt.datetime.fromisoformat(r['date'])<=end])
        self.fetch=fetch
        self.worker=PaperWorker(self.engine,fetch,clock=lambda:self.now,lease_seconds=300)

    def start(self,worker=None,**changes):
        args=dict(retention_approved=True,calendar_confirmed=True);args.update(changes)
        return (worker or self.worker).start(self.account,self.instrument,self.calendar,**args)

    def state(self):
        with self.engine.db() as db:return self.engine.load(db,self.account)

    def test_explicit_permissions_and_model_binding_required(self):
        with self.assertRaises(ValueError):self.start(retention_approved=False)
        with self.assertRaises(ValueError):self.start(calendar_confirmed=False)
        with self.assertRaises(ValueError):self.worker.start(self.account,dict(self.instrument,token=True),self.calendar,True,True)
        self.assertEqual(self.state()['status'],'paused')

    def test_startup_disarmed_and_second_owner_cannot_claim(self):
        self.assertFalse(self.worker.status()['enabled'])
        with self.assertRaises(ValueError):self.worker.tick()
        self.start();other=PaperWorker(self.engine,self.fetch,clock=lambda:self.now)
        with self.assertRaisesRegex(ValueError,'Another worker'):self.start(other)
        self.assertTrue(self.worker.status()['enabled'])

    def test_warmup_suppresses_old_entries_and_forward_receipts_are_distinct(self):
        self.start();r=self.worker.tick()
        self.assertEqual(r['processed'],20);self.assertEqual(self.state()['quantity'],0)
        self.assertIsNone(self.state()['pending'])
        self.now+=dt.timedelta(minutes=1);self.worker.tick()
        self.assertEqual(self.state()['pending']['side'],'BUY')
        self.now+=dt.timedelta(minutes=4);self.worker.tick()
        self.now+=dt.timedelta(minutes=1);self.worker.tick()
        self.assertEqual(self.state()['quantity'],9)
        self.assertTrue(self.engine.reconcile(self.account)['matches'])
        with self.engine.db() as db:
            modes={r[0] for r in db.execute('SELECT DISTINCT mode FROM worker_receipts')}
            self.assertEqual(modes,{'warmup','observed-candle-paper'})
            self.assertEqual(db.execute('SELECT COUNT(*) FROM worker_receipts').fetchone()[0],22)
        duplicate=self.worker.tick();self.assertEqual(duplicate['processed'],0)

    def test_stale_gap_and_revised_batches_do_not_mutate_ledger(self):
        self.start();self.worker.tick();before=self.state()
        self.now+=dt.timedelta(minutes=1)
        self.worker.fetch=lambda i,s,e:[]
        with self.assertRaisesRegex(ValueError,'No completed'):self.worker.tick()
        self.assertEqual(self.state(),before)
        self.worker.fetch=lambda i,s,e:[dict(self.rows[19],close=500,high=501)]
        with self.assertRaises(ValueError):self.worker.tick()
        self.assertEqual(self.state(),before)

    def test_lease_expiration_during_fetch_fences_all_changes(self):
        self.start();before=self.state()
        def slow(instrument,start,end):
            self.now+=dt.timedelta(seconds=301)
            return self.fetch(instrument,start,end)
        self.worker.fetch=slow
        with self.assertRaisesRegex(ValueError,'lease'):self.worker.tick()
        self.assertEqual(self.state(),before)
        self.assertEqual(self.worker.status()['state'],'expired')

    def test_reclaim_while_old_request_inflight_fences_old_commit(self):
        self.start();other=PaperWorker(self.engine,self.fetch,clock=lambda:self.now,lease_seconds=300)
        def replacement(instrument,start,end):
            self.now+=dt.timedelta(seconds=301)
            self.start(other)
            return self.fetch(instrument,start,end)
        self.worker.fetch=replacement
        with self.assertRaisesRegex(ValueError,'lease'):self.worker.tick()
        self.assertIsNone(self.state()['lastBar'])
        self.assertFalse(self.worker.status()['enabled'])

    def test_unknown_session_blocks_provider_request(self):
        bad=copy.deepcopy(self.calendar);bad['sessions']={}
        with self.assertRaisesRegex(ValueError,'Session unknown'):
            self.worker.start(self.account,self.instrument,bad,True,True)
        self.assertEqual(self.calls,[])

    def test_provider_failure_redacted_and_stop_preserves_pending(self):
        self.start();self.worker.tick();self.now+=dt.timedelta(minutes=1);self.worker.tick()
        before=self.state()['pending'];self.worker.stop()
        self.assertEqual(self.state()['pending'],before);self.assertEqual(self.state()['status'],'paused')
        self.start();self.worker.fetch=lambda *args:(_ for _ in ()).throw(PermissionError('private-token'))
        with self.assertRaises(PermissionError):self.worker.tick()
        self.assertNotIn('private-token',self.worker.status()['lastError'])
        self.assertEqual(self.worker.status()['lastErrorCode'],'BROKER_LOGIN_REQUIRED')

    def test_holiday_waits_without_fetch_and_special_session_blocks(self):
        calendar=copy.deepcopy(self.calendar);calendar['sessions']['2026-01-02']=None
        self.worker.start(self.account,self.instrument,calendar,True,True)
        self.assertEqual(self.worker.tick()['state'],'waiting');self.assertEqual(self.calls,[])
        self.worker.stop()
        calendar=copy.deepcopy(self.calendar)
        calendar['sessions']['2026-01-02']['open']='2026-01-02T10:00:00+05:30'
        self.worker.start(self.account,self.instrument,calendar,True,True)
        with self.assertRaisesRegex(ValueError,'Special session'):self.worker.tick()
        self.assertEqual(self.calls,[])

    def test_arming_records_calendar_source_version_and_fingerprint(self):
        import trading_calendar
        self.start()
        status=self.worker.status()
        self.assertEqual((status['calendarVersion'],status['calendarSource']),('fixture-1','https://example.invalid/calendar'))
        self.assertEqual(status['calendarFingerprint'],trading_calendar.fingerprint(self.calendar))
        self.assertNotIn('calendar',status)

    def test_square_off_time_comes_from_calendar_and_worker_clock_closes_position(self):
        self.start()
        self.assertEqual(self.worker.status()['squareOffAt'],'2026-01-02T15:15:00+05:30')
        self.worker.tick()
        for minutes in (1,4,1):
            self.now+=dt.timedelta(minutes=minutes);self.worker.tick()
        self.assertGreater(self.state()['quantity'],0)
        for i in range(22,len(self.rows)):   # slow rise: trend holds, no stop or target can trigger
            price=102.2+0.002*(i-22)
            self.rows[i]=dict(self.rows[i],open=price,high=price+0.01,low=price-0.01,close=price)
        stop=dt.datetime.fromisoformat('2026-01-02T15:26:00+05:30')
        while self.now<stop:   # step inside the 300 s lease so ingestion is never fenced
            self.now+=dt.timedelta(minutes=4);self.worker.tick()
        self.assertEqual(self.state()['quantity'],0)
        with self.engine.db() as db:
            sells=[json.loads(r[0]) for r in db.execute('SELECT body FROM events ORDER BY seq')]
        exits=[e for e in sells if e.get('type')=='fill' and e.get('side')=='SELL']
        self.assertEqual(len(exits),1)
        self.assertIn('square-off',exits[0]['reason'].lower())
        self.assertGreaterEqual(exits[0]['bar'],'2026-01-02T15:15:00+05:30')
        self.assertTrue(self.engine.reconcile(self.account)['matches'])

    def test_arming_on_a_listed_holiday_is_allowed_and_has_no_square_off_time(self):
        holiday=dict(self.calendar,sessions={'2026-01-02':None})
        self.worker.start(self.account,self.instrument,holiday,True,True)
        self.assertIsNone(self.worker.status()['squareOffAt'])

    def test_stale_or_unlisted_calendar_refuses_to_arm_and_changes_nothing(self):
        stale=dict(self.calendar,availableAt='2025-10-01T00:00:00+05:30')
        with self.assertRaisesRegex(ValueError,'stale'):self.worker.start(self.account,self.instrument,stale,True,True)
        unlisted=dict(self.calendar,sessions={'2026-01-05':self.calendar['sessions']['2026-01-02']})
        with self.assertRaises(ValueError):self.worker.start(self.account,self.instrument,unlisted,True,True)
        self.assertFalse(self.worker.status()['enabled'])
        self.assertEqual(self.state()['status'],'paused')
        self.assertEqual(self.calls,[])

    def test_manual_ingestion_cannot_bypass_worker_ownership(self):
        self.start()
        with self.assertRaises(ValueError):self.engine.ingest(self.account,self.rows[:1],True)
