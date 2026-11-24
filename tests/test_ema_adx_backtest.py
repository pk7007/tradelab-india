import copy
import datetime as dt
import math
import unittest

import ema_adx_backtest as bt
import ema_adx_strategy as strat

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
CONFIG = dict(capital=100000.0, units=1000, maxExposure=100000.0, maxLoss=500.0, dailyLossLimit=2000.0,
              stopDistancePct=1.0, targetMultiple=2.0, participationPct=10.0, costBps=10.0, slippageBps=5.0,
              entryEnd='14:30', squareOff='15:05')


def session_times(day):
    start = dt.datetime(2026, 1, 1 + day, 9, 15, tzinfo=IST)
    return [start + dt.timedelta(minutes=5 * k) for k in range(75)]   # 09:15 .. 15:25


def synthetic(days=10, seed=3, amp=0.08, period=120, noise_scale=0.06):
    """Deterministic multi-day 5-minute bars: a repeating up/down drift plus small noise."""
    state = seed
    def noise():
        nonlocal state
        state = (state * 1103515245 + 12345) % 2 ** 31
        return (state / 2 ** 31 - 0.5) * noise_scale
    bars, price, k = [], 100.0, 0
    for day in range(days):
        for stamp in session_times(day):
            open_ = price
            close = max(1.0, open_ + amp * math.sin(2 * math.pi * k / period) + noise())
            high = max(open_, close) + abs(noise()) * 0.5
            low = min(open_, close) - abs(noise()) * 0.5
            bars.append(dict(date=stamp.isoformat(), open=round(open_, 4), high=round(high, 4), low=round(low, 4),
                             close=round(close, 4), volume=100000))
            price = close
            k += 1
    return bars


BARS = synthetic()


class ConfigTests(unittest.TestCase):
    def test_saved_risk_limits_are_validated_by_the_existing_intraday_contract(self):
        self.assertEqual(bt.validate_config(CONFIG)['squareOff'], '15:05')
        for bad in (dict(CONFIG, maxLoss=5000.0), dict(CONFIG, squareOff='15:07'), dict(CONFIG, stopDistancePct=0),
                    dict(CONFIG, entryEnd='15:10'), dict(CONFIG, units=0), dict(CONFIG, costBps=-1)):
            with self.assertRaises(ValueError, msg=str(bad)):
                bt.validate_config(bad)

    def test_timeframe_is_five_minutes_and_declared(self):
        self.assertEqual(bt.TIMEFRAME_MINUTES, 5)
        self.assertEqual(bt.VERSION, 'ema20-50-adx14-intraday-5m-v1')


class DecisionTests(unittest.TestCase):
    def test_exit_priority_stop_then_target_then_trend_then_square_off(self):
        pos = dict(entry=100.0)
        cfg = bt.validate_config(CONFIG)
        stop, target = bt.levels(100.0, cfg)
        self.assertAlmostEqual(stop, 99.0)
        self.assertAlmostEqual(target, 102.0)
        both = dict(open=100.0, high=103.0, low=98.0, close=100.0, date='2026-01-02T10:00:00+05:30')
        self.assertEqual(bt.intrabar_exit(pos, both, cfg)['reason'], 'stop')          # stop wins a same-bar tie
        self.assertEqual(bt.intrabar_exit(pos, dict(both, low=99.5), cfg)['reason'], 'target')
        self.assertIsNone(bt.intrabar_exit(pos, dict(both, low=99.5, high=101.5), cfg))
        gap = dict(open=97.0, high=97.5, low=96.0, close=97.0, date='x')
        self.assertEqual(bt.intrabar_exit(pos, gap, cfg), dict(reason='stop', price=97.0))   # gap fills at the open
        up = dict(open=104.0, high=105.0, low=103.0, close=104.0, date='x')
        self.assertEqual(bt.intrabar_exit(pos, up, cfg), dict(reason='target', price=104.0))

    def test_close_decision_trend_exit_and_square_off(self):
        cfg = bt.validate_config(CONFIG)
        self.assertEqual(bt.close_exit(9.5, 10, '10:00', cfg), 'trend-exit')       # fast EMA below slow EMA
        self.assertIsNone(bt.close_exit(10.5, 10, '10:00', cfg))
        self.assertEqual(bt.close_exit(10.5, 10, '15:05', cfg), 'square-off')
        self.assertEqual(bt.close_exit(9.0, 10, '15:05', cfg), 'square-off')       # square-off outranks trend
        self.assertIsNone(bt.close_exit(None, None, '10:00', cfg))

    def test_entry_requires_a_signal_time_before_entry_end_and_no_open_position(self):
        enter = dict(action=strat.ENTER, reason='ema_cross_up_adx_ok')
        cfg = bt.validate_config(CONFIG)
        self.assertTrue(bt.may_enter(enter, '14:25', False, cfg))
        self.assertFalse(bt.may_enter(enter, '14:30', False, cfg))
        self.assertFalse(bt.may_enter(enter, '10:00', True, cfg))
        self.assertFalse(bt.may_enter(dict(action=strat.SKIP, reason='no_crossover'), '10:00', False, cfg))

    def test_sizing_respects_cash_exposure_volume_and_trade_and_daily_loss_limits(self):
        cfg = bt.validate_config(CONFIG)
        qty = bt.size_entry(cfg, cash=100000.0, price=100.0, volume=100000, day_start_equity=100000.0)
        self.assertGreater(qty, 0)
        loss_at_stop = qty * (100.0 * 1.0005 * 1.001 - 99.0 * 0.9995 * 0.999)
        self.assertLessEqual(loss_at_stop, cfg['maxLoss'] + 1e-6)
        self.assertEqual(bt.size_entry(cfg, cash=50.0, price=100.0, volume=100000, day_start_equity=100000.0), 0)
        self.assertLessEqual(bt.size_entry(cfg, 100000.0, 100.0, volume=40, day_start_equity=100000.0), 4)   # 10% of volume
        spent = bt.size_entry(cfg, cash=100000.0, price=100.0, volume=100000, day_start_equity=102000.0)     # already down 2000
        self.assertEqual(spent, 0)                                                                            # daily limit used up


class BacktestInvariantTests(unittest.TestCase):
    def setUp(self):
        self.result = bt.backtest(BARS, CONFIG)

    def test_runs_trade_and_every_exit_reason_is_one_of_the_rules(self):
        trades = self.result['trades']
        self.assertGreater(len(trades), 0, 'fixture should produce at least one trade')
        self.assertTrue({t['exitReason'] for t in trades} <= {'stop', 'target', 'trend-exit', 'square-off', 'end-of-data'})

    def test_no_position_is_ever_held_overnight_or_entered_after_entry_end(self):
        for trade in self.result['trades']:
            if trade['exitReason'] == 'end-of-data':
                continue
            self.assertEqual(trade['entryDate'][:10], trade['exitDate'][:10], trade)
            self.assertLess(trade['entryDate'][11:16], CONFIG['entryEnd'])   # the FILL bar is before the cutoff
        for trade in self.result['trades']:
            signal_clock = trade['signalDate'][11:16]
            self.assertLess(signal_clock, CONFIG['entryEnd'])

    def test_entries_fill_at_the_open_after_the_signal_bar_never_the_signal_bar(self):
        index = {bar['date']: i for i, bar in enumerate(BARS)}
        for trade in self.result['trades']:
            self.assertEqual(index[trade['entryDate']], index[trade['signalDate']] + 1)

    def test_every_trade_respects_the_saved_per_trade_loss_limit_unless_gapped(self):
        cfg = bt.validate_config(CONFIG)
        for trade in self.result['trades']:
            if trade['exitReason'] == 'stop' and trade['exitRaw'] >= bt.levels(trade['entryRaw'], cfg)[0] - 1e-9:
                self.assertGreaterEqual(trade['netPnl'], -(cfg['maxLoss'] + 1e-6), trade)

    def test_accounting_reconciles_cash_fees_and_equity(self):
        r = self.result
        realised = sum(t['netPnl'] for t in r['trades'] if t['exitReason'] != 'end-of-data')
        self.assertAlmostEqual(r['finalEquity'] - r['initialCapital'], sum(t['netPnl'] for t in r['trades']), places=6)
        self.assertAlmostEqual(r['fees'], sum(t['fees'] for t in r['trades']), places=6)
        self.assertEqual(len(r['equity']), len(BARS))
        self.assertGreaterEqual(min(r['equity']), 0)
        self.assertTrue(math.isfinite(realised))

    def test_deterministic_and_input_is_not_mutated(self):
        before = copy.deepcopy(BARS)
        again = bt.backtest(BARS, CONFIG)
        self.assertEqual(again, self.result)
        self.assertEqual(BARS, before)

    def test_no_lookahead_changing_future_bars_never_changes_earlier_trades(self):
        cut = 300
        early = bt.backtest(BARS[:cut], CONFIG)['trades']
        mutated = copy.deepcopy(BARS)
        for bar in mutated[cut:]:
            bar.update(open=bar['open'] * 3, high=bar['high'] * 3, low=bar['low'] * 3, close=bar['close'] * 3)
        full = bt.backtest(mutated, CONFIG)['trades']
        settled = [t for t in early if t['exitReason'] != 'end-of-data']
        self.assertEqual([t for t in full if t['exitDate'] < BARS[cut]['date']][:len(settled)], settled)

    def test_makes_no_profitability_claim(self):
        self.assertFalse(self.result['claimsProfitability'])
        self.assertIn('no validated edge', self.result['limitations'].lower())
        for text in (self.result['limitations'], bt.__doc__):
            self.assertNotRegex(text.lower(), r'guarantee|will profit|profitable strategy')

    def test_invalid_input_is_refused(self):
        with self.assertRaises(ValueError):
            bt.backtest([], CONFIG)
        broken = copy.deepcopy(BARS)
        broken[10]['low'] = broken[10]['high'] + 1
        with self.assertRaises(ValueError):
            bt.backtest(broken, CONFIG)
        with self.assertRaises(ValueError):
            bt.backtest(BARS, dict(CONFIG, maxLoss=1e9))
        shuffled = BARS[:50] + BARS[40:60]
        with self.assertRaises(ValueError):
            bt.backtest(shuffled, CONFIG)


def flat_bars(count=75, price=100.0, day=0):
    return [dict(date=t.isoformat(), open=price, high=price + 0.1, low=price - 0.1, close=price, volume=100000)
            for t in session_times(day)[:count]]


def script(length, **at):
    """Scripted strategy decisions: at[index] = (action, ema20, ema50)."""
    rows = []
    for i in range(length):
        action, fast, slow = at.get('i%d' % i, (strat.SKIP, None, None))
        rows.append(dict(action=action, reason='scripted', ema20=fast, ema50=slow, date='x', adx=None, version='x'))
    return rows


class SpacingTests(unittest.TestCase):
    def test_missing_or_irregular_bars_inside_a_session_are_refused_but_overnight_gaps_are_fine(self):
        bars = flat_bars() + flat_bars(day=1)
        bt.backtest(bars, CONFIG)                                   # an overnight gap is normal
        holed = copy.deepcopy(bars)
        del holed[30]
        with self.assertRaisesRegex(ValueError, 'consecutive 5-minute'):
            bt.backtest(holed, CONFIG)
        slow = copy.deepcopy(bars)
        slow[20]['date'] = (dt.datetime.fromisoformat(slow[20]['date']) + dt.timedelta(minutes=1)).isoformat()
        with self.assertRaises(ValueError):
            bt.backtest(slow, CONFIG)


class ScriptedScenarioTests(unittest.TestCase):
    """Force each rule with scripted decisions so every exit path is exercised exactly."""

    def run_scenario(self, bars, scripted, config=CONFIG):
        from unittest.mock import patch
        with patch.object(bt.strat, 'ema_adx_scan', return_value=scripted):
            return bt.backtest(bars, config)

    def enter_at(self, index):
        return {'i%d' % index: (strat.ENTER, 10.0, 9.0)}

    def test_entry_fills_next_open_then_stop_hits_intrabar_at_the_stop_price(self):
        bars = flat_bars()
        bars[12] = dict(bars[12], open=100.0, high=100.2, low=98.5, close=99.0)   # pierces the 99.00 stop
        result = self.run_scenario(bars, script(75, **self.enter_at(10)))
        trade = result['trades'][0]
        self.assertEqual((trade['signalDate'], trade['entryDate']), (bars[10]['date'], bars[11]['date']))
        self.assertEqual((trade['exitReason'], trade['exitDate']), ('stop', bars[12]['date']))
        self.assertAlmostEqual(trade['exitRaw'], 99.0)
        self.assertLessEqual(-trade['netPnl'], CONFIG['maxLoss'] + 1e-6)

    def test_target_hit_exits_at_target(self):
        bars = flat_bars()
        bars[13] = dict(bars[13], open=100.0, high=102.5, low=99.9, close=102.0)
        trade = self.run_scenario(bars, script(75, **self.enter_at(10)))['trades'][0]
        self.assertEqual(trade['exitReason'], 'target')
        self.assertAlmostEqual(trade['exitRaw'], 102.0)
        self.assertGreater(trade['netPnl'], 0)

    def test_trend_exit_fills_at_the_next_open_not_the_signal_bar(self):
        bars = flat_bars()
        scripted = script(75, **self.enter_at(10), **{'i20': (strat.SKIP, 9.0, 10.0)})   # fast EMA below slow on bar 20
        trade = self.run_scenario(bars, scripted)['trades'][0]
        self.assertEqual((trade['exitReason'], trade['exitDate']), ('trend-exit', bars[21]['date']))

    def test_square_off_exits_at_the_next_open_after_the_configured_time(self):
        bars = flat_bars()
        trade = self.run_scenario(bars, script(75, **self.enter_at(10)))['trades'][0]
        self.assertEqual(trade['exitReason'], 'square-off')
        index = {b['date']: i for i, b in enumerate(bars)}[trade['exitDate']]
        self.assertEqual(bars[index - 1]['date'][11:16], '15:05')        # decided on the 15:05 bar, filled next open

    def test_entry_cutoff_is_judged_by_the_fill_bar_like_the_paper_engine(self):
        bars = flat_bars()
        at = {b['date'][11:16]: i for i, b in enumerate(bars)}
        self.assertEqual(self.run_scenario(bars, script(75, **self.enter_at(at['14:30'])))['trades'], [])
        # signal on 14:25 would FILL at the 14:30 open, which the engine rejects (clock >= entryEnd)
        self.assertEqual(self.run_scenario(bars, script(75, **self.enter_at(at['14:25'])))['trades'], [])
        trades = self.run_scenario(bars, script(75, **self.enter_at(at['14:20'])))['trades']
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]['entryDate'][11:16], '14:25')

    def test_a_second_entry_signal_while_holding_is_ignored(self):
        bars = flat_bars()
        trades = self.run_scenario(bars, script(75, **self.enter_at(10), **self.enter_at(11), **self.enter_at(12)))['trades']
        self.assertEqual(len(trades), 1)

    def test_daily_loss_limit_blocks_a_further_entry_after_a_loss(self):
        bars = flat_bars()
        bars[12] = dict(bars[12], open=100.0, high=100.2, low=98.0, close=98.5)       # first trade stops out
        config = dict(CONFIG, maxLoss=300.0, dailyLossLimit=300.0)
        trades = self.run_scenario(bars, script(75, **self.enter_at(10), **self.enter_at(30)), config)['trades']
        self.assertEqual([t['exitReason'] for t in trades], ['stop'])                 # re-entry sized to zero

    def test_the_daily_loss_allowance_resets_each_session_from_that_days_starting_equity(self):
        bars = flat_bars() + flat_bars(day=1)
        bars[12] = dict(bars[12], open=100.0, high=100.2, low=98.0, close=98.5)        # day 1: stop out
        config = dict(CONFIG, maxLoss=300.0, dailyLossLimit=300.0)
        scripted = script(150, **self.enter_at(10), **self.enter_at(75 + 10))
        trades = self.run_scenario(bars, scripted, config)['trades']
        self.assertEqual([t['exitReason'] for t in trades], ['stop', 'square-off'])      # day 2 may trade again
        self.assertEqual(trades[1]['entryDate'][:10], bars[75]['date'][:10])

    def test_a_position_still_open_at_the_end_of_data_is_closed_and_counted(self):
        bars = flat_bars(count=30)
        result = self.run_scenario(bars, script(30, **self.enter_at(10)))
        self.assertEqual(result['trades'][0]['exitReason'], 'end-of-data')
        self.assertAlmostEqual(result['finalEquity'] - result['initialCapital'], result['trades'][0]['netPnl'], places=6)

    def test_gap_down_through_the_stop_fills_at_the_open_and_may_exceed_the_trade_limit(self):
        bars = flat_bars()
        bars[12] = dict(bars[12], open=95.0, high=95.2, low=94.5, close=95.0)
        trade = self.run_scenario(bars, script(75, **self.enter_at(10)))['trades'][0]
        self.assertEqual((trade['exitReason'], trade['exitRaw']), ('stop', 95.0))
        self.assertGreater(-trade['netPnl'], CONFIG['maxLoss'])       # gap risk is real and not hidden


class WalkForwardTests(unittest.TestCase):
    def setUp(self):
        self.report = bt.walk_forward(BARS, CONFIG, minimum_train=150, test_size=75, label_horizon=75)

    def test_folds_are_ordered_disjoint_and_test_windows_follow_purged_training(self):
        folds = self.report['folds']
        self.assertGreaterEqual(len(folds), 2)
        for earlier, later in zip(folds, folds[1:]):
            self.assertLessEqual(earlier['test'][1], later['test'][0])
        for fold in folds:
            self.assertGreater(fold['test'][0], fold['train'][1])          # purged gap
            self.assertLessEqual(fold['test'][1], len(BARS))

    def test_parameters_are_identical_in_every_fold_so_nothing_is_tuned(self):
        self.assertEqual(self.report['parameters']['fast'], 20)
        self.assertEqual({tuple(sorted(f['parameters'].items())) for f in self.report['folds']},
                         {tuple(sorted(self.report['parameters'].items()))})

    def test_trades_are_attributed_only_to_the_window_they_were_entered_in(self):
        index = {bar['date']: i for i, bar in enumerate(BARS)}
        total = 0
        for fold in self.report['folds']:
            for trade in fold['trades']:
                self.assertGreaterEqual(index[trade['entryDate']], fold['test'][0])
                self.assertLess(index[trade['entryDate']], fold['test'][1])
            total += len(fold['trades'])
        self.assertEqual(self.report['pooled']['tradeCount'], total)

    def test_report_counts_without_claiming_an_edge(self):
        pooled = self.report['pooled']
        self.assertEqual(set(pooled), {'tradeCount', 'truncatedTrades', 'foldsWithTrades', 'foldsTotal', 'positiveFolds', 'netPnl', 'fees'})
        self.assertFalse(self.report['claimsProfitability'])
        self.assertIn('no validated edge', self.report['limitations'].lower())
        self.assertIn('not tuned', self.report['limitations'].lower())

    def test_a_trade_entered_near_a_window_end_reaches_its_real_exit_not_a_truncation(self):
        from unittest.mock import patch
        bars = flat_bars() * 1
        for day in range(1, 8):
            bars += flat_bars(day=day)
        entry_signal = 260                        # inside the window [225, 275); its square-off exit is at bar 296
        scripted = script(len(bars), **{'i%d' % entry_signal: (strat.ENTER, 10.0, 9.0)})
        with patch.object(bt.strat, 'ema_adx_scan', return_value=scripted):
            report = bt.walk_forward(bars, CONFIG, minimum_train=150, test_size=50, label_horizon=75)
        trades = [t for fold in report['folds'] for t in fold['trades']]
        self.assertEqual(len(trades), 1)
        self.assertNotEqual(trades[0]['exitReason'], 'end-of-data')
        owner = next(f for f in report['folds'] if f['trades'])
        self.assertEqual(owner['test'], [225, 275])
        self.assertGreater(trades[0]['exitIndex'], owner['test'][1])       # the exit lies beyond the window end
        self.assertGreaterEqual(trades[0]['entryIndex'], owner['test'][0])
        self.assertEqual(report['pooled']['truncatedTrades'], 0)   # truncation is counted and visible

    def test_bars_beyond_the_window_plus_horizon_never_change_a_fold(self):
        base = bt.walk_forward(BARS, CONFIG, minimum_train=150, test_size=75, label_horizon=75)
        altered = copy.deepcopy(BARS)
        first_end = base['folds'][0]['test'][1]
        for bar in altered[first_end + 75:]:
            bar.update(open=bar['open'] * 2, high=bar['high'] * 2, low=bar['low'] * 2, close=bar['close'] * 2)
        again = bt.walk_forward(altered, CONFIG, minimum_train=150, test_size=75, label_horizon=75)
        self.assertEqual(again['folds'][0], base['folds'][0])

    def test_deterministic_and_refuses_too_little_data(self):
        self.assertEqual(bt.walk_forward(BARS, CONFIG, minimum_train=150, test_size=75, label_horizon=75), self.report)
        with self.assertRaises(ValueError):
            bt.walk_forward(BARS[:100], CONFIG, minimum_train=150, test_size=75, label_horizon=75)


class AdjustmentTests(unittest.TestCase):
    def day_bars(self, day, price, volume=1000):
        return [dict(date=t.isoformat(), open=price, high=price + 1, low=price - 1, close=price, volume=volume)
                for t in session_times(day)[:3]]

    def test_split_back_adjusts_prices_down_and_volume_up_before_the_action_date(self):
        bars = self.day_bars(0, 200.0) + self.day_bars(1, 100.0)
        out = bt.adjust_for_actions(bars, [dict(date='2026-01-02', type='split', ratio=2)])
        self.assertEqual(out[0]['close'], 100.0)
        self.assertEqual(out[0]['high'], 100.5)
        self.assertEqual(out[0]['volume'], 2000)
        self.assertEqual(out[-1]['close'], 100.0)            # on and after the date: unchanged
        self.assertEqual(out[-1]['volume'], 1000)
        self.assertLess(abs(out[2]['close'] / out[3]['close'] - 1), 1e-9)   # continuous across the split

    def test_bonus_and_multiple_actions_compose_and_input_is_not_mutated(self):
        bars = self.day_bars(0, 400.0) + self.day_bars(1, 200.0) + self.day_bars(2, 100.0)
        before = copy.deepcopy(bars)
        out = bt.adjust_for_actions(bars, [dict(date='2026-01-03', type='split', ratio=2),
                                            dict(date='2026-01-02', type='bonus', ratio=2)])
        self.assertEqual([b['close'] for b in out[::3]], [100.0, 100.0, 100.0])
        self.assertEqual(bars, before)
        self.assertTrue(all(b['adjustedFor'] for b in out[:3]))

    def test_cash_dividend_adjusts_prices_but_not_volume(self):
        bars = self.day_bars(0, 100.0) + self.day_bars(1, 98.0)
        out = bt.adjust_for_actions(bars, [dict(date='2026-01-02', type='dividend', amount=2.0)])
        self.assertAlmostEqual(out[0]['close'], 100.0 * (1 - 2.0 / 100.0))
        self.assertEqual(out[0]['volume'], 1000)

    def test_invalid_actions_are_refused(self):
        bars = self.day_bars(0, 100.0)
        for bad in (dict(date='2026-01-03', type='merger', ratio=2), dict(date='bad', type='split', ratio=2),
                    dict(date='2026-01-03', type='split', ratio=1), dict(date='2026-01-03', type='split', ratio=float('nan')),
                    dict(date='2026-01-03', type='dividend', amount=500.0), dict(date='2026-01-03', type='dividend', amount=-1),
                    dict(date='2026-01-03', type='split')):
            with self.assertRaises(ValueError, msg=str(bad)):
                bt.adjust_for_actions(bars, [bad])
        with self.assertRaises(ValueError):
            bt.adjust_for_actions(bars, [dict(date='2026-01-03', type='split', ratio=2)] * 2)   # duplicate action

    def test_unadjusted_split_creates_a_false_gap_that_adjustment_removes(self):
        bars = self.day_bars(0, 200.0) + self.day_bars(1, 100.0)
        raw_jump = abs(bars[3]['close'] / bars[2]['close'] - 1)
        adjusted = bt.adjust_for_actions(bars, [dict(date='2026-01-02', type='split', ratio=2)])
        self.assertGreater(raw_jump, 0.4)
        self.assertLess(abs(adjusted[3]['close'] / adjusted[2]['close'] - 1), 1e-9)


if __name__ == '__main__':
    unittest.main()
