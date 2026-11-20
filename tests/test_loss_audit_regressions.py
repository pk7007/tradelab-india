"""Offline loss-audit regressions; no broker or active account access."""
import datetime as dt
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from strategy_lab import StrategyLab, forward_evidence
from intraday_contract import advance
from test_intraday_paper import CONFIG


def sessions(start, count=60):
    return [dict(date=(start + dt.timedelta(days=i)).isoformat() + 'T09:15:00+05:30')
            for i in range(count)]


class HoldoutIndependenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.lab = StrategyLab(Path(self.directory.name) / 'lab.sqlite')
        self.request = dict(hypothesis='Frozen hypothesis', baselineConfig=CONFIG,
                            criteria=dict(maxDrawdownPct=10),
                            provenance=dict(datasetId='fixture', datasetVersion='1', source='synthetic',
                                            corporateActions='none', universe='DEMO', benchmark='baseline'))
        report = dict(fills=[], returnPct=0, maxDrawdownPct=0, fees=0,
                      openQuantity=0, pending=None, ledgerMatches=True)
        mock = patch('strategy_lab.evaluate_intraday', return_value=report)
        self.replay = mock.start()
        self.addCleanup(mock.stop)

    def evaluate_new(self, start, stage='final'):
        hypothesis = self.lab.register(self.request)['id']
        candidate = self.lab.add_candidate(hypothesis, dict(targetMultiple=3))['id']
        return self.lab.evaluate(hypothesis, candidate, sessions(start), True, stage)

    def test_shifted_final_window_cannot_reuse_exposed_sessions(self):
        self.evaluate_new(dt.date(2025, 1, 1))
        calls = self.replay.call_count
        with self.assertRaisesRegex(ValueError, 'already opened'):
            self.evaluate_new(dt.date(2025, 1, 2))
        self.assertEqual(self.replay.call_count, calls)
        self.assertEqual(len(self.lab.status()['evaluations']), 1)

    def test_nonoverlapping_final_windows_remain_available(self):
        self.evaluate_new(dt.date(2025, 1, 1))
        result = self.evaluate_new(dt.date(2025, 4, 1))
        self.assertEqual(result['state'], 'rejected')

    def test_validation_cannot_reuse_an_exposed_final_window(self):
        self.evaluate_new(dt.date(2025, 1, 1))
        with self.assertRaisesRegex(ValueError, 'already opened'):
            self.evaluate_new(dt.date(2025, 1, 22), stage='validation')

    def test_legacy_seal_without_dates_fails_closed(self):
        self.evaluate_new(dt.date(2025, 1, 1))
        with self.lab.db() as db:
            db.execute('DELETE FROM sealed_windows')
        with self.assertRaisesRegex(ValueError, 'already opened'):
            self.evaluate_new(dt.date(2025, 4, 1))

    def test_final_cannot_relabel_prior_validation_as_independent(self):
        self.evaluate_new(dt.date(2025, 1, 1), stage='validation')
        calls = self.replay.call_count
        # Validation Jan21-Feb9 becomes the shifted trial's final Jan21-Feb9.
        with self.assertRaisesRegex(ValueError, 'already opened'):
            self.evaluate_new(dt.date(2024, 12, 12))
        self.assertEqual(calls, self.replay.call_count)

    def test_validation_can_repeat_and_exposure_survives_restart(self):
        self.evaluate_new(dt.date(2025, 1, 1), stage='validation')
        self.evaluate_new(dt.date(2025, 1, 1), stage='validation')
        self.lab = StrategyLab(self.lab.path)
        with self.assertRaisesRegex(ValueError, 'already opened'):
            self.evaluate_new(dt.date(2024, 12, 12))
        # Disjoint final evidence remains available after validation.
        self.evaluate_new(dt.date(2025, 1, 1))

    def test_legacy_validation_without_dates_fails_closed_for_final(self):
        self.evaluate_new(dt.date(2025, 1, 1), stage='validation')
        with self.lab.db() as db:
            db.execute('DELETE FROM exposed_windows')
        with self.assertRaisesRegex(ValueError, 'already opened'):
            self.evaluate_new(dt.date(2025, 4, 1))


class IntradayExecutionAssumptionTests(unittest.TestCase):
    def state(self, **changes):
        config = dict(CONFIG, **changes)
        return dict(config=config, cash=1000, quantity=0, basis=0, fees=0, realized=0,
                    equity=1000, pending=dict(side='BUY', signalAt='2026-01-02T10:50:00+05:30'),
                    lastBar='2026-01-02T10:50:00+05:30', closes=[], day='2026-01-02',
                    dayStartEquity=1000, dayLoss=0, riskHalted=False, completedTrades=0)

    def candle(self, **changes):
        return dict(dict(date='2026-01-02T10:55:00+05:30', open=100, high=100,
                         low=100, close=100, volume=10000), **changes)

    def test_next_open_entry_does_not_use_current_close_as_entry_price(self):
        state = self.state()
        events = advance(state, self.candle(close=100.5, high=101))
        fill = next(event for event in events if event['type'] == 'fill')
        self.assertAlmostEqual(fill['price'], 100.05)
        self.assertLess(fill['signalAt'], fill['bar'])

    def test_both_levels_after_entry_choose_stop_and_charge_both_sides(self):
        state = self.state()
        events = advance(state, self.candle(high=110, low=90))
        fills = [event for event in events if event['type'] == 'fill']
        self.assertEqual([fill['side'] for fill in fills], ['BUY', 'SELL'])
        self.assertIn('stop-first', fills[1]['reason'])
        cashflow = sum((1 if fill['side'] == 'SELL' else -1) * fill['quantity'] * fill['price']
                       - fill['fee'] for fill in fills)
        self.assertAlmostEqual(state['realized'], cashflow)
        self.assertAlmostEqual(state['equity'] - 1000, cashflow)

    def test_entry_and_protection_share_one_candle_liquidity_capacity(self):
        state = self.state(participationPct=50)
        events = advance(state, self.candle(volume=20, high=110, low=90))
        fills = [event for event in events if event['type'] == 'fill']
        self.assertEqual(sum(fill['quantity'] for fill in fills), 10)
        self.assertEqual(state['quantity'], 8)
        self.assertEqual(state['pending']['side'], 'SELL')

    def test_halted_day_blocks_entry_until_next_flat_session(self):
        state = self.state()
        state.update(cash=890, equity=890, riskHalted=True)
        self.assertFalse(any(event['type'] == 'fill' for event in advance(state, self.candle())))
        self.assertTrue(state['riskHalted'])
        advance(state, self.candle(date='2026-01-05T09:15:00+05:30'))
        self.assertFalse(state['riskHalted'])
        self.assertEqual(state['dayStartEquity'], 890)


class ExecutableForwardPromotionTests(unittest.TestCase):
    def evidence(self, profit=1, revision='candidate', model='observed-quote-paper'):
        events = []; observed = set(); equity = 1000
        for trade in range(30):
            day = (dt.date(2025, 1, 1) + dt.timedelta(days=trade // 3)).isoformat()
            for side, minute in [('BUY', 15 + 10 * (trade % 3)), ('SELL', 20 + 10 * (trade % 3))]:
                stamp = day + 'T10:' + str(minute) + ':00+05:30'
                observed.add(stamp)
                if side == 'SELL': equity += profit
                events.append(dict(type='fill', bar=stamp, strategyRevision=revision, executionModel=model,
                                   side=side, quantity=1, price=100 if side == 'BUY' else 100 + profit, fee=0))
                events.append(dict(type='quote-mark', bar=stamp, strategyRevision=revision, equity=equity))
        account = dict(config=dict(capital=1000), equity=equity, fees=0, quantity=0, pending=None)
        return account, events, observed

    def test_candle_worker_receipts_cannot_qualify(self):
        account, events, observed = self.evidence(model='observed-candle-paper')
        with self.assertRaisesRegex(ValueError, 'candle fills'):
            forward_evidence(account, 'candidate', events, observed, 10)
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            forward_evidence(account, 'candidate', events, set(), 10)

    def test_old_baseline_trades_cannot_qualify_candidate(self):
        account, events, observed = self.evidence(revision='baseline')
        with self.assertRaisesRegex(ValueError, 'baseline'):
            forward_evidence(account, 'candidate', events, observed, 10)

    def test_thirty_losing_quote_trades_cannot_promote(self):
        account, events, observed = self.evidence(profit=-1)
        with self.assertRaisesRegex(ValueError, 'acceptance failed'):
            forward_evidence(account, 'candidate', events, observed, 10)

    def test_missing_fill_mark_and_unreconciled_mark_fail_closed(self):
        account, events, observed = self.evidence()
        with self.assertRaisesRegex(ValueError, 'Every forward fill'):
            forward_evidence(account, 'candidate', events[0:1] + events[2:], observed, 10)
        events[-1]['equity'] += 1
        with self.assertRaisesRegex(ValueError, 'reconcile'):
            forward_evidence(account, 'candidate', events, observed, 10)

    def test_trusted_quote_fixture_passes_financial_contract_only(self):
        account, events, observed = self.evidence()
        result = forward_evidence(account, 'candidate', events, observed, 10)
        self.assertEqual(result['completedTrades'], 30)
        self.assertEqual(result['netExpectancy'], 1)
