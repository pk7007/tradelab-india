# EMA 20/50 + ADX trend strategy (research only)

Status: research and backtest function. It has **no validated edge**; nothing here is a profitability
claim, and it grants no authority to place orders, change risk limits or promote a strategy.

## Modules
- `indicators.py`: `ema`, `true_range`, `atr`, `adx`. Pure, aligned with the input, `None` during warm-up, never NaN.
- `ema_adx_strategy.py`: `ema_adx_signal(candles, ...)` (decision for the last completed candle) and
  `ema_adx_scan(candles, ...)` (one decision per candle, each using only data up to that candle).
- Tests: `tests/test_indicators.py` (hand-computed fixtures plus an independent reference ADX),
  `tests/test_ema_adx_strategy.py`.

## Rules
- EMA: seeded with the simple mean of the first N closes, alpha = 2/(N+1). EMA50 is first defined at bar 50.
- ATR/ADX: Wilder smoothing, period 14. The first ADX value appears at index 27 (2*14-1), the same lookback as TA-Lib.
- ATR convention differs from TA-Lib: here TR[0] = high-low is included, so the first ATR is at index p-1;
  TA-Lib excludes TR[0] and first reports ATR at index p. Early ATR values therefore differ. (ADX does not use this ATR.)
- Candle dates must be ISO-8601 strings, strictly increasing and all naive or all zoned; otherwise `ValueError`.
  `last_signal_date` is parsed and compared as a date-time, not as a raw string.
- Entry (long only): on the current completed bar EMA20 > EMA50 **and** on the previous bar EMA20 <= EMA50
  (a true crossover, not a bullish state), **and** ADX >= threshold (default 20).
- Decisions are `ENTER_LONG` or `SKIP` with a reason: `insufficient_history`, `no_crossover`,
  `adx_below_threshold`, `duplicate_signal`. A decision on candle N applies to the next open.
- Duplicate prevention: pass `last_signal_date`; the same bar cannot signal twice. A crossover occurs on a
  single bar, so the scan emits at most one entry per crossover.
- There is **no exit rule**. Sizing, stops and exits are outside this module.

## Assumptions and limits
- Caller must supply completed candles only, with `date` (string), `high`, `low`, `close`. Candles are
  not checked for gaps, holidays, splits or dividends; unadjusted gaps distort EMA/ATR/ADX.
- Zero-range markets give ADX 0 and `no_crossover`; flat series never signal.
- Defaults (20/50/14/20) are conventional, not tuned or validated. Tuning on a holdout weakens evidence.
- Transaction costs, slippage and liquidity are not modelled here.
- Not wired into `evaluation.py`: that module is hard-wired to the SMA(5/20) protocol, and its dataset and
  result fingerprints carry the protocol version, so adding a strategy switch would change existing contracts.

## How to wire it into evaluation later
`evaluation._portfolio(bars, signals, ...)` takes `signals[i]`, a target-long state determined before open `i`.
This strategy is entry-only, so first define an exit (for example EMA20 < EMA50) and build the state list
from `ema_adx_scan(bars[:i])` for each `i`, holding long between an entry and the exit. Give it a distinct
protocol version, window fingerprint and limitations text, add tests, and keep the SMA path unchanged.
