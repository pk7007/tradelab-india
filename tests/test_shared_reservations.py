import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from automation import SharedReservations, Coordinator, validate_config
from test_automation import CONFIG, SNAP, Mock


class SharedFundingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'ledger.sqlite'
        self.ledger = SharedReservations(self.path)
        self.ledger.reconcile('broker', 1000, {'NSE:INFY:CNC': 1})

    def test_two_books_compete_for_last_cash_across_connections(self):
        def attempt(book):
            try:
                SharedReservations(self.path).reserve(book,'broker',book,'NSE:INFY:CNC','BUY',1,900,10)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(attempt,['intraday','longterm'])),1)

    def test_boolean_risk_values_and_truthy_session_flags_rejected(self):
        with self.assertRaises(ValueError):validate_config(CONFIG|dict(units=True))
        engine=Coordinator(self.path);engine.save(CONFIG)
        engine.state='running';engine.reconciled=True
        for changed in (dict(loss=False),dict(inSession='yes'),dict(externalMismatch='')):
            with self.assertRaises(ValueError):engine.prepare('bar',1,'INFY',1,100,SNAP|changed)
        with self.assertRaises(ValueError):engine.prepare('bar',1,'INFY',1,True,SNAP)
        self.assertEqual(engine.status()['intents'],[])

    def test_last_share_cannot_be_sold_twice(self):
        self.ledger.reserve('a','broker','longterm','NSE:INFY:CNC','SELL',1,900)
        with self.assertRaises(ValueError):
            self.ledger.reserve('b','broker','intraday','NSE:INFY:CNC','SELL',1,900)

    def test_fees_and_sub_paise_round_up(self):
        with self.assertRaises(ValueError):
            self.ledger.reserve('a','broker','book','INFY','BUY',1,1000,.001)

    def test_timeout_and_restart_retain_full_cash_reservation(self):
        self.ledger.reserve('a','broker','book','INFY','BUY',2,900,10)
        self.ledger.settle('a','UNKNOWN',0)
        self.ledger.settle('a','PARTIAL',1)
        restored=SharedReservations(self.path)
        with self.assertRaises(ValueError):
            restored.reserve('b','broker','book','INFY','BUY',1,100)
        self.assertEqual(restored.status()['reservations'][0]['cash'],90000)

    def test_partial_cancel_requires_explicit_reconciliation(self):
        self.ledger.reserve('a','broker','book','INFY','BUY',2,900,10)
        self.ledger.settle('a','CANCELLED',1)
        with self.assertRaises(ValueError):
            self.ledger.reserve('b','broker','book','INFY','BUY',1,1)
        self.assertEqual(self.ledger.status()['accounts'][0]['cash'],54000)
        self.assertTrue(self.ledger.reconcile('broker',540,{'INFY':1}))
        self.ledger.reserve('b','broker','book','INFY','BUY',1,100)

    def test_external_mismatch_persists_across_restart(self):
        self.assertFalse(self.ledger.reconcile('broker',1000,{},external_mismatch=True))
        with self.assertRaises(ValueError):
            SharedReservations(self.path).reserve('a','broker','book','INFY','BUY',1,10)

    def test_reconcile_cannot_erase_pending_reservation(self):
        self.ledger.reserve('a','broker','book','INFY','BUY',1,900)
        self.assertFalse(self.ledger.reconcile('broker',10000,{}))
        self.assertEqual(len(self.ledger.status()['reservations']),1)

    def test_coordinator_reserves_and_retains_on_timeout(self):
        engine=Coordinator(self.path)
        engine.save(CONFIG)
        engine.state='running';engine.reconciled=True
        identity=engine.prepare('bar',1,'INFY',1,900,SNAP|{'fundingAccount':'broker','estimatedFees':10})
        engine.submit_mock(identity,Mock(True))
        self.assertEqual(engine.status()['funding']['reservations'][0]['state'],'ACTIVE')
        with self.assertRaises(ValueError):
            self.ledger.reserve('b','broker','longterm','INFY','BUY',1,100)

    def test_duplicate_reservation_is_atomic(self):
        self.ledger.reserve('a','broker','book','INFY','BUY',1,100)
        with self.assertRaises(ValueError):
            self.ledger.reserve('a','broker','book','INFY','BUY',1,100)
        self.assertEqual(len(self.ledger.status()['reservations']),1)

    def test_invalid_terminal_or_partial_fill_cannot_release(self):
        self.ledger.reserve('a','broker','book','INFY','BUY',2,900)
        for state,filled in [('COMPLETE',1),('REJECTED',1),('PARTIAL',0),('PARTIAL',2)]:
            with self.assertRaises(ValueError):
                self.ledger.settle('a',state,filled)
        self.assertEqual(self.ledger.status()['reservations'][0]['state'],'ACTIVE')

    def test_unfilled_cancel_releases_without_debit(self):
        self.ledger.reserve('a','broker','book','INFY','BUY',1,900,10)
        self.ledger.settle('a','CANCELLED',0)
        self.ledger.settle('a','CANCELLED',0)
        self.ledger.reserve('b','broker','other','INFY','BUY',1,1000)
        self.assertEqual(self.ledger.status()['accounts'][0]['cash'],100000)

    def test_missing_named_funding_account_fails_closed(self):
        engine=Coordinator(self.path);engine.save(CONFIG)
        engine.state='running';engine.reconciled=True
        with self.assertRaises(ValueError):
            engine.prepare('bar',1,'INFY',1,100,SNAP|{'fundingAccount':'unconfigured'})
        self.assertEqual(engine.status()['intents'],[])

    def test_reconciliation_cannot_complete_without_funding_record(self):
        engine=Coordinator(self.path);engine.save(CONFIG)
        engine.state='running';engine.reconciled=True
        identity=engine.prepare('bar',1,'INFY',1,100,SNAP)
        engine.submit_mock(identity,Mock())
        with engine.db() as db:
            db.execute('DELETE FROM funding_reservations WHERE id=?',(identity,))
        with self.assertRaisesRegex(ValueError,'reservation'):
            engine.reconcile_mock([dict(id=identity,broker_id='mock-order-1',state='COMPLETE',filled=1)])
        self.assertNotEqual(engine.status()['intents'][0]['state'],'COMPLETE')

    def test_late_ack_or_timeout_cannot_erase_reconciled_fills(self):
        for timeout in (False,True):
            path=Path(self.temp.name)/('race'+str(timeout)+'.sqlite')
            engine=Coordinator(path);engine.save(CONFIG)
            engine.state='running';engine.reconciled=True
            identity=engine.prepare('bar',1,'INFY',1,100,SNAP)
            class RacingBroker:
                mode='offline-mock'
                def submit(_self,intent):
                    other=Coordinator(path)
                    other.reconcile_mock([dict(id=identity,broker_id='matched',state='COMPLETE',filled=1)])
                    if timeout:
                        raise TimeoutError()
                    return 'matched'
            engine.submit_mock(identity,RacingBroker())
            row=engine.status()['intents'][0]
            self.assertEqual((row['state'],row['broker_id'],row['filled']),('COMPLETE','matched',1))

    def test_conflicting_late_ack_keeps_terminal_and_blocks_funding(self):
        engine=Coordinator(self.path);engine.save(CONFIG)
        engine.state='running';engine.reconciled=True
        identity=engine.prepare('bar',1,'INFY',1,100,SNAP)
        class RacingBroker:
            mode='offline-mock'
            def submit(_self,intent):
                other=Coordinator(engine.path)
                other.reconcile_mock([dict(id=identity,broker_id='matched',state='COMPLETE',filled=1)])
                return 'conflicting'
        engine.submit_mock(identity,RacingBroker())
        row=engine.status()['intents'][0]
        self.assertEqual((row['state'],row['broker_id'],row['filled']),('COMPLETE','matched',1))
        self.assertEqual(engine.state,'faulted')
        self.assertTrue(all(a['blocked'] for a in engine.status()['funding']['accounts']))

    def test_late_ack_preserves_partial_fill_and_full_reservation(self):
        engine=Coordinator(self.path);engine.save(CONFIG|{'units':2})
        engine.state='running';engine.reconciled=True
        identity=engine.prepare('bar',1,'INFY',2,100,SNAP)
        class RacingBroker:
            mode='offline-mock'
            def submit(_self,intent):
                other=Coordinator(engine.path)
                other.reconcile_mock([dict(id=identity,broker_id='matched',state='PARTIAL',filled=1)])
                return 'matched'
        engine.submit_mock(identity,RacingBroker())
        row=engine.status()['intents'][0]
        self.assertEqual((row['state'],row['broker_id'],row['filled']),('PARTIAL','matched',1))
        reservation=engine.status()['funding']['reservations'][0]
        self.assertEqual((reservation['state'],reservation['cash']),('ACTIVE',20000))

    def test_external_mismatch_after_prepare_blocks_submit_from_other_instance(self):
        engine=Coordinator(self.path);engine.save(CONFIG)
        engine.state='running';engine.reconciled=True
        identity=engine.prepare('bar',1,'INFY',1,100,SNAP|{'fundingAccount':'broker'})
        SharedReservations(self.path).reconcile('broker',1000,{},external_mismatch=True)
        broker=Mock()
        with self.assertRaisesRegex(ValueError,'funding reservation'):
            engine.submit_mock(identity,broker)
        self.assertEqual(broker.calls,0)
        self.assertEqual(engine.status()['intents'][0]['state'],'PREPARED')

    def test_missing_or_inactive_reservation_or_account_blocks_submit(self):
        for mutation in ('DELETE FROM funding_reservations',"UPDATE funding_reservations SET state='CANCELLED'",'DELETE FROM funding_accounts'):
            with self.subTest(mutation=mutation):
                path=Path(self.temp.name)/('case'+str(len(mutation))+'.sqlite')
                engine=Coordinator(path);engine.save(CONFIG)
                engine.state='running';engine.reconciled=True
                identity=engine.prepare('bar',1,'INFY',1,100,SNAP)
                with engine.db() as db:
                    db.execute(mutation)
                broker=Mock()
                with self.assertRaisesRegex(ValueError,'funding reservation'):
                    engine.submit_mock(identity,broker)
                self.assertEqual(broker.calls,0)

    def test_changed_cash_after_prepare_blocks_submit(self):
        engine=Coordinator(self.path);engine.save(CONFIG)
        engine.state='running';engine.reconciled=True
        identity=engine.prepare('bar',1,'INFY',1,100,SNAP)
        with engine.db() as db:
            db.execute('UPDATE funding_accounts SET cash=0')
        broker=Mock()
        with self.assertRaisesRegex(ValueError,'Funding changed'):
            engine.submit_mock(identity,broker)
        self.assertEqual(broker.calls,0)

    def test_other_uncertain_intent_blocks_prepared_submit(self):
        engine=Coordinator(self.path);engine.save(CONFIG)
        engine.state='running';engine.reconciled=True
        first=engine.prepare('bar1',1,'INFY',1,100,SNAP)
        second=engine.prepare('bar2',1,'INFY',1,100,SNAP)
        with engine.db() as db:
            db.execute("UPDATE intents SET state='UNKNOWN' WHERE id=?",(first,))
        broker=Mock()
        with self.assertRaisesRegex(ValueError,'Uncertain order'):
            engine.submit_mock(second,broker)
        self.assertEqual(broker.calls,0)
