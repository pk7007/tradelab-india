"""Indicator tests against hand-computed fixtures.

Formulas (all values aligned with the input, None during warm-up):
* EMA(p): seed at index p-1 = mean(first p values); then e = a*x + (1-a)*e_prev, a = 2/(p+1).
* TR[0] = high-low; TR[i] = max(h-l, |h-prev_close|, |l-prev_close|).
* ATR(p) (Wilder): first at index p-1 = mean(TR[0..p-1]); then (prev*(p-1)+TR)/p.
* ADX(p) (Wilder): +DM = up if up>down and up>0 else 0, -DM = down if down>up and down>0 else 0,
  up = h[i]-h[i-1], down = l[i-1]-l[i]. Sums of TR/+DM/-DM over indices 1..p seed index p,
  then S = S - S/p + x. DI = 100*DM/TR, DX = 100*|+DI - -DI|/(+DI + -DI).
  First ADX at index 2p-1 = mean(DX[p..2p-1]); then (prev*(p-1)+DX)/p.
"""
import math
import unittest

from indicators import adx, atr, ema, true_range


def reference_adx(highs, lows, closes, period):
    """Independent re-derivation written separately from the module under test."""
    n = len(highs)
    tr, pdm, mdm = [], [], []
    for i in range(1, n):
        up, down = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        pdm.append(up if up > down and up > 0 else 0.0)
        mdm.append(down if down > up and down > 0 else 0.0)
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    out = [None] * n
    s_tr, s_p, s_m = sum(tr[:period]), sum(pdm[:period]), sum(mdm[:period])
    dxs = []
    value = 0.0
    for k in range(period - 1, n - 1):
        if k >= period:
            s_tr += tr[k] - s_tr / period
            s_p += pdm[k] - s_p / period
            s_m += mdm[k] - s_m / period
        pdi = 100 * s_p / s_tr if s_tr else 0.0
        mdi = 100 * s_m / s_tr if s_tr else 0.0
        dxs.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0.0)
        if len(dxs) == period:
            value = sum(dxs) / period
        elif len(dxs) > period:
            value = (value * (period - 1) + dxs[-1]) / period
        else:
            continue
        out[k + 1] = value
    return out


def _long_series():
    closes = [100 + 8 * math.sin(i / 3.1) + 0.2 * i for i in range(70)]
    highs = [c + 1 + 0.4 * math.cos(i) ** 2 for i, c in enumerate(closes)]
    lows = [c - 1 - 0.3 * math.sin(i) ** 2 for i, c in enumerate(closes)]
    return highs, lows, closes


def _zero_range_series():
    """The long series with zero-range bars (high=low=previous close) after movement."""
    highs, lows, closes = _long_series()
    for i in (35, 36, 52, 53, 54):
        closes[i] = closes[i - 1]
        highs[i] = lows[i] = closes[i]
    return highs, lows, closes


def _inside_series():
    """Highs mostly fall (alternately 0.5 and 0.3, +2 every 6th bar) while lows rise 0.4 (or fall 1 every
    4th bar). Many bars have up<0 and down<0 with up>down, so a negative raw +DM must be treated as 0,
    while enough positive -DM keeps DI sums positive."""
    highs, lows = [200.0], [80.0]
    for i in range(1, 40):
        highs.append(highs[-1] + 2 if i % 6 == 0 else highs[-1] - (0.5 if i % 2 == 0 else 0.3))
        lows.append(lows[-1] - 1 if i % 4 == 0 else lows[-1] + 0.4)
    return highs, lows, [(h + l) / 2 for h, l in zip(highs, lows)]


class EmaTests(unittest.TestCase):
    def test_hand_computed(self):
        # period 3, a=0.5: seed (2+4+6)/3=4; 0.5*8+0.5*4=6; 0.5*4+0.5*6=5
        self.assertEqual(ema([2, 4, 6, 8, 4], 3), [None, None, 4.0, 6.0, 5.0])

    def test_period_one_is_identity(self):
        self.assertEqual(ema([3, 1, 2], 1), [3.0, 1.0, 2.0])

    def test_flat_series(self):
        self.assertEqual(ema([7.0] * 6, 4), [None] * 3 + [7.0] * 3)

    def test_short_series_all_warmup(self):
        self.assertEqual(ema([1, 2], 3), [None, None])
        self.assertEqual(ema([], 3), [])

    def test_no_look_ahead(self):
        full = ema([2, 4, 6, 8, 4, 9, 1], 3)
        self.assertEqual(ema([2, 4, 6, 8, 4], 3), full[:5])

    def test_rejects_bad_input(self):
        for bad in ([1, True, 3], [1, float("nan"), 3], [1, float("inf"), 3], [1, "2", 3], None, "abc"):
            with self.assertRaises(ValueError):
                ema(bad, 2)
        for period in (0, -1, True, 2.0, "3", None):
            with self.assertRaises(ValueError):
                ema([1, 2, 3], period)


class TrueRangeAtrTests(unittest.TestCase):
    H = [10, 12, 11, 13]
    L = [8, 9, 9, 10]
    C = [9, 11, 10, 12]

    def test_true_range_hand(self):
        # 2; max(3,3,0)=3; max(2,0,2)=2; max(3,3,0)=3
        self.assertEqual(true_range(self.H, self.L, self.C), [2.0, 3.0, 2.0, 3.0])

    def test_gap_up_uses_previous_close(self):
        # prev close 10, bar 14-15: max(1, 5, 4) = 5
        self.assertEqual(true_range([11, 15], [9, 14], [10, 14.5]), [2.0, 5.0])

    def test_atr_wilder_hand(self):
        # seed (2+3+2)/3 = 7/3; then (7/3*2+3)/3 = 23/9
        out = atr(self.H, self.L, self.C, 3)
        self.assertIsNone(out[0])
        self.assertIsNone(out[1])
        self.assertAlmostEqual(out[2], 7 / 3, places=12)
        self.assertAlmostEqual(out[3], 23 / 9, places=12)

    def test_flat_series_zero_range(self):
        self.assertEqual(atr([5] * 4, [5] * 4, [5] * 4, 2), [None, 0.0, 0.0, 0.0])

    def test_rejects(self):
        with self.assertRaises(ValueError):
            true_range([1, 2], [1], [1, 2])  # length mismatch
        with self.assertRaises(ValueError):
            true_range([1, 2], [3, 1], [1, 2])  # high below low
        with self.assertRaises(ValueError):
            true_range([1, True], [0, 0], [1, 1])
        with self.assertRaises(ValueError):
            true_range([1, float("nan")], [0, 0], [1, 1])
        with self.assertRaises(ValueError):
            atr([1, 2], [0, 1], [1, 2], 0)


class AdxTests(unittest.TestCase):
    def test_monotonic_trend_is_100(self):
        # every bar: +DM=1, -DM=0, TR=1.5 -> DX=100 throughout, first ADX at index 2p-1=3
        highs, lows = [10, 11, 12, 13, 14], [9, 10, 11, 12, 13]
        closes = [9.5, 10.5, 11.5, 12.5, 13.5]
        out = adx(highs, lows, closes, 2)
        self.assertEqual(out[:3], [None] * 3)
        self.assertAlmostEqual(out[3], 100.0, places=9)
        self.assertAlmostEqual(out[4], 100.0, places=9)

    def test_mixed_hand_computed(self):
        # i1: +DM2 TR2.5; i2: -DM1 TR2.5; i3: +DM1 TR2.
        # idx2 sums TR5 +DM2 -DM1 -> DI 40/20 -> DX 100/3.
        # idx3 sums TR4.5 +DM2 -DM0.5 -> DI 44.44/11.11 -> DX 60. ADX[3]=(100/3+60)/2=140/3
        out = adx([10, 12, 11, 12], [9, 10, 9, 10], [9.5, 11.5, 10, 11.5], 2)
        self.assertEqual(out[:3], [None] * 3)
        self.assertAlmostEqual(out[3], 140 / 3, places=9)

    def test_matches_independent_reference(self):
        closes = [50 + 3 * math.sin(i / 2.3) + i * 0.15 for i in range(60)]
        highs = [c + 1 + 0.3 * math.cos(i) ** 2 for i, c in enumerate(closes)]
        lows = [c - 1 - 0.2 * math.sin(i) ** 2 for i, c in enumerate(closes)]
        for period in (3, 7, 14):
            got = adx(highs, lows, closes, period)
            want = reference_adx(highs, lows, closes, period)
            self.assertEqual(len(got), 60)
            self.assertEqual([v is None for v in got], [v is None for v in want])
            first = next(i for i, v in enumerate(got) if v is not None)
            self.assertEqual(first, 2 * period - 1)
            for a, b in zip(got, want):
                if a is not None:
                    self.assertAlmostEqual(a, b, places=9)
                    self.assertTrue(0 <= a <= 100)

    def test_long_series_against_literal_reference_values(self):
        # Literals produced by an independent script (exact fractions.Fraction arithmetic, TA-Lib style
        # sum recurrence S = S - S/p + x, no code shared with indicators.py) on this 70-bar series, period 14.
        out = adx(*_long_series(), 14)
        self.assertEqual(out[:27], [None] * 27)
        for index, want in ((27, 27.642112222272218), (28, 27.06770629515356), (50, 23.316037445613862),
                            (60, 20.93749650199548), (69, 23.928154911424503)):
            self.assertAlmostEqual(out[index], want, places=9, msg=index)

    def test_zero_range_bars_keep_smoothed_true_range(self):
        # Literals from the same independent Fraction reference. ADX is invariant to the TR scale, so the
        # Wilder-smoothed TR only matters when the current TR is zero but the smoothed sum is not: a
        # non-smoothed TR would force DX to 0 on these bars.
        out = adx(*_zero_range_series(), 14)
        for index, want in ((37, 21.544747985657565), (50, 24.932834676175393), (55, 21.999729211896174),
                            (56, 21.225308563002198), (69, 22.63378380059624)):
            self.assertAlmostEqual(out[index], want, places=9, msg=index)

    def test_negative_directional_movement_is_ignored(self):
        # Inside bars give up<0 and down<0; a negative raw DM must count as 0. Literals from the same
        # independent Fraction reference script, period 5.
        out = adx(*_inside_series(), 5)
        self.assertEqual(out[:9], [None] * 9)
        for index, want in ((9, 40.46663937781416), (10, 34.03520261972984), (20, 34.01134307812158), (30, 35.86010537431023), (39, 45.3192495085162)):
            self.assertAlmostEqual(out[index], want, places=9, msg=index)

    def test_flat_series_is_zero_not_nan(self):
        out = adx([5] * 8, [5] * 8, [5] * 8, 2)
        self.assertEqual(out[:3], [None] * 3)
        self.assertEqual(out[3:], [0.0] * 5)

    def test_gap_series_finite_and_bounded(self):
        highs = [10, 10.5, 20.5, 21, 21.2, 21.5, 22]
        lows = [9, 9.5, 19.5, 20, 20.2, 20.5, 21]
        closes = [9.5, 10, 20, 20.5, 20.7, 21, 21.5]
        out = adx(highs, lows, closes, 2)
        self.assertTrue(all(v is None or (math.isfinite(v) and 0 <= v <= 100) for v in out))

    def test_short_series_all_warmup(self):
        self.assertEqual(adx([2, 3, 4], [1, 2, 3], [1.5, 2.5, 3.5], 2), [None] * 3)
        self.assertEqual(adx([], [], [], 14), [])

    def test_no_look_ahead(self):
        closes = [50 + 3 * math.sin(i / 2.0) for i in range(40)]
        highs = [c + 1 for c in closes]
        lows = [c - 1 for c in closes]
        full = adx(highs, lows, closes, 5)
        part = adx(highs[:30], lows[:30], closes[:30], 5)
        self.assertEqual(part, full[:30])

    def test_rejects(self):
        with self.assertRaises(ValueError):
            adx([1, 2], [0, 1], [1], 2)
        with self.assertRaises(ValueError):
            adx([1, 2], [0, 1], [1, float("nan")], 2)
        with self.assertRaisesRegex(ValueError, r"closes\[1\].*boolean"):
            adx([1, 2], [0, 1], [1, False], 2)
        with self.assertRaises(ValueError):
            adx([1, 2], [0, 1], [1, 2], True)


if __name__ == "__main__":
    unittest.main()
