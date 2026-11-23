import math
import unittest

from research import ResearchRiskGate, _short

ARGS = dict(fresh=True, reconciled=True, exposure=0, pending=0, added=1,
            exposure_limit=100, daily_loss=0, loss_limit=10)


class KillTests(unittest.TestCase):
    def setUp(self):
        self.gate = ResearchRiskGate()
        self.gate.armed = True

    def test_legacy_call_is_unknown_exposure(self):
        r = self.gate.kill(['p1'])
        self.assertEqual(r['cancelRequests'], ['p1'])
        self.assertEqual(r['exitRequests'], [])
        self.assertEqual(r['exposureStatus'], 'UNKNOWN_NOT_FLATTENED')
        self.assertFalse(r['positionsClosed'])

    def test_empty_positions_list_reports_no_open_positions(self):
        r = self.gate.kill([], open_positions=[])
        self.assertEqual(r['exposureStatus'], 'NO_OPEN_POSITIONS_REPORTED')
        self.assertFalse(r['positionsClosed'])
        self.assertEqual(r['exitRequests'], [])
        self.assertEqual(r['rejectedPositions'], [])

    def test_exit_intents_opposite_side_never_submitted(self):
        r = self.gate.kill(['p1'], open_positions=[
            {'symbol': 'AAA', 'quantity': 10, 'side': 'buy'},
            {'symbol': 'BBB', 'quantity': 5, 'side': 'SELL'}])
        self.assertEqual(r['exposureStatus'], 'FLATTEN_REQUESTED')
        self.assertFalse(r['positionsClosed'])
        by = {e['symbol']: e for e in r['exitRequests']}
        self.assertEqual(by['AAA']['side'], 'SELL')
        self.assertEqual(by['BBB']['side'], 'BUY')
        self.assertEqual(by['AAA']['quantity'], 10)
        self.assertTrue(all(e['intentOnly'] and not e['submitted'] for e in r['exitRequests']))

    def test_duplicates_same_side_merge(self):
        r = self.gate.kill([], open_positions=[
            {'symbol': 'AAA', 'quantity': 4, 'side': 'BUY'},
            {'symbol': 'AAA', 'quantity': 6, 'side': 'BUY'}])
        self.assertEqual(len(r['exitRequests']), 1)
        self.assertEqual(r['exitRequests'][0]['quantity'], 10)

    def test_invalid_rows_skipped_and_reported_never_raise(self):
        bad = [
            {'symbol': 'A', 'quantity': True, 'side': 'BUY'},
            {'symbol': 'A', 'quantity': float('nan'), 'side': 'BUY'},
            {'symbol': 'A', 'quantity': math.inf, 'side': 'BUY'},
            {'symbol': 'A', 'quantity': -1, 'side': 'BUY'},
            {'symbol': 'A', 'quantity': 0, 'side': 'BUY'},
            {'symbol': 'A', 'quantity': '5', 'side': 'BUY'},
            {'symbol': 'A', 'quantity': 1, 'side': 'HOLD'},
            {'symbol': '', 'quantity': 1, 'side': 'BUY'},
            {'quantity': 1, 'side': 'BUY'},
            'not-a-dict',
        ]
        for pos in bad:
            gate = ResearchRiskGate()
            gate.armed = True
            r = gate.kill(['p1'], open_positions=[pos])
            self.assertTrue(gate.killed, repr(pos))
            self.assertFalse(gate.armed)
            self.assertEqual(r['exitRequests'], [])
            self.assertEqual(len(r['rejectedPositions']), 1, repr(pos))
            self.assertEqual(r['rejectedPositions'][0]['index'], 0)
            self.assertEqual(r['exposureStatus'], 'UNKNOWN_NOT_FLATTENED')
            self.assertFalse(r['positionsClosed'])
            self.assertEqual(r['cancelRequests'], ['p1'])

    def test_bad_row_does_not_suppress_other_exits_or_cancels(self):
        r = self.gate.kill(['p1', 'p2'], open_positions=[
            {'symbol': 'GOOD', 'quantity': 3, 'side': 'BUY'},
            {'symbol': 'BAD', 'quantity': -2, 'side': 'BUY'}])
        self.assertEqual([e['symbol'] for e in r['exitRequests']], ['GOOD'])
        self.assertEqual(len(r['rejectedPositions']), 1)
        self.assertEqual(r['cancelRequests'], ['p1', 'p2'])
        self.assertEqual(r['exposureStatus'], 'UNKNOWN_NOT_FLATTENED')

    def test_conflicting_sides_emit_no_intent_for_that_symbol_only(self):
        r = self.gate.kill([], open_positions=[
            {'symbol': 'A', 'quantity': 1, 'side': 'BUY'},
            {'symbol': 'A', 'quantity': 1, 'side': 'SELL'},
            {'symbol': 'B', 'quantity': 2, 'side': 'BUY'}])
        self.assertEqual([e['symbol'] for e in r['exitRequests']], ['B'])
        self.assertEqual([x['symbol'] for x in r['rejectedPositions']], ['A'])
        self.assertEqual(r['exposureStatus'], 'UNKNOWN_NOT_FLATTENED')
        self.assertTrue(self.gate.killed)

    def test_non_list_positions_no_exits_unknown(self):
        for bad in ('AAA', 5, {'symbol': 'A'}):
            gate = ResearchRiskGate()
            r = gate.kill(['p1'], open_positions=bad)
            self.assertEqual(r['exitRequests'], [])
            self.assertEqual(len(r['rejectedPositions']), 1)
            self.assertEqual(r['exposureStatus'], 'UNKNOWN_NOT_FLATTENED')
            self.assertTrue(gate.killed)

    def test_bad_pending_ids_never_raise(self):
        for bad in (None, 5, object(), 'p1'):
            gate = ResearchRiskGate()
            gate.armed = True
            r = gate.kill(bad)
            self.assertTrue(gate.killed)
            self.assertFalse(gate.armed)
            self.assertIsInstance(r['cancelRequests'], list)
        r = ResearchRiskGate().kill(['ok', None, 7, '', 'ok2'])
        self.assertEqual(r['cancelRequests'], ['ok', 'ok2'])
        self.assertEqual(len(r['rejectedCancelIds']), 3)

    def test_hostile_iter_pending_ids_contained(self):
        class Hostile(list):
            def __iter__(self):
                raise RuntimeError('boom')
        r = self.gate.kill(Hostile(['p1']), open_positions=[{'symbol': 'A', 'quantity': 1, 'side': 'BUY'}])
        self.assertTrue(self.gate.killed)
        self.assertFalse(self.gate.armed)
        self.assertEqual(r['cancelRequests'], [])
        self.assertEqual(len(r['rejectedCancelIds']), 1)
        self.assertEqual([e['symbol'] for e in r['exitRequests']], ['A'])

    def test_hostile_rows_isolated_valid_rows_still_exit(self):
        class BadDict(dict):
            def get(self, *a, **k):
                raise RuntimeError('boom')
        r = self.gate.kill(['p1'], open_positions=[
            {'symbol': 'A', 'quantity': 10 ** 400, 'side': 'BUY'},
            BadDict(symbol='B', quantity=1, side='BUY'),
            {'symbol': 'GOOD', 'quantity': 2, 'side': 'SELL'},
            {'symbol': 'GOOD2', 'quantity': 1.5, 'side': 'BUY'}])
        self.assertEqual(sorted(e['symbol'] for e in r['exitRequests']), ['GOOD', 'GOOD2'])
        self.assertEqual(sorted(x['index'] for x in r['rejectedPositions']), [0, 1])
        self.assertEqual(r['exposureStatus'], 'UNKNOWN_NOT_FLATTENED')
        self.assertEqual(r['cancelRequests'], ['p1'])

    def test_id_dedup_and_bare_string(self):
        self.assertEqual(ResearchRiskGate().kill(['a', 'a', 'b'])['cancelRequests'], ['a', 'b'])
        r = ResearchRiskGate().kill('only')
        self.assertEqual(r['cancelRequests'], ['only'])
        self.assertEqual(r['rejectedCancelIds'], [])

    def test_short_caps_repr(self):
        self.assertEqual(_short('x' * 1000), repr('x' * 1000)[:40] + '...')
        self.assertEqual(len(_short('x' * 1000)), 43)
        self.assertEqual(_short('ab'), "'ab'")
        class NoRepr:
            def __repr__(self):
                raise RuntimeError
        self.assertEqual(_short(NoRepr()), '<unrepresentable>')
        r = ResearchRiskGate().kill([], open_positions=['y' * 1000])
        self.assertLess(len(r['rejectedPositions'][0]['reason']), 100)

    def test_check_refuses_after_kill_with_positions(self):
        self.gate.kill([], open_positions=[{'symbol': 'A', 'quantity': 1, 'side': 'BUY'}])
        self.assertFalse(self.gate.check('s', **ARGS)[0])
        self.gate.armed = True  # even if re-armed, killed blocks
        self.assertFalse(self.gate.check('s2', **ARGS)[0])


if __name__ == '__main__':
    unittest.main()
