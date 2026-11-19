# Operator capability map — 18 November 2026

This is a source-inspection map, not a claim that a live broker session or every browser workflow was exercised. Local credentials and current account balances were not inspected. Automated real-money readiness is not demonstrated. Isolated browser checks of the home readiness display, repeated synthetic evaluation and paper entry-pause/close/reconciliation passed on 18 November; see the [repair report](system-repair-2026-11-18.md).

## Visible workspaces

| Route or workspace | Current implementation | Boundary / missing evidence |
|---|---|---|
| `/` account overview, orders, holdings, positions | Broker read adapters and account calculations; offline calculation tests exist | Valid authentication, broker responses, permissions and current balances require runtime verification. Login does not reconcile strategy ownership. |
| `/` manual order review | Explicit review and confirmation; server validation; durable safety changes tracked in implementation report | Acceptance is not a fill. Uncertain outcomes require reconciliation; do not submit again just because the browser lost a response. |
| `/` automation | Versioned configuration, coordinator ledger and local controls | Live scheduler/dispatch unavailable. Pause/stop do not cancel real orders or sell real positions. |
| `/` market data | Instrument lookup, historical jobs, private last-price chart and stream freshness handling | Live connectivity and licensed retention require verification. Chart is not a complete tick archive. |
| `/` research | Synthetic demonstration and research inputs | Fixture results do not establish profitability or a deployable strategy. |
| `/trader-scanner` | Imported candle setup heuristics | No continuous market-wide feed. Imported symbols are not a point-in-time universe. |
| `/trader-news` | Imported news/watchlist filtering and availability cutoff | Live publisher monitoring disconnected; links are manual research destinations. |
| `/trader-entry` | Completed-bar snapshot evaluation | No continuous entry watcher or executable recommendation. |
| `/trader-exit` | Long-only stop/target planning | Does not send protective broker orders; gaps can exceed modeled stop loss. |
| `/trader-timemachine` | Bootstrap scenarios and in-sample setup matches | Not every possible outcome; no independent predictive validation. |
| `/trader-risk` | Snapshot risk calculation and paper-draft gating | User-entered exposure is not authoritative broker inventory. |
| `/trader-budget` | Whole-unit sizing including supplied costs/slippage | Not broker margin or historical tax calculation; gaps remain unbounded. |
| `/trader-broker` | Explicitly approved hypothetical paper orders | Session-only paper book, lost on restart; supplied entry price is not a market fill. |
| `/trader-alerts` | Snapshot threshold checks and optional current-stream browser watcher | Requires existing stream. No closed-tab delivery or automatic exits. |
| `/trader-analyst` | Structured earnings JSON comparisons | No automatic PDF extraction or continuous filing feed. |
| `/trader-pelosi` | Imported US congressional disclosures | No live filing feed; unrelated to Indian equity execution and trades may precede filing. |
| `/trader-evaluate` | Fixed SMA evaluation, chronological windows, next-open fills and hold benchmark | Single-symbol price-return model; not a full intraday liquidation or dividend-aware long-term engine. |
| `/trader-paper` | Durable simulated cash/positions/events, imports, synthetic feed fixture, ledger checks and controls | Independent simulation capital per account; not broker-funded strategy allocation. Full next-open simulated fills, no continuous real feed. |

## Operator distinctions

Credentials configured, token present, current market data, broker reconciliation, paper eligibility and live enablement are different states. The account header now displays those distinctions without treating authentication as readiness.

The paper screen explains that its account capital is independent. It displays existing shares separately from the control state. Pause new entries preserves exit processing; cancel pending entry removes an unfilled buy; simulated close requests need a future permitted observed bar. Pause all ingestion freezes exits too. A stop leaves existing shares held. None of these controls changes a real broker position.

A manual order review is invalidated when order inputs change. A preview response arriving after an edit or a newer preview is ignored, preventing an older preview from replacing the order currently being reviewed. This is UI protection in addition to server-side validation.

## Checks for these UI changes

- `node --check web/app.js`
- `node --check web/paper.js`
- `node tests/account.test.js`
- `node tests/order-review.test.js`

The review regression uses VM mocks of the preview handlers to exercise edited-input and overlapping-request responses. These checks do not exercise a browser rendering engine, live broker authentication or real-money submission. Full end-to-end browser verification remains a separate check.

## Durable manual recovery surface

The main workspace displays durable manual intents separately from the mock automation ledger, including requested/filled quantities, uncertain and partial states, broker order IDs and evidence. Refresh reads the journal; Reconcile reads broker orders and trades and does not place orders. The interface explicitly reports positions as unreconciled. Submission outcomes refresh this view, including request errors. The live-readiness reason comes from server status; configuration alone cannot unlock manual dispatch. A separate Resume new entries paper control preserves the distinction between entry pause and total ingestion pause.
