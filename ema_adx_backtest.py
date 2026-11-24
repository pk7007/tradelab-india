"""EMA 20/50 + ADX intraday research backtest on completed 5-minute bars. No execution authority.

This is a research simulation only. It places no orders, changes no limits and promotes nothing; the
paper engine does not run it (see `strategy_registry`). It makes no claim of profitability.

Rules: entry decisions come from `ema_adx_strategy` on the completed bar and fill at the NEXT bar's open,
only before the saved entry cutoff and while flat. Exits, in priority order: stop (intrabar, gaps fill at the
open), target (entry + (entry - stop) * targetMultiple), trend exit (EMA20 below EMA50 on a completed bar,
fills next open) and square-off (at or after the saved square-off time, fills next open). Size, stop,
target, costs and daily loss come from the saved risk limits and reuse `intraday_contract`.
"""
import datetime as dt
import math

import ema_adx_strategy as strat
import intraday_contract
from research import chronological_splits
from strategy_contract import assumed_fill

TIMEFRAME_MINUTES = 5
VERSION = 'ema20-50-adx14-intraday-5m-v1'
PARAMETERS = dict(fast=20, slow=50, adxPeriod=14, adxThreshold=20.0)
LIMITATIONS = ('No validated edge. Research simulation on supplied completed 5-minute OHLC bars. Parameters are '
               'conventional (20/50/14/20) and not tuned. Fills use modeled open, stop and target prices with fixed '
               'slippage and fees; exits are assumed to fill in full. Prices are unadjusted unless '
               'adjust_for_actions was applied. Nothing here says anything about live profitability.')


def _finite(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Invalid ' + name)
    return float(value)


def validate_config(config):
    """Saved risk limits, checked by the existing intraday contract plus the account numbers it does not cover."""
    if not isinstance(config, dict):
        raise ValueError('Config must be an object.')
    checked = intraday_contract.validate(config)
    cfg = dict(checked)
    cfg['capital'] = _finite(config.get('capital'), .01, 1e12, 'capital')
    cfg['maxExposure'] = _finite(config.get('maxExposure'), .01, 1e12, 'maxExposure')
    cfg['dailyLossLimit'] = _finite(config.get('dailyLossLimit'), .01, 1e12, 'dailyLossLimit')
    units = config.get('units')
    if isinstance(units, bool) or not isinstance(units, int) or units < 1:
        raise ValueError('Invalid units')
    cfg['units'] = units
    cfg['costBps'] = _finite(config.get('costBps'), 0, 100, 'costBps')
    cfg['slippageBps'] = _finite(config.get('slippageBps'), 0, 100, 'slippageBps')
    return cfg


def levels(entry, cfg):
    stop = entry * (1 - cfg['stopDistancePct'] / 100)
    return stop, entry + (entry - stop) * cfg['targetMultiple']


def intrabar_exit(position, bar, cfg):
    """Stop first (a same-bar tie is conservative); gaps fill at the open."""
    stop, target = levels(position['entry'], cfg)
    if bar['open'] <= stop:
        return dict(reason='stop', price=bar['open'])
    if bar['low'] <= stop:
        return dict(reason='stop', price=stop)
    if bar['open'] >= target:
        return dict(reason='target', price=bar['open'])
    if bar['high'] >= target:
        return dict(reason='target', price=target)
    return None


def close_exit(fast, slow, clock, cfg):
    if clock >= cfg['squareOff']:
        return 'square-off'
    if fast is not None and slow is not None and fast < slow:
        return 'trend-exit'
    return None


def may_enter(decision, fill_clock, holding, cfg):
    """The cutoff applies to the bar the order would FILL on (the next open), as in the paper engine."""
    return decision.get('action') == strat.ENTER and not holding and fill_clock < cfg['entryEnd']


def size_entry(cfg, cash, price, volume, day_start_equity):
    state = dict(config=cfg, cash=cash, quantity=0, dayStartEquity=day_start_equity)
    return intraday_contract.entry_size(state, price, volume)


def _validate_bars(bars):
    if not isinstance(bars, (list, tuple)) or not bars:
        raise ValueError('Supply a non-empty list of completed bars.')
    previous = None
    for bar in bars:
        if not isinstance(bar, dict) or not isinstance(bar.get('date'), str):
            raise ValueError('Each bar needs a date string.')
        try:
            stamp = dt.datetime.fromisoformat(bar['date'])
        except ValueError:
            raise ValueError('Bar dates must be ISO-8601.') from None
        if stamp.tzinfo is None:
            raise ValueError('Bar dates must be timezone-aware (IST).')
        if previous is not None and not previous < stamp:
            raise ValueError('Bar dates must be strictly increasing.')
        if previous is not None and previous.date() == stamp.date() and stamp - previous != dt.timedelta(minutes=TIMEFRAME_MINUTES):
            raise ValueError('Bars must be consecutive 5-minute candles within a session (no missing or irregular bars).')
        previous = stamp
        o, h, l, c = (_finite(bar.get(key), 1e-9, 1e12, key) for key in ('open', 'high', 'low', 'close'))
        _finite(bar.get('volume'), 0, 1e15, 'volume')
        if l > min(o, c) or h < max(o, c):
            raise ValueError('Invalid OHLC bar.')


def backtest(bars, config):
    cfg = validate_config(config)
    _validate_bars(bars)
    decisions = strat.ema_adx_scan([dict(date=b['date'], high=b['high'], low=b['low'], close=b['close']) for b in bars],
                                   PARAMETERS['fast'], PARAMETERS['slow'], PARAMETERS['adxPeriod'], PARAMETERS['adxThreshold'])
    cash, quantity, position, pending, fees = cfg['capital'], 0, None, None, 0.0
    day, day_start_equity, trades, equity = None, cfg['capital'], [], []

    def sell(index, raw, reason):
        nonlocal cash, quantity, position, fees
        price, fee = assumed_fill(raw, position['quantity'], 'SELL', cfg['costBps'], cfg['slippageBps'])
        cash += position['quantity'] * price - fee
        total_fees = position['fee'] + fee
        fees += fee
        trades.append(dict(signalDate=position['signalDate'], entryDate=position['entryDate'], entryRaw=position['entry'],
                           entryPrice=position['fill'], quantity=position['quantity'], exitDate=bars[index]['date'],
                           exitReason=reason, exitRaw=raw, exitPrice=price, fees=total_fees,
                           netPnl=position['quantity'] * (price - position['fill']) - total_fees,
                           entryIndex=position['entryIndex'], exitIndex=index))
        quantity, position = 0, None

    for i, bar in enumerate(bars):
        if bar['date'][:10] != day:
            day = bar['date'][:10]
            day_start_equity = cash + quantity * bar['open']
        if pending:
            if pending['side'] == 'BUY' and position is None:
                count = size_entry(cfg, cash, bar['open'], bar['volume'], day_start_equity)
                if count > 0:
                    price, fee = assumed_fill(bar['open'], count, 'BUY', cfg['costBps'], cfg['slippageBps'])
                    cash -= count * price + fee
                    fees += fee
                    quantity = count
                    position = dict(entry=bar['open'], fill=price, quantity=count, fee=fee, signalDate=pending['signalDate'],
                                    entryDate=bar['date'], entryIndex=i)
            elif pending['side'] == 'SELL' and position:
                sell(i, bar['open'], pending['reason'])
            pending = None
        if position:
            hit = intrabar_exit(position, bar, cfg)
            if hit:
                sell(i, hit['price'], hit['reason'])
        equity.append(cash + quantity * bar['close'])
        decision, clock = decisions[i], bar['date'][11:16]
        if position:
            reason = close_exit(decision['ema20'], decision['ema50'], clock, cfg)
            if reason:
                pending = dict(side='SELL', reason=reason)
        elif i + 1 < len(bars) and may_enter(decision, bars[i + 1]['date'][11:16], False, cfg):
            pending = dict(side='BUY', signalDate=bar['date'])
    if position:
        sell(len(bars) - 1, bars[-1]['close'], 'end-of-data')
        equity[-1] = cash
    return dict(version=VERSION, timeframeMinutes=TIMEFRAME_MINUTES, parameters=dict(PARAMETERS), initialCapital=cfg['capital'],
                finalEquity=cash, fees=fees, trades=trades, equity=equity, claimsProfitability=False, limitations=LIMITATIONS)


def walk_forward(bars, config, *, minimum_train=300, test_size=150, label_horizon=75):
    """Expanding test windows over one continuous account. Parameters are fixed; nothing is fitted or tuned.

    `train` is only the history before the window and `label_horizon` is the number of bars (default one session)
    that lets a trade entered late in a window reach its real exit instead of being cut off at the window end. Only
    trades ENTERED inside the test window are counted. Cash carries over from earlier trades, so windows are not
    independent. Bars after `test end + label_horizon` never influence a window.
    """
    validate_config(config)
    _validate_bars(bars)
    folds = chronological_splits(len(bars), label_horizon, minimum_train, test_size)
    if not folds:
        raise ValueError('Not enough bars for a walk-forward test.')
    report, pooled_trades = [], 0
    for fold in folds:
        start, end = fold['test']
        result = backtest(bars[:min(len(bars), end + label_horizon)], config)   # room for exits to resolve (one session)
        trades = [t for t in result['trades'] if start <= t['entryIndex'] < end]
        pooled_trades += len(trades)
        report.append(dict(train=fold['train'], test=fold['test'], trades=trades, tradeCount=len(trades),
                           truncatedTrades=sum(1 for t in trades if t['exitReason'] == 'end-of-data'),
                           netPnl=sum(t['netPnl'] for t in trades), fees=sum(t['fees'] for t in trades),
                           parameters=dict(PARAMETERS)))
    return dict(version=VERSION, parameters=dict(PARAMETERS), folds=report,
                pooled=dict(tradeCount=pooled_trades, truncatedTrades=sum(f['truncatedTrades'] for f in report), foldsWithTrades=sum(1 for f in report if f['tradeCount']),
                            foldsTotal=len(report), positiveFolds=sum(1 for f in report if f['tradeCount'] and f['netPnl'] > 0),
                            netPnl=sum(f['netPnl'] for f in report), fees=sum(f['fees'] for f in report)),
                claimsProfitability=False, limitations=LIMITATIONS)


def adjust_for_actions(bars, actions):
    """Back-adjust bars dated BEFORE each action's effective (ex) date. `ratio` = new shares per old share:
    a 2-for-1 split is 2, a 1:1 bonus is 2, a 1:2 bonus is 1.5. Split/bonus: price / ratio, volume * ratio.
    Cash dividend: price * (1 - amount / last raw close before the date), volume unchanged. Input is not mutated."""
    if not isinstance(bars, (list, tuple)) or not isinstance(actions, (list, tuple)):
        raise ValueError('Bars and actions must be lists.')
    seen, parsed = set(), []
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError('Invalid corporate action.')
        try:
            date = dt.date.fromisoformat(str(action.get('date')))
        except ValueError:
            raise ValueError('Corporate action needs an ISO date.') from None
        kind = action.get('type')
        if kind in ('split', 'bonus'):
            value = _finite(action.get('ratio'), 1.000001, 1e6, 'ratio')
        elif kind == 'dividend':
            value = _finite(action.get('amount'), 1e-9, 1e9, 'amount')
        else:
            raise ValueError('Unsupported corporate action type.')
        if (date, kind) in seen:
            raise ValueError('Duplicate corporate action.')
        seen.add((date, kind))
        parsed.append((date, kind, value))
    stamps = [dt.date.fromisoformat(b['date'][:10]) for b in bars]
    factors = []
    for date, kind, value in parsed:
        if kind == 'dividend':
            before = [bar['close'] for bar, d in zip(bars, stamps) if d < date]
            if not before:
                continue
            if value >= before[-1]:
                raise ValueError('Dividend is not smaller than the prior close.')
            factors.append((date, 1 - value / before[-1], 1.0, kind))
        else:
            factors.append((date, 1 / value, value, kind))
    out = []
    for bar, day in zip(bars, stamps):
        price_factor, volume_factor, applied = 1.0, 1.0, []
        for date, price, volume, kind in factors:
            if day < date:
                price_factor *= price
                volume_factor *= volume
                applied.append('%s@%s' % (kind, date.isoformat()))
        row = dict(bar)
        if applied:
            for key in ('open', 'high', 'low', 'close'):
                row[key] = bar[key] * price_factor
            row['volume'] = bar['volume'] * volume_factor
            row['adjustedFor'] = applied
        out.append(row)
    return out
