"""EMA 20/50 crossover with an ADX trend filter. Research and backtest only.

The caller supplies COMPLETED candles only (as with strategy_contract.target_long);
a decision on the last candle applies to the next open. This module has no execution,
paper-account, risk or broker authority and makes no claim of edge.
"""
import datetime as dt
import math

from indicators import adx, ema

VERSION = 'ema20-50-adx14-cross-v1'
ENTER = 'ENTER_LONG'
SKIP = 'SKIP'


def _stamp(value, name):
    if not isinstance(value, str):
        raise ValueError(f'{name} must be an ISO-8601 date or date-time string.')
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f'{name} must be an ISO-8601 date or date-time string.') from None


def _same_instant(a, b):
    try:
        return a == b if (a.tzinfo is None) == (b.tzinfo is None) else _mismatch()
    except TypeError:
        return _mismatch()


def _mismatch():
    raise ValueError('Dates must be all timezone-aware or all naive.')


def _validate(candles, fast, slow, adx_period, adx_threshold):
    for name, v in (('fast', fast), ('slow', slow), ('adx_period', adx_period)):
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise ValueError(f'{name} must be a positive integer.')
    if fast >= slow:
        raise ValueError('fast period must be shorter than slow period.')
    if isinstance(adx_threshold, bool) or not isinstance(adx_threshold, (int, float)) \
            or not math.isfinite(adx_threshold) or not 0 <= adx_threshold <= 100:
        raise ValueError('adx_threshold must be a number from 0 to 100.')
    if not isinstance(candles, (list, tuple)):
        raise ValueError('candles must be a list.')
    dates, stamps, highs, lows, closes = [], [], [], [], []
    for row in candles:
        if not isinstance(row, dict) or not isinstance(row.get('date'), str):
            raise ValueError('Each candle needs a date string and numeric high, low and close.')
        dates.append(row['date'])
        stamps.append(_stamp(row['date'], 'candle date'))
        highs.append(row.get('high'))
        lows.append(row.get('low'))
        closes.append(row.get('close'))
    for earlier, later in zip(stamps, stamps[1:]):
        if (earlier.tzinfo is None) != (later.tzinfo is None):
            _mismatch()
        if not earlier < later:
            raise ValueError('Candle dates must be strictly increasing with no duplicates.')
    return dates, highs, lows, closes


def _decide(i, date, fast_v, slow_v, adx_v, threshold):
    base = {'version': VERSION, 'date': date, 'ema20': None, 'ema50': None, 'adx': adx_v}
    cur_f, cur_s = fast_v[i], slow_v[i]
    prev_f, prev_s = (fast_v[i - 1], slow_v[i - 1]) if i else (None, None)
    base['ema20'], base['ema50'] = cur_f, cur_s
    if cur_s is None or prev_s is None or adx_v is None:
        return {**base, 'action': SKIP, 'reason': 'insufficient_history'}
    if not (prev_f <= prev_s and cur_f > cur_s):
        return {**base, 'action': SKIP, 'reason': 'no_crossover'}
    if adx_v < threshold:
        return {**base, 'action': SKIP, 'reason': 'adx_below_threshold'}
    return {**base, 'action': ENTER, 'reason': 'ema_cross_up_adx_ok'}


def ema_adx_scan(candles, fast=20, slow=50, adx_period=14, adx_threshold=20.0):
    """One decision per candle, each using only data up to and including that candle."""
    dates, highs, lows, closes = _validate(candles, fast, slow, adx_period, adx_threshold)
    fast_v, slow_v = ema(closes, fast), ema(closes, slow)
    adx_v = adx(highs, lows, closes, adx_period)
    return [_decide(i, dates[i], fast_v, slow_v, adx_v[i], adx_threshold) for i in range(len(dates))]


def ema_adx_signal(candles, fast=20, slow=50, adx_period=14, adx_threshold=20.0, last_signal_date=None):
    """Decision for the last completed candle. Long entry only on a true upward EMA cross
    (previous bar fast <= slow, current bar fast > slow) with ADX >= adx_threshold.
    Pass the date of the last signal already acted on to prevent a duplicate."""
    last_stamp = None if last_signal_date is None else _stamp(last_signal_date, 'last_signal_date')
    if not candles:
        _validate(candles, fast, slow, adx_period, adx_threshold)
        return {'version': VERSION, 'date': None, 'ema20': None, 'ema50': None, 'adx': None,
                'action': SKIP, 'reason': 'insufficient_history'}
    decision = ema_adx_scan(candles, fast, slow, adx_period, adx_threshold)[-1]
    if decision['action'] == ENTER and last_stamp is not None and _same_instant(_stamp(decision['date'], 'candle date'), last_stamp):
        return {**decision, 'action': SKIP, 'reason': 'duplicate_signal'}
    return decision
