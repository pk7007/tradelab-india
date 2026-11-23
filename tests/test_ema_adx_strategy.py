import datetime as dt
import math
import unittest

from indicators import adx, ema
from ema_adx_strategy import ema_adx_signal, ema_adx_scan, VERSION


def make(closes, spread=1.0):
    start = dt.date(2026, 1, 1)
    return [{"date": (start + dt.timedelta(days=i)).isoformat(), "open": c, "high": c + spread, "low": c - spread, "close": c, "volume": 1}
            for i, c in enumerate(closes)]


def series():
    # long decline, then a sharp rise that produces one EMA20/EMA50 upward cross
    return [200 - i for i in range(70)] + [130 + 4 * i for i in range(40)]


def cross_index(candles):
    closes = [c["close"] for c in candles]
    fast, slow = ema(closes, 20), ema(closes, 50)
    hits = [i for i in range(50, len(closes)) if fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]]
    return hits


class EmaAdxSignalTests(unittest.TestCase):
    def test_signal_only_on_the_crossover_bar_not_state(self):
        candles = make(series())
        hits = cross_index(candles)
        self.assertEqual(len(hits), 1)
        k = hits[0]
        at = ema_adx_signal(candles[:k + 1], adx_threshold=0)
        self.assertEqual(at["action"], "ENTER_LONG")
        self.assertEqual(at["reason"], "ema_cross_up_adx_ok")
        before = ema_adx_signal(candles[:k], adx_threshold=0)
        after = ema_adx_signal(candles[:k + 2], adx_threshold=0)
        self.assertEqual(before["reason"], "no_crossover")  # state is bearish, no cross yet
        self.assertEqual(after["reason"], "no_crossover")   # state bullish but not a cross
        self.assertGreater(after["ema20"], after["ema50"])

    def test_warmup_skip(self):
        candles = make(series())[:50]
        out = ema_adx_signal(candles)
        self.assertEqual((out["action"], out["reason"]), ("SKIP", "insufficient_history"))
        self.assertEqual(ema_adx_signal([])["reason"], "insufficient_history")

    def test_low_adx_skip(self):
        candles = make(series())
        k = cross_index(candles)[0]
        closes = [c["close"] for c in candles[:k + 1]]
        value = adx([c["high"] for c in candles[:k + 1]], [c["low"] for c in candles[:k + 1]], closes, 14)[-1]
        self.assertTrue(0 < value < 100)
        out = ema_adx_signal(candles[:k + 1], adx_threshold=min(100.0, value + 0.5))
        self.assertEqual((out["action"], out["reason"]), ("SKIP", "adx_below_threshold"))
        self.assertAlmostEqual(out["adx"], value, places=9)
        # threshold equal to ADX is allowed (>=)
        ok = ema_adx_signal(candles[:k + 1], adx_threshold=value)
        self.assertEqual(ok["action"], "ENTER_LONG")

    def test_no_repeated_signal_for_same_bar(self):
        candles = make(series())
        k = cross_index(candles)[0]
        first = ema_adx_signal(candles[:k + 1], adx_threshold=0)
        again = ema_adx_signal(candles[:k + 1], adx_threshold=0, last_signal_date=first["date"])
        self.assertEqual((again["action"], again["reason"]), ("SKIP", "duplicate_signal"))

    def test_scan_emits_once_per_crossover(self):
        candles = make(series())
        decisions = ema_adx_scan(candles, adx_threshold=0)
        self.assertEqual(len(decisions), len(candles))
        entries = [i for i, d in enumerate(decisions) if d["action"] == "ENTER_LONG"]
        self.assertEqual(entries, cross_index(candles))

    def test_deterministic_and_pure(self):
        candles = make(series())
        snapshot = [dict(c) for c in candles]
        a = ema_adx_scan(candles)
        b = ema_adx_scan(candles)
        self.assertEqual(a, b)
        self.assertEqual(candles, snapshot)
        self.assertEqual(a[-1]["version"], VERSION)

    def test_no_look_ahead_prefix_equality(self):
        candles = make(series())
        full = ema_adx_scan(candles)
        self.assertEqual(ema_adx_scan(candles[:90]), full[:90])

    def test_invalid_input(self):
        good = make(series())
        bad = [dict(c) for c in good]
        bad[10]["close"] = float("nan")
        with self.assertRaises(ValueError):
            ema_adx_signal(bad)
        bad = [dict(c) for c in good]
        bad[10]["high"] = True
        with self.assertRaises(ValueError):
            ema_adx_signal(bad)
        for threshold in (-1, 101, True, float("nan"), "20"):
            with self.assertRaises(ValueError):
                ema_adx_signal(good, adx_threshold=threshold)
        with self.assertRaises(ValueError):
            ema_adx_signal("not candles")
        with self.assertRaises(ValueError):
            ema_adx_signal(good, fast=50, slow=20)

    def test_equality_on_previous_bar_counts_as_cross(self):
        # fast=2, slow=3: closes 10,10,10 make both EMAs exactly 10 (equal); next close 12 -> fast 11.33 > slow 11.
        candles = make([10.0, 10.0, 10.0, 12.0])
        out = ema_adx_signal(candles, fast=2, slow=3, adx_period=1, adx_threshold=0)
        self.assertEqual((out["action"], out["reason"]), ("ENTER_LONG", "ema_cross_up_adx_ok"))
        self.assertEqual(ema_adx_signal(candles[:3], fast=2, slow=3, adx_period=1, adx_threshold=0)["reason"], "insufficient_history")

    def test_equality_on_current_bar_is_not_a_cross(self):
        # fast=1 (close), slow=2: idx1 fast 8 < slow 9; idx2 close 9 -> slow = 2/3*9+1/3*9 = 9 == fast.
        candles = make([10.0, 8.0, 9.0])
        out = ema_adx_signal(candles, fast=1, slow=2, adx_period=1, adx_threshold=0)
        self.assertEqual(out["ema20"], out["ema50"])
        self.assertEqual((out["action"], out["reason"]), ("SKIP", "no_crossover"))

    def test_date_validation(self):
        good = make(series())
        dup = [dict(c) for c in good]
        dup[30]["date"] = dup[29]["date"]
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            ema_adx_signal(dup)
        unsorted = [dict(c) for c in good]
        unsorted[30]["date"], unsorted[31]["date"] = unsorted[31]["date"], unsorted[30]["date"]
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            ema_adx_scan(unsorted)
        junk = [dict(c) for c in good]
        junk[5]["date"] = "not a date"
        with self.assertRaises(ValueError):
            ema_adx_signal(junk)
        mixed = [dict(c) for c in good]
        mixed[5]["date"] = "2026-01-06T00:00:00+05:30"
        with self.assertRaises(ValueError):
            ema_adx_signal(mixed)
        missing = [dict(c) for c in good]
        del missing[3]["date"]
        with self.assertRaises(ValueError):
            ema_adx_signal(missing)

    def test_last_signal_date_validation_and_comparison(self):
        candles = make(series())
        k = cross_index(candles)[0]
        day = candles[k]["date"]
        for bad in (123, "garbage", True):
            with self.assertRaises(ValueError):
                ema_adx_signal(candles[:k + 1], adx_threshold=0, last_signal_date=bad)
        # equivalent instant in another notation is the same date, not a different string
        same = dt.date.fromisoformat(day).isoformat() + "T00:00:00"
        out = ema_adx_signal(candles[:k + 1], adx_threshold=0, last_signal_date=same)
        self.assertEqual(out["reason"], "duplicate_signal")
        with self.assertRaises(ValueError):
            ema_adx_signal(candles[:k + 1], adx_threshold=0, last_signal_date=day + "T00:00:00+05:30")
        older = ema_adx_signal(candles[:k + 1], adx_threshold=0, last_signal_date=candles[k - 1]["date"])
        self.assertEqual(older["action"], "ENTER_LONG")

    def test_flat_series_skips(self):
        out = ema_adx_signal(make([100.0] * 80, spread=0.0))
        self.assertEqual(out["action"], "SKIP")
        self.assertTrue(math.isfinite(out["adx"]))
        self.assertEqual(out["reason"], "no_crossover")


if __name__ == "__main__":
    unittest.main()
