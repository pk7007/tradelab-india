import datetime as dt
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import deployment_state as ds
import live_readiness as lr

OWNER = dict(by='owner', text='I approve micro-live with Rs 1,000 under the written plan.')
NOW = dt.datetime(2026, 12, 1, 10, 0, tzinfo=dt.timezone.utc)


def eligible(**changes):
    report = dict(generatedAt=(NOW - dt.timedelta(hours=1)).isoformat(), score=92, decision=lr.MICRO_LIVE,
                  blockers=[dict(id=gate, status='blocked' if gate == lr.OWNER_GATE else 'clear') for gate in lr.GATE_IDS])
    report.update(changes)
    return report


class StateMachineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'deployment.sqlite'
        self.machine = self.open(self.path)

    @staticmethod
    def open(path):
        return ds.DeploymentState(path, clock=lambda: NOW)

    def walk_to(self, target, machine=None):
        machine = machine or self.machine
        for state in ds.LADDER[1:ds.LADDER.index(target) + 1]:
            kwargs = {}
            if state == 'MICRO_LIVE_PENDING_APPROVAL':
                kwargs['readiness'] = eligible()
            if state in ds.APPROVAL_REQUIRED:
                kwargs.update(actor='owner', approval=OWNER)
            machine.transition(state, reason='test step', **kwargs)

    def test_starts_in_development_with_live_disabled(self):
        self.assertEqual(self.machine.state, 'DEVELOPMENT')
        self.assertFalse(self.machine.live_enabled)

    def test_no_stage_may_be_skipped(self):
        with self.assertRaisesRegex(ValueError, 'not allowed'):
            self.machine.transition('PAPER', reason='skip')
        self.walk_to('PAPER')
        with self.assertRaisesRegex(ValueError, 'not allowed'):
            self.machine.transition('MICRO_LIVE', reason='skip', actor='owner', approval=OWNER)

    def test_pending_approval_needs_a_complete_fresh_eligible_report(self):
        self.walk_to('SHADOW')
        forged = [None, dict(decision=lr.MICRO_LIVE, blockers=[]), eligible(decision='NOT READY'), eligible(score=89),
                  eligible(score=True), eligible(score=float('nan')), eligible(score=float('inf')), eligible(score=1e9), eligible(generatedAt=(NOW - dt.timedelta(hours=25)).isoformat()),
                  eligible(generatedAt=(NOW + dt.timedelta(hours=1)).isoformat()), eligible(generatedAt='2026-12-01T09:00:00'),
                  eligible(generatedAt='yesterday'),
                  eligible(blockers=[dict(id=g, status='clear') for g in lr.GATE_IDS if g != 'net_expectancy']),
                  eligible(blockers=[dict(id=g, status='blocked' if g == 'net_expectancy' else 'clear') for g in lr.GATE_IDS])]
        for report in forged:
            with self.assertRaisesRegex(ValueError, 'readiness report'):
                self.machine.transition('MICRO_LIVE_PENDING_APPROVAL', reason='x', readiness=report)
        self.machine.transition('MICRO_LIVE_PENDING_APPROVAL', reason='eligible', readiness=eligible())
        evidence = self.machine.history()[-1]['evidence']
        self.assertEqual(evidence['score'], 92)
        self.assertEqual(len(evidence['sha256']), 64)

    def test_a_real_assess_report_is_accepted_once_every_other_gate_clears(self):
        evidence = {c['id']: dict(status='pass', source='live_readiness.py') for c in lr.CRITERIA}
        perf = dict(tradeCount=400, tradingDays=500, sessions=600, sharpe=2.0, sortino=2.5, profitFactor=1.8, maxDrawdown=0.04,
                    calmar=2.0, expectancy=1.0, netPnl=400.0)
        report = lr.assess(evidence, perf, 70, 15, root=Path(__file__).resolve().parents[1], now=NOW)
        self.assertEqual(report['decision'], lr.MICRO_LIVE)
        self.walk_to('SHADOW')
        self.machine.transition('MICRO_LIVE_PENDING_APPROVAL', reason='real report', readiness=report)

    def test_real_money_states_need_the_owner_and_an_agent_can_never_approve(self):
        self.walk_to('MICRO_LIVE_PENDING_APPROVAL')
        for actor, approval in (('agent', OWNER), ('system', OWNER), ('owner', None), ('owner', dict(by='agent', text='ok')),
                                ('owner', dict(by='owner', text='  ')), ('owner', dict(by='owner', text=5))):
            with self.assertRaisesRegex(ValueError, 'owner approval'):
                self.machine.transition('MICRO_LIVE', reason='x', actor=actor, approval=approval)
        self.assertEqual(self.machine.state, 'MICRO_LIVE_PENDING_APPROVAL')
        self.machine.transition('MICRO_LIVE', reason='owner approved', actor='owner', approval=OWNER)
        self.assertTrue(self.machine.live_enabled)
        self.assertEqual(self.machine.history()[-1]['approval'], OWNER)

    def test_leaving_emergency_needs_the_owner_and_suspension_goes_back_through_validation(self):
        self.machine.transition('EMERGENCY_STOP', reason='kill switch', actor='system')
        self.assertFalse(self.machine.live_enabled)
        with self.assertRaisesRegex(ValueError, 'owner approval'):
            self.machine.transition('SUSPENDED', reason='x', actor='agent')
        self.machine.transition('SUSPENDED', reason='reviewed', actor='owner', approval=OWNER)
        for target in ('PAPER', 'SHADOW', 'MICRO_LIVE'):
            with self.assertRaisesRegex(ValueError, 'not allowed'):
                self.machine.transition(target, reason='x', actor='owner', approval=OWNER)
        self.machine.transition('VALIDATION', reason='revalidate')

    def test_a_risk_breach_suspends_a_critical_one_stops_and_neither_ever_raises(self):
        self.walk_to('MICRO_LIVE')
        self.assertEqual(self.machine.risk_breach('daily loss limit', critical=False), 'SUSPENDED')
        self.assertEqual(self.machine.risk_breach('again', critical=False), 'SUSPENDED')
        self.assertEqual(self.machine.risk_breach('position mismatch', critical=True), 'EMERGENCY_STOP')
        self.assertEqual(self.machine.risk_breach('more', critical=True), 'EMERGENCY_STOP')
        self.assertEqual(self.machine.risk_breach('minor while stopped', critical=False), 'EMERGENCY_STOP')
        self.assertEqual(self.machine.state, 'EMERGENCY_STOP')

    def test_a_material_change_forces_revalidation_and_is_always_recorded(self):
        self.walk_to('PAPER')
        self.assertEqual(self.machine.material_change('model', 'retrained'), 'VALIDATION')
        self.walk_through('PAPER', 'SHADOW')
        self.assertEqual(self.machine.material_change('strategy', 'new exit rule'), 'VALIDATION')
        self.walk_through('PAPER', 'SHADOW')
        self.machine.transition('MICRO_LIVE_PENDING_APPROVAL', reason='r', readiness=eligible())
        self.assertEqual(self.machine.material_change('execution', 'new adapter'), 'SUSPENDED')
        before = len(self.machine.history())
        self.assertEqual(self.machine.material_change('risk', 'changed daily loss'), 'SUSPENDED')
        self.assertEqual(len(self.machine.history()), before + 1)
        fresh = self.open(Path(self.folder.name) / 'dev.sqlite')
        fresh.material_change('risk', 'limit edit during development')
        self.assertIn('Material risk change', fresh.history()[-1]['reason'])
        with self.assertRaises(ValueError):
            self.machine.material_change('mood', 'x')
        self.assertEqual(self.machine.material_change('risk', ''), 'SUSPENDED')            # never refused
        self.assertEqual(self.machine.material_change('risk', 'x' * 5000), 'SUSPENDED')
        self.assertLessEqual(len(self.machine.history()[-1]['reason']), 400)
        paper = self.open(Path(self.folder.name) / 'long.sqlite')
        self.walk_to('PAPER', paper)
        self.assertEqual(paper.material_change('strategy', 'y' * 5000), 'VALIDATION')

    def walk_through(self, *states):
        for state in states:
            self.machine.transition(state, reason='r')

    def test_a_restart_never_resumes_pending_real_money_or_scaling_states(self):
        for target in ('MICRO_LIVE_PENDING_APPROVAL', 'MICRO_LIVE', 'CONTROLLED_LIVE', 'SCALING_PENDING_APPROVAL'):
            path = Path(self.folder.name) / ('%s.sqlite' % target)
            machine = self.open(path)
            self.walk_to(target, machine)
            again = self.open(path)
            self.assertEqual(again.state, 'SUSPENDED', target)
            self.assertFalse(again.live_enabled)
            self.assertEqual(again.history()[-1]['reason'], 'Process restart: real-money states never resume automatically.')
        paper = Path(self.folder.name) / 'paper.sqlite'
        self.walk_to('PAPER', self.open(paper))
        self.assertEqual(self.open(paper).state, 'PAPER')

    def test_every_transition_is_persisted_and_audited(self):
        self.walk_to('PAPER')
        history = self.open(self.path).history()
        self.assertEqual([h['to'] for h in history], ['BACKTEST', 'VALIDATION', 'PAPER'])
        self.assertTrue(all(h['at'] and h['actor'] and h['reason'] for h in history))
        for bad in ('', '   ', 'x' * 501, None):
            with self.assertRaises(ValueError):
                self.machine.transition('SHADOW', reason=bad)
        with self.assertRaises(ValueError):
            self.machine.transition('NOT_A_STATE', reason='x')
        with self.assertRaises(ValueError):
            self.machine.transition('SHADOW', reason='x', actor='root')

    def test_scaling_needs_its_own_owner_approval(self):
        self.walk_to('MICRO_LIVE')
        with self.assertRaisesRegex(ValueError, 'owner approval'):
            self.machine.transition('CONTROLLED_LIVE', reason='x', actor='agent', approval=OWNER)
        self.machine.transition('CONTROLLED_LIVE', reason='20 live days reviewed', actor='owner', approval=OWNER)
        self.machine.transition('SCALING_PENDING_APPROVAL', reason='request scale')
        with self.assertRaisesRegex(ValueError, 'owner approval'):
            self.machine.transition('CONTROLLED_LIVE', reason='scale', actor='agent', approval=OWNER)

    def test_a_corrupted_stored_state_fails_closed_and_is_recorded(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE deployment SET state='LIVE_NOW'")
            db.commit()
        again = self.open(self.path)
        self.assertEqual(again.state, 'SUSPENDED')
        self.assertEqual(again.history()[-1]['reason'], 'Unknown stored state; failing closed.')
        self.assertEqual(again.history()[-1]['origin'], 'LIVE_NOW')
        self.assertFalse(again.live_enabled)


if __name__ == '__main__':
    unittest.main()
