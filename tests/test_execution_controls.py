import copy
from pathlib import Path
import tempfile
import unittest

from automation import Coordinator
from test_automation import CONFIG,SNAP

ACCOUNT='broker'
SCOPE='NSE:INFY:MIS'
AT='2026-01-02T10:00:00+05:30'
CALENDAR=dict(exchange='NSE',segment='EQ',source='https://example.invalid/calendar',availableAt='2026-01-01T00:00:00+05:30',
    sessions={'2026-01-02':dict(open='2026-01-02T09:15:00+05:30',close='2026-01-02T15:30:00+05:30')})


class Broker:
    mode='offline-mock'
    def __init__(self):
        self.account=ACCOUNT;self.revision=1;self.received=AT
        self.positions={SCOPE:6};self.orders=[];self.calls=0;self.cancels=0
        self.timeout=False;self.accept=True
    def submit(self,intent):
        return 'entry'
    def snapshot(self,account):
        return dict(account=self.account,revision=self.revision,receivedAt=self.received,
                    positions=copy.deepcopy(self.positions),orders=copy.deepcopy(self.orders))
    def place_protective(self,request):
        self.calls+=1
        identity='stop-'+str(self.calls)
        if self.accept:
            self.orders.append(dict(request,id=identity,filled=0,state='TRIGGER PENDING'))
            self.revision+=1
        if self.timeout:raise TimeoutError('private-provider-message')
        return identity
    def cancel(self,identity):
        self.cancels+=1
        next(row for row in self.orders if row['id']==identity)['state']='CANCELLED'
        self.revision+=1
        return identity


class ExecutionControlTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'oms.sqlite'
        self.engine=Coordinator(self.path)
        self.engine.save(CONFIG|dict(units=10))
        self.engine.funding.reconcile(ACCOUNT,10000,{})
        self.engine.state='running';self.engine.reconciled=True
        self.entry=self.engine.prepare('entry',1,'INFY',10,100,SNAP|dict(fundingAccount=ACCOUNT))
        self.broker=Broker()
        self.engine.submit_mock(self.entry,self.broker)
        self.engine.reconcile_mock([dict(id=self.entry,broker_id='entry',state='PARTIAL',filled=6)])
    def protect(self,**values):
        args=dict(trigger_price='95',limit_price='94.95',tick_size='.05',as_of=AT)
        args.update(values)
        return self.engine.protective_mock(ACCOUNT,SCOPE,self.broker,**args)
    def observe(self):
        return self.engine.controls.observe(ACCOUNT,self.broker,as_of=AT)
    def kill_active(self):
        return next(row['active'] for row in self.engine.controls.status()['kills'] if row['account']==ACCOUNT)
    def test_cross_instance_kill_revokes_prepared_buy_and_survives_restart(self):
        self.engine.state='running';self.engine.reconciled=True
        second=self.engine.prepare('second',1,'INFY',10,100,SNAP|dict(fundingAccount=ACCOUNT))
        Coordinator(self.path).emergency_stop_mock(ACCOUNT,'Operator emergency.')
        self.engine.state='running';self.engine.reconciled=True
        calls=self.broker.calls
        with self.assertRaisesRegex(ValueError,'emergency'):self.engine.submit_mock(second,self.broker)
        with self.assertRaisesRegex(ValueError,'emergency'):
            self.engine.prepare('third',1,'INFY',10,100,SNAP|dict(fundingAccount=ACCOUNT))
        self.assertEqual(self.broker.calls,calls)
        self.assertTrue(self.kill_active())
    def test_partial_entry_and_partial_protective_fill_use_actual_remaining_position(self):
        result=self.protect()
        self.assertEqual(result['state'],'ACKNOWLEDGED')
        self.assertEqual(result['quantity'],6)
        self.assertEqual(self.protect()['state'],'COVERED')
        self.broker.orders[0].update(state='PARTIAL',filled=3)
        self.broker.positions[SCOPE]=3;self.broker.revision+=1
        self.assertEqual(self.protect()['quantity'],3)
        self.assertEqual(self.broker.calls,1)
    def test_timeout_after_acceptance_reconciles_without_resubmission(self):
        self.broker.timeout=True
        result=self.protect()
        self.assertEqual(result['state'],'UNKNOWN')
        self.assertTrue(self.kill_active())
        self.assertEqual(self.protect()['state'],'COVERED')
        self.assertEqual(self.broker.calls,1)
        self.assertNotIn('private-provider-message',str(self.engine.controls.status()))
    def test_timeout_before_acceptance_blocks_repeat_and_restart_preserves_unknown(self):
        self.broker.timeout=True;self.broker.accept=False
        self.assertEqual(self.protect()['state'],'UNKNOWN')
        other=Coordinator(self.path)
        with self.assertRaisesRegex(ValueError,'reconciliation'):
            other.protective_mock(ACCOUNT,SCOPE,self.broker,trigger_price=95,limit_price=94.95,tick_size=.05,as_of=AT)
        self.assertEqual(self.broker.calls,1)
    def test_missing_previously_confirmed_stop_becomes_unknown_and_latches_kill(self):
        self.protect();self.observe()
        self.broker.orders=[];self.broker.revision+=1
        self.observe()
        state=self.engine.controls.status()
        self.assertEqual(state['actions'][0]['state'],'UNKNOWN')
        self.assertTrue(self.kill_active())
        self.engine.state='running';self.engine.reconciled=True
        with self.assertRaisesRegex(ValueError,'emergency'):
            self.engine.prepare('new-entry',1,'INFY',10,100,SNAP|dict(fundingAccount=ACCOUNT))
    def test_closed_roundtrip_cannot_authorize_protection_of_foreign_position(self):
        self.protect()
        self.broker.orders[0].update(state='COMPLETE',filled=6)
        self.broker.positions[SCOPE]=0;self.broker.revision+=1
        self.observe()
        self.broker.positions[SCOPE]=6;self.broker.revision+=1
        with self.assertRaisesRegex(ValueError,'Unowned'):self.protect()
        self.assertEqual(self.broker.calls,1)
        self.assertTrue(self.kill_active())
    def test_oversized_or_orphan_exit_is_not_adopted_as_owned_protection(self):
        self.broker.orders=[dict(id='foreign',instrument=SCOPE,side='SELL',kind='SL',
            quantity=7,filled=0,state='OPEN',triggerPrice='95',limitPrice='94.95')]
        self.broker.revision+=1
        with self.assertRaisesRegex(ValueError,'exceeds'):self.protect()
        self.assertTrue(self.kill_active());self.assertEqual(self.broker.calls,0)
    def test_rejected_stop_is_uncovered_and_cancel_confirmed_before_replacement(self):
        self.protect();self.broker.orders[0].update(state='REJECTED');self.broker.revision+=1
        self.observe();self.assertTrue(self.kill_active())
        # A new observation may legitimately authorize a new protective intent.
        self.broker.orders[0]['state']='CANCELLED';self.broker.revision+=1
        self.observe()
        self.protect()
        self.assertEqual(self.broker.calls,2)
        current=self.broker.orders[-1]['id']
        response=self.engine.controls.cancel_protection_mock(ACCOUNT,current,self.broker,as_of=AT)
        self.assertNotEqual(response['state'],'COMPLETE')
        self.observe()
        self.assertEqual(self.engine.controls.status()['actions'][0]['state'],'CANCELLED')
        self.assertEqual(self.broker.positions[SCOPE],6)
    def test_operator_review_requires_flat_confirmed_account_and_never_auto_arms(self):
        self.protect();self.engine.emergency_stop_mock(ACCOUNT,'Test incident.')
        with self.assertRaises(ValueError):
            self.engine.controls.rearm_mock(ACCOUNT,self.broker,operator='agent:auto',as_of=AT)
        with self.assertRaises(ValueError):
            self.engine.controls.rearm_mock(ACCOUNT,self.broker,operator='human:operator',as_of=AT)
        self.engine.reconcile_mock([dict(id=self.entry,broker_id='entry',state='CANCELLED',filled=6)])
        self.broker.orders[0].update(state='COMPLETE',filled=6);self.broker.positions[SCOPE]=0;self.broker.revision+=1
        self.engine.controls.rearm_mock(ACCOUNT,self.broker,operator='human:operator',as_of=AT)
        self.assertFalse(self.kill_active())
        self.assertEqual(self.engine.state,'disabled')
        self.assertFalse(self.engine.reconciled)
    def test_clock_cutoff_squareoff_and_restart_escalate_without_price_or_fill(self):
        self.engine.controls.configure_session(ACCOUNT,CALENDAR,day='2026-01-02',as_of=AT,
            entry_cutoff='14:45',square_off='15:10',escalate='15:18')
        self.assertEqual(self.engine.session_tick_mock(ACCOUNT,as_of='2026-01-02T14:45:00+05:30')['phase'],'ENTRY_BLOCKED')
        before=self.engine.status()['intents']
        self.assertEqual(self.engine.session_tick_mock(ACCOUNT,as_of='2026-01-02T15:10:00+05:30')['phase'],'EXIT_REQUIRED')
        other=Coordinator(self.path)
        self.assertEqual(other.session_tick_mock(ACCOUNT,as_of='2026-01-02T15:18:00+05:30')['phase'],'ESCALATED')
        self.assertEqual(other.status()['intents'],before)
        actions=other.controls.status()['actions']
        self.assertEqual(actions[0]['kind'],'SESSION_EXIT_REQUIRED')
        self.assertEqual(actions[0]['state'],'NEEDS_EVIDENCE')
        self.assertTrue(self.kill_active());self.assertEqual(self.broker.calls,0)
    def test_snapshot_identity_staleness_revision_and_tick_checks(self):
        for kwargs in (dict(trigger_price=True),dict(limit_price='95.01'),dict(tick_size=0)):
            with self.assertRaises(ValueError):self.protect(**kwargs)
        self.broker.account='foreign'
        with self.assertRaisesRegex(ValueError,'account'):self.protect()
        self.broker.account=ACCOUNT;self.observe()
        self.broker.revision=0
        with self.assertRaises(ValueError):self.observe()
        self.broker.revision=2;self.broker.received='2026-01-02T09:59:00+05:30'
        with self.assertRaisesRegex(ValueError,'Stale'):self.observe()
