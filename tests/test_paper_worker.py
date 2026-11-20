import copy
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

    def test_manual_ingestion_cannot_bypass_worker_ownership(self):
        self.start()
        with self.assertRaises(ValueError):self.engine.ingest(self.account,self.rows[:1],True)
