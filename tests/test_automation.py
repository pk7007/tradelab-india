import tempfile
from pathlib import Path
import unittest
from concurrent.futures import ThreadPoolExecutor
from automation import Coordinator,validate_config

CONFIG=dict(symbols='INFY',units=1,capital=10000,maxExposure=5000,maxPositionValue=2000,maxPositions=3,dailyLoss=500,ordersPerMinute=5,fast=5,slow=20,start='09:30',end='15:00',exitPolicy='manual-review')
SNAP=dict(ageSeconds=1,exposure=0,positionValue=0,positionCount=0,loss=0,available=10000,marginRequired=100,spreadBps=1,inSession=True,externalMismatch=False)
class Mock:
    mode='offline-mock'
    def __init__(self,error=False):self.calls=0;self.error=error
    def submit(self,intent):
        self.calls+=1
        if self.error:raise TimeoutError('Ambiguous timeout')
        return 'mock-order-1'

class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'test.sqlite'
        self.engine=Coordinator(self.path);self.engine.save(CONFIG)
        self.engine.state='running';self.engine.reconciled=True
    def prepare(self,signal='bar1',snapshot=None):return self.engine.prepare(signal,1,'INFY',1,1000,snapshot or SNAP)
    def test_config_requires_explicit_limits(self):
        with self.assertRaises(ValueError):validate_config({})
        with self.assertRaises(ValueError):validate_config(CONFIG|dict(dailyLoss=float('nan')))
    def test_versions_persist_and_restart_disarms(self):
        self.engine.control('stop');self.engine.save(CONFIG)
        other=Coordinator(self.path)
        self.assertEqual(other.status()['version'],2)
        self.assertEqual(other.state,'disabled');self.assertFalse(other.reconciled)
    def test_public_start_cannot_arm(self):
        self.engine.control('stop')
        result=self.engine.control('start')
        self.assertFalse(result['liveEnabled']);self.assertEqual(result['state'],'disabled')
    def test_duplicate_concurrent_signal_creates_one_intent(self):
        def attempt(_):
            try:return self.prepare()
            except ValueError:return None
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(attempt,range(4)))
        self.assertEqual(sum(bool(r) for r in results),1)
    def test_pending_exposure_blocks_addition(self):
        self.prepare()
        with self.assertRaises(ValueError):self.prepare('bar2',SNAP|dict(exposure=4500))
    def test_stale_loss_mismatch_margin_and_session_block(self):
        for change in [dict(ageSeconds=6),dict(loss=500),dict(externalMismatch=True),dict(available=1),dict(inSession=False)]:
            with self.assertRaises(ValueError):self.prepare(snapshot=SNAP|change)
    def test_ambiguous_acceptance_faults_without_retry(self):
        identity=self.prepare();broker=Mock(True);self.engine.submit_mock(identity,broker)
        self.assertEqual(self.engine.status()['intents'][0]['state'],'UNKNOWN')
        with self.assertRaises(ValueError):self.engine.submit_mock(identity,broker)
        self.assertEqual(broker.calls,1);self.assertEqual(self.engine.state,'faulted')
    def test_crash_during_submission_recovers_unknown(self):
        identity=self.prepare()
        with self.engine.db() as db:db.execute("UPDATE intents SET state='SUBMITTING' WHERE id=?",(identity,))
        self.assertEqual(Coordinator(self.path).status()['intents'][0]['state'],'UNKNOWN')
    def test_partial_fills_cannot_regress(self):
        identity=self.prepare();self.engine.submit_mock(identity,Mock())
        self.engine.reconcile_mock([dict(id=identity,state='COMPLETE',filled=1)])
        with self.assertRaises(ValueError):self.engine.reconcile_mock([dict(id=identity,state='OPEN',filled=0)])
    def test_unknown_missing_from_snapshot_stays_blocked(self):
        identity=self.prepare();self.engine.submit_mock(identity,Mock(True))
        self.assertFalse(self.engine.reconcile_mock([])['reconciled'])
    def test_external_position_mismatch_faults(self):
        self.assertEqual(self.engine.reconcile_mock([],True)['state'],'faulted')
    def test_stop_does_not_fake_cancellation_or_closure(self):
        identity=self.prepare();self.engine.submit_mock(identity,Mock())
        result=self.engine.control('stop')
        self.assertEqual(result['intents'][0]['state'],'OPEN')
        with self.assertRaises(ValueError):self.prepare('bar2')
    def test_real_adapter_rejected(self):
        class Real:mode='live'
        with self.assertRaises(ValueError):self.engine.submit_mock(self.prepare(),Real())
