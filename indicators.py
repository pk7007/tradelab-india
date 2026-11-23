"""Pure technical indicators for research and backtests; no execution authority.

Every function returns a list aligned with its input. Positions without enough
history hold None (explicit warm-up); no value ever uses a later bar.
Inputs must be finite, non-boolean real numbers.
"""
import math


def _period(period):
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise ValueError("period must be an integer of at least 1.")
    return period


def _series(values, name):
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{name} must be a list of numbers.")
    for index, v in enumerate(values):
        if isinstance(v, bool):
            raise ValueError(f"{name}[{index}] is a boolean; only finite numbers are accepted.")
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"{name}[{index}] must be a finite number.")
    return [float(v) for v in values]


def _bars(highs, lows, closes):
    h, l, c = _series(highs, "highs"), _series(lows, "lows"), _series(closes, "closes")
    if not len(h) == len(l) == len(c):
        raise ValueError("highs, lows and closes must have equal length.")
    if any(hi < lo for hi, lo in zip(h, l)):
        raise ValueError("A high is below its low.")
    return h, l, c


def ema(values, period):
    """EMA seeded with the simple mean of the first `period` values, alpha = 2/(period+1)."""
    period = _period(period)
    data = _series(values, "values")
    out = [None] * len(data)
    if len(data) < period:
        return out
    alpha = 2 / (period + 1)
    prev = math.fsum(data[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(data)):
        prev = alpha * data[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def true_range(highs, lows, closes):
    """TR[0] = high-low; later bars include the gap from the previous close."""
    h, l, c = _bars(highs, lows, closes)
    return [h[i] - l[i] if i == 0 else max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(len(h))]


def atr(highs, lows, closes, period=14):
    """Wilder ATR: first value (index period-1) is the mean TR, then (prev*(p-1)+TR)/p.

    Convention note: TR[0] = high-low is included in the seed mean, so the first ATR is at index
    period-1. TA-Lib instead excludes TR[0] and first reports ATR at index period, so early values
    differ from TA-Lib. ADX below seeds like TA-Lib (first value at index 2*period-1)."""
    period = _period(period)
    tr = true_range(highs, lows, closes)
    out = [None] * len(tr)
    if len(tr) < period:
        return out
    prev = math.fsum(tr[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(tr)):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def adx(highs, lows, closes, period=14):
    """Wilder ADX in 0..100. First value at index 2*period-1; a zero-range market gives 0."""
    period = _period(period)
    h, l, c = _bars(highs, lows, closes)
    n = len(h)
    out = [None] * n
    if n < 2 * period:
        return out
    tr = true_range(h, l, c)
    pdm, mdm = [0.0] * n, [0.0] * n
    for i in range(1, n):
        up, down = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm[i] = up if up > down and up > 0 else 0.0
        mdm[i] = down if down > up and down > 0 else 0.0
    s_tr = math.fsum(tr[1:period + 1])
    s_p = math.fsum(pdm[1:period + 1])
    s_m = math.fsum(mdm[1:period + 1])
    dx = []
    value = 0.0
    for i in range(period, n):
        if i > period:
            s_tr += tr[i] - s_tr / period
            s_p += pdm[i] - s_p / period
            s_m += mdm[i] - s_m / period
        pdi = 100 * s_p / s_tr if s_tr > 0 else 0.0
        mdi = 100 * s_m / s_tr if s_tr > 0 else 0.0
        total = pdi + mdi
        dx.append(100 * abs(pdi - mdi) / total if total > 0 else 0.0)
        if len(dx) == period:
            value = math.fsum(dx) / period
        elif len(dx) > period:
            value = (value * (period - 1) + dx[-1]) / period
        else:
            continue
        out[i] = min(100.0, max(0.0, value))
    return out
