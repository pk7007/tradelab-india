# Research implementation and release status

Updated 2026-10-31. This is a partial research implementation, not a validated trading system.

## Implementation plan and results

1. Inspect the existing local Kite app and preserve its credentials and manual order flow: complete.
2. Verify available source types and data limitations: initial evidence register below; no company investment thesis has been verified.
3. Add explainable, price-only intraday and swing ranking: implemented, offline fixtures tested; authenticated real-data validation pending.
4. Add deterministic execution stress simulations and offline risk contracts: implemented and tested. These are not connected to broker execution.
5. Add metadata experiment fingerprints and chronological split utility: implemented. Full walk-forward research, final holdout evaluation, and persistent experiment governance are not implemented.
6. Validate point-in-time fundamentals, corporate actions, historic membership, costs and execution assumptions before strategy deployment: blocked by missing licensed datasets and unfinished integrations.
7. Configure and approve live strategy/risk settings: pending user decisions. No automated live strategy exists.

## Using the screens

Refresh the local app and choose Strategy lab. Run Execution stress lab without logging into a broker. It runs 8 synthetic paths with 3 cost/delay variants, using stated illustrative settings, never your account balance. Reports include loss-making outcomes. These experiments do not establish profitability.

For descriptive stock rankings, connect Zerodha and finish a historical request in Market data. Choose Strategy lab, select swing (daily candles) or intraday (five-minute candles), then evaluate. Current time is the cutoff. Daily analysis excludes today's potentially incomplete candle. Intraday requires 21 contiguous completed bars from the current session. Old history is rejected for current rankings. The timestamp shows the actual candle coverage. No calendar-completeness claim is made for daily bars.

Long-term mode returns insufficient evidence because point-in-time fundamentals are unavailable. Every score is simply trailing 20-bar price return in percent; volatility and approximate turnover are context, not hidden scoring weights. Positive momentum is an illustrative filter, not empirically validated. Missing sector, corporate-action and event information remains a prominent limitation. No data is automatically downloaded by ranking.

Session experiment metadata retains the latest 30 attempts, including failures; it is not durable experiment governance. Hashes identify the data and report; they do not establish untouched-holdout independence. Reloading loses these records. The test report and synthetic stress report are reproducible local artifacts.

## Evidence register

All sources retrieved 2026-10-31. These continuously maintained pages did not provide a stable publication date in the inspected content; publication date is recorded as unavailable, not inferred from retrieval. No company filings were ingested or analyzed.

| Source | Evidence / implementation consequence | Permission or coverage limitation |
| --- | --- | --- |
| [Kite historical API](https://kite.trade/docs/connect/v3/historical/) | OHLCV interval data and instrument-token limitations | Does not supply point-in-time fundamentals or a survivorship-free stock universe |
| [Kite terms](https://kite.trade/terms/) | Restrictions on retention, redistribution and certain uses | No blanket rights inferred; permanent storage remains gated; synthetic stress lab uses no Kite data |
| [Kite order API](https://kite.trade/docs/connect/v3/orders/) | Order state and trade records are distinct from submission | Future execution must reconcile broker state; offline risk contract is not an adapter |
| [NSE announcements](https://www.nseindia.com/companies-listing/corporate-filings-announcements) | Potential official company disclosure source | Automated ingestion rights and publication-time history not established; not scraped |
| [NSE financial results](https://www.nseindia.com/companies-listing/corporate-filings-financial-results) | Potential fundamentals evidence source | No filing-based model claimed without ingestion and revision controls |
| [Zerodha charges](https://zerodha.com/charges/) | Multiple product- and side-dependent charges exist | Flat basis-point stress costs are illustrative, not a verified historical tax/fee engine |

## Test coverage and exclusions

See research-test-results.md for actual per-test outcomes and commands. Tests use synthetic fixtures and mocked state, not real accounts.

Implemented: malformed/duplicate/out-of-order/stale bars; timezone requirements; intraday gaps; future bars; next-open fills; gap-stop fills; halts; participation-limited partial fills; rejection; cash reconciliation; costs and delays; disarm on new risk instance; duplicate signal gate; stale/reconciliation/exposure/loss gates; cancellation intents without false position closure.

Not implemented or not run: actual API-expiry/rate-limit/network integration tests; broker reconciliation and persistence across crashes; concurrent production duplicate-order prevention; real cancellations; circuit-limit/queue simulation; splits/dividends/symbol changes; fiscal publication-time data; historical membership; portfolio correlated-loss simulation; real historical regime studies; ranking forward-return calibration; statistically supported uncertainty intervals; matched net benchmark; tax schedule; holdout registry; long-term model.

The risk contract is an offline sequential prototype. Its checks do not protect the existing manual-order route. Its kill method returns cancellation intents only, does not call the broker, and cannot close positions. It is not a production risk manager.

## Release gates

- Offline implemented-component correctness: passed; see test report.
- Comprehensive requested failure matrix: incomplete, exclusions above.
- Licensed point-in-time dataset and actual corporate disclosures: pending.
- Real-data out-of-sample validation and cost verification: not run.
- Approved financial limits, exact strategy, production execution controls: pending.
- Automated live trading: disabled/unimplemented. No orders submitted during development.

Loss thresholds cannot bound realized losses in all circumstances. The evidence supports selected software invariants and deterministic synthetic behavior only, not future returns.
