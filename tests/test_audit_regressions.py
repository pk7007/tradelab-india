import unittest
from unittest.mock import Mock
from worker_runtime import WorkerRuntime
from research import ResearchRiskGate

class AuditRegressionTests(unittest.TestCase):
    def test_inactive_worker_does_not_write_stop_or_fetch(self):
        runtime=WorkerRuntime.__new__(WorkerRuntime)
        runtime.worker=Mock()
        runtime.worker.status.return_value={'enabled':False}
        for _ in range(3):runtime.tick_once()
        runtime.worker.tick.assert_not_called()
        runtime.worker.stop.assert_not_called()

    def test_fault_stops_once_then_inactive_poll_is_quiet(self):
        runtime=WorkerRuntime.__new__(WorkerRuntime)
        runtime.worker=Mock()
        runtime.worker.status.side_effect=[{'enabled':True},{'enabled':False}]
        runtime.worker.tick.side_effect=ValueError('provider failure')
        runtime.tick_once();runtime.tick_once()
        runtime.worker.tick.assert_called_once()
        runtime.worker.stop.assert_called_once()

    def test_risk_gate_rejects_boolean_amounts_and_truthy_flags_without_consuming_signal(self):
        args=dict(fresh=True,reconciled=True,exposure=20,pending=10,added=10,exposure_limit=50,daily_loss=0,loss_limit=5)
        for key in args:
            gate=ResearchRiskGate();gate.armed=True
            changed=dict(args);changed[key]='true' if key in ('fresh','reconciled') else True
            self.assertFalse(gate.check('signal',**changed)[0],key)
            self.assertEqual(gate.seen,set())
            self.assertTrue(gate.check('signal',**args)[0])
