import ast
import unittest
from pathlib import Path

import live_mock as lm
import order_guard
from research import ResearchRiskGate

ROOT = Path(__file__).resolve().parents[1]
ORDERS = [dict(id='o1', symbol='INFY', side='BUY', quantity=10, filled=0, state='OPEN'),
          dict(id='o2', symbol='TCS', side='SELL', quantity=3, filled=3, state='COMPLETE')]


def armed_gate():
    gate = ResearchRiskGate()
    gate.armed = True
    return gate


def order(identity, symbol='INFY', side='BUY', quantity=10, filled=10, state='COMPLETE'):
    return dict(id=identity, symbol=symbol, side=side, quantity=quantity, filled=filled, state=state)


class KillTests(unittest.TestCase):
    def test_full_exits_and_cancels_confirm_closure_from_newer_evidence(self):
        broker = lm.MockBroker(positions={'INFY': 10, 'TCS': -3}, orders=ORDERS)
        gate = armed_gate()
        result = lm.kill_with_confirmation(gate, broker)
        self.assertEqual(result['closure'], 'CONFIRMED_FLAT')
        self.assertTrue(result['positionsClosed'])
        self.assertFalse(result['submittedToRealBroker'])
        self.assertEqual([c['orderId'] for c in result['cancels']], ['o1'])
        self.assertEqual({(e['symbol'], e['side'], e['quantity']) for e in result['exits']}, {('INFY', 'SELL', 10), ('TCS', 'BUY', 3)})
        self.assertEqual(broker.calls[-1], ('snapshot',))
        self.assertTrue(gate.killed)
        self.assertFalse(gate.check('s1', fresh=True, reconciled=True, exposure=0, pending=0, added=1,
                                    exposure_limit=10, daily_loss=0, loss_limit=10)[0])

    def test_an_already_flat_book_is_confirmed_without_any_request(self):
        result = lm.kill_with_confirmation(armed_gate(), lm.MockBroker())
        self.assertEqual((result['closure'], result['cancels'], result['exits']), ('CONFIRMED_FLAT', [], []))

    def test_a_partial_exit_is_not_confirmed_and_lists_the_residual(self):
        result = lm.kill_with_confirmation(armed_gate(), lm.MockBroker(positions={'INFY': 10}, exit_fill_ratio=0.5))
        self.assertEqual((result['closure'], result['residualPositions']), ('NOT_CONFIRMED', {'INFY': 5}))

    def test_a_rejected_exit_or_a_failed_cancel_is_not_confirmed(self):
        rejected = lm.kill_with_confirmation(armed_gate(), lm.MockBroker(positions={'INFY': 10}, rejected_exits={'INFY'}))
        self.assertEqual((rejected['closure'], rejected['residualPositions']), ('NOT_CONFIRMED', {'INFY': 10}))
        stuck = lm.kill_with_confirmation(armed_gate(), lm.MockBroker(orders=ORDERS, failing_cancels={'o1'}))
        self.assertEqual(stuck['closure'], 'NOT_CONFIRMED')
        self.assertEqual(stuck['cancels'], [dict(orderId='o1', outcome='FAILED', error='TimeoutError')])
        self.assertEqual(stuck['workingOrders'], ['o1'])

    def test_unknown_or_missing_order_states_count_as_working(self):
        for state in ('CANCEL PENDING', 'OPEN PENDING', 'AMO REQ RECEIVED', 'VALIDATION PENDING', 'MODIFY PENDING', None, 'WEIRD'):
            pending = order('p1', filled=0, state=state)
            broker = lm.MockBroker(orders=[pending], failing_cancels={'p1'})
            result = lm.kill_with_confirmation(armed_gate(), broker)
            self.assertEqual(result['closure'], 'NOT_CONFIRMED', state)
            self.assertEqual(result['workingOrders'], ['p1'], state)

    def test_a_stale_snapshot_after_requests_never_confirms(self):
        class Stale(lm.MockBroker):
            served = 0

            def snapshot(self):
                snap = super().snapshot()
                self.served += 1
                if self.served > 1:                                    # a cached flat answer, not newer than the kill
                    snap.update(revision=1, positions={})
                return snap
        result = lm.kill_with_confirmation(armed_gate(), Stale(positions={'INFY': 10}, rejected_exits={'INFY'}))
        self.assertEqual(result['closure'], 'NOT_CONFIRMED')
        self.assertIn('No newer broker evidence', result['problems'][0])

    def test_an_exit_is_held_while_a_same_side_order_could_not_be_cancelled(self):
        stop = order('stop-1', side='SELL', filled=0, state='TRIGGER PENDING')
        broker = lm.MockBroker(positions={'INFY': 10}, orders=[stop], failing_cancels={'stop-1'})
        result = lm.kill_with_confirmation(armed_gate(), broker)
        self.assertEqual([e['outcome'] for e in result['exits']], ['HELD'])
        self.assertNotIn('exit', [call[0] for call in broker.calls])
        self.assertEqual(result['closure'], 'NOT_CONFIRMED')

    def test_an_acknowledged_but_pending_cancel_still_holds_the_same_side_exit(self):
        class SlowCancel(lm.MockBroker):
            def cancel(self, order_id):
                self.calls.append(('cancel', order_id))
                next(o for o in self.orders if o['id'] == order_id)['state'] = 'CANCEL PENDING'
                self.revision += 1
                return order_id
        stop = order('stop-1', side='SELL', filled=0, state='TRIGGER PENDING')
        broker = SlowCancel(positions={'INFY': 10}, orders=[stop])
        result = lm.kill_with_confirmation(armed_gate(), broker)
        self.assertEqual([c['outcome'] for c in result['cancels']], ['REQUESTED'])
        self.assertEqual([e['outcome'] for e in result['exits']], ['HELD'])
        self.assertNotIn('exit', [call[0] for call in broker.calls])
        self.assertEqual(result['closure'], 'NOT_CONFIRMED')

    def test_an_exit_goes_out_once_newer_evidence_shows_the_stop_cancelled(self):
        stop = order('stop-1', side='SELL', filled=0, state='TRIGGER PENDING')
        result = lm.kill_with_confirmation(armed_gate(), lm.MockBroker(positions={'INFY': 10}, orders=[stop]))
        self.assertEqual([e['outcome'] for e in result['exits']], ['REQUESTED'])
        self.assertEqual(result['closure'], 'CONFIRMED_FLAT')

    def test_malformed_positions_in_any_snapshot_never_confirm(self):
        for bad in ([('INFY', 10)], {'INFY': 0.0}, {'INFY': '10'}, {5: 10}):
            broker = lm.MockBroker()
            original = broker.snapshot
            broker.snapshot = lambda original=original, bad=bad: dict(original(), positions=bad)
            result = lm.kill_with_confirmation(armed_gate(), broker)
            self.assertEqual(result['closure'], 'NOT_CONFIRMED', bad)
            later = lm.MockBroker(positions={'INFY': 10})
            first = later.snapshot
            calls = {'n': 0}

            def second_bad(first=first, bad=bad):
                calls['n'] += 1
                snap = first()
                return snap if calls['n'] == 1 else dict(snap, positions=bad)
            later.snapshot = second_bad
            self.assertEqual(lm.kill_with_confirmation(armed_gate(), later)['closure'], 'NOT_CONFIRMED', bad)

    def test_an_unreachable_or_malformed_broker_never_raises_and_still_kills_the_gate(self):
        brokers = [lm.MockBroker(positions={'INFY': 10}, snapshot_failures=1)]
        late = lm.MockBroker(positions={'INFY': 10})
        original = late.snapshot
        seen = {'n': 0}

        def flaky():
            seen['n'] += 1
            if seen['n'] == 2:
                raise ConnectionError('down')
            return original()
        late.snapshot = flaky
        brokers.append(late)
        malformed = lm.MockBroker(positions={'INFY': 10})
        malformed.snapshot = lambda: dict(positions={'INFY': 10}, orders=[])      # no revision
        brokers.append(malformed)
        for broker in brokers:
            gate = armed_gate()
            result = lm.kill_with_confirmation(gate, broker)
            self.assertTrue(gate.killed)
            self.assertEqual(result['closure'], 'NOT_CONFIRMED')
            self.assertTrue(result['problems'])

    def test_a_non_mock_broker_is_refused_before_it_is_touched(self):
        class RealLooking:
            mode = 'live'

            def __getattr__(self, name):
                raise AssertionError('broker touched: ' + name)

        class HostileMode:
            @property
            def mode(self):
                raise RuntimeError('boom')
        for broker in (RealLooking(), HostileMode()):
            gate = armed_gate()
            result = lm.kill_with_confirmation(gate, broker)
            self.assertTrue(gate.killed)
            self.assertEqual(result['closure'], 'NOT_CONFIRMED')
            self.assertIn('Refused', result['problems'][0])

    def test_a_position_row_the_gate_rejects_is_never_confirmed_even_if_the_book_looks_flat(self):
        class RejectingGate(ResearchRiskGate):
            def kill(self, pending_ids, open_positions=None):
                result = super().kill(pending_ids, open_positions)
                result['rejectedPositions'] = [dict(index=0, symbol='INFY', reason='Invalid quantity')]
                return result
        result = lm.kill_with_confirmation(RejectingGate(), lm.MockBroker(positions={'INFY': 10}))
        self.assertEqual(result['residualPositions'], {})
        self.assertEqual(result['closure'], 'NOT_CONFIRMED')


class ReconcileTests(unittest.TestCase):
    LEDGER = dict(positions={'INFY': 10, 'TCS': 0}, orders=[order('o1')])

    def test_matching_books_are_matched(self):
        result = lm.reconcile(self.LEDGER, dict(positions={'INFY': 10}, orders=[order('o1')]))
        self.assertEqual((result['status'], result['blockNewEntries'], result['mismatches']), ('MATCHED', False, []))

    def test_every_kind_of_mismatch_is_detected_in_a_fixture(self):
        broker = dict(positions={'INFY': 7, 'SBIN': 5}, orders=[order('o1', filled=7, state='PARTIAL'), order('manual-1', 'SBIN', quantity=5, filled=5)])
        ledger = dict(positions={'INFY': 10}, orders=[order('o1'), order('o9', side='SELL', filled=0, state='OPEN')])
        result = lm.reconcile(ledger, broker)
        kinds = sorted(m['kind'] for m in result['mismatches'])
        self.assertEqual(kinds, ['fill-mismatch', 'missing-at-broker', 'position-mismatch', 'position-mismatch', 'state-mismatch', 'unknown-at-broker'])
        self.assertEqual((result['status'], result['blockNewEntries']), ('MISMATCH', True))
        changed = lm.reconcile(self.LEDGER, dict(positions={'INFY': 10}, orders=[order('o1', side='SELL')]))
        self.assertEqual([(m['kind'], m['field']) for m in changed['mismatches']], [('order-mismatch', 'side')])

    def test_a_working_order_the_broker_cancelled_is_a_mismatch(self):
        ledger = dict(positions={}, orders=[order('o1', filled=0, state='OPEN')])
        broker = dict(positions={}, orders=[order('o1', filled=0, state='CANCELLED')])
        self.assertEqual([m['kind'] for m in lm.reconcile(ledger, broker)['mismatches']], ['state-mismatch'])

    def test_unreadable_or_incomplete_input_fails_closed_and_never_raises(self):
        for ledger, snapshot in ((None, {}), ({}, {}), (self.LEDGER, dict(positions={'INFY': 1.5}, orders=[])),
                                 (self.LEDGER, dict(positions={}, orders=[order('a'), order('a')])),
                                 (self.LEDGER, dict(positions={}, orders=['x'])),
                                 (dict(positions={}, orders=[dict(id='o1')]), dict(positions={}, orders=[dict(id='o1')]))):
            result = lm.reconcile(ledger, snapshot)
            self.assertEqual((result['status'], result['blockNewEntries']), ('UNVERIFIED', True))

    def test_a_kill_then_reconcile_round_trip_matches_a_flat_ledger(self):
        broker = lm.MockBroker(positions={'INFY': 10})
        lm.kill_with_confirmation(armed_gate(), broker)
        snapshot = broker.snapshot()
        self.assertEqual(lm.reconcile(dict(positions={}, orders=snapshot['orders']), snapshot)['status'], 'MATCHED')


class IsolationTests(unittest.TestCase):
    def test_the_mock_path_imports_nothing_that_can_reach_a_network_or_broker(self):
        tree = ast.parse((ROOT / 'live_mock.py').read_text(encoding='utf-8'))
        imported = {a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertEqual(imported, {'copy', 'itertools'})
        self.assertEqual(order_guard.scan_python((ROOT / 'live_mock.py').read_text(encoding='utf-8')), [])


if __name__ == '__main__':
    unittest.main()
