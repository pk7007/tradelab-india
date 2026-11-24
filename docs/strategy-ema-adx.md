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

## Phase 5: intraday rules, walk-forward, adjustments and status (research only)

- `ema_adx_backtest.py` (5-minute, `ema20-50-adx14-intraday-5m-v1`): entry signals from `ema_adx_strategy` fill at the NEXT
  open, only while flat and only if the FILL bar is before the saved entry cutoff (as in the paper engine: a 14:25 signal
  would fill at 14:30 and is rejected when the cutoff is 14:30). Bars must be consecutive 5-minute candles inside each session
  (a missing or irregular bar is refused); overnight gaps between sessions are normal. Exits in priority order: stop (intrabar; gaps fill at the open),
  target (`entry + (entry - stop) * targetMultiple`), trend exit (EMA20 below EMA50 on a completed bar, next open) and
  square-off (at or after the saved time, next open). Size, stop, target, costs and the daily loss limit reuse the saved
  limits and `intraday_contract.entry_size`. Gap risk is not hidden: a gap through the stop can lose more than `maxLoss`.
- Unit (a) tests: `tests/test_ema_adx_backtest.py` (34), including scripted scenarios that force every exit path, no-lookahead,
  determinism, accounting reconciliation and the no-profit-claim fields.
- Unit (b) walk-forward: `walk_forward` uses `research.chronological_splits` (expanding test windows) over ONE continuous
  account with parameters fixed in every fold (nothing is tuned or trained: `train` is only the preceding history and the
  label horizon, default one session, just lets a trade entered late in a window reach its real exit instead of being
  cut off at the window end). Only trades ENTERED inside a window count. Cash carries over, so windows are not independent,
  and bars beyond a window plus the horizon never influence it. It reports counts and net figures per window and pooled,
  and states no edge. Synthetic fixtures prove mechanics only; no real-data result exists.
- Unit (c) adjustments: `adjust_for_actions` back-adjusts bars dated before an action's effective date (`ratio` = new shares per old share: a 2-for-1 split is 2, a 1:1 bonus is 2, a 1:2 bonus is 1.5; split and bonus:
  price / ratio, volume * ratio; cash dividend: price * (1 - amount / prior raw close)). The owner supplies the actions; the
  code does not look them up, and dividends use the raw prior close.
- Unit (d) status: `strategy_registry.py` records both EMA/ADX versions as `research-only`, not paper-approved, not promoted,
  with the blockers below; `tests/test_strategy_registry.py` proves the paper engine still refuses them
  ("Unknown paper strategy version") and that the registry agrees with what the engine accepts.

### Running it (offline)
`python scripts/ema_adx_report.py --bars bars.json --config config.json [--actions actions.json] [--walk-forward]` reads local
JSON only and prints a JSON report. It places no order and touches no database or broker (`tests/test_ema_adx_report.py`).

### Why it is not wired into the paper engine
1. Entry checks in `entry_review.py`, `paper.py` and `intraday_contract.py` call the SMA 5/20 rule directly.
2. The engine resets its candle history each session, and EMA50 needs 50 completed 5-minute bars (first defined about 13:25 IST),
   leaving little of the 14:30 entry window. Carrying history across sessions would change the engine's state contract.
3. There is no walk-forward evidence on real adjusted data.
4. Creating a paper account with it and starting it remain owner actions through the existing controls; nothing promotes it.

Wiring it in later needs a deliberate engine change (a strategy interface, cross-session history, reviewed separately), not a flag.
