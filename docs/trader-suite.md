# Trader suite — import-first release

Updated 2026-11-03. User chose imports first; external feeds will be selected later. All eleven requested routes are implemented as local tool workspaces. This is not an autonomous end-to-end live bot.

| Route | Implemented behavior | Remaining boundary |
| --- | --- | --- |
| /trader-scanner | Batch ORB, flag and oversold-bounce heuristics on imports, max 2,000 symbols / 100,000 bars | No exchange-wide streaming scanner; unvalidated rules |
| /trader-news | Imported watchlist filtering, URL deduplication, keyword tags, publication timestamps | No breaking-news feed or causal movement attribution |
| /trader-entry | Completed-bar setup evaluation and step-by-step imported-history replay | No live setup scheduler or best-entry guarantee |
| /trader-exit | Validates user-selected long entry/stop/target; models stop risk | No stop placement or guaranteed exit |
| /trader-timemachine | 10,000 seeded bootstrap paths plus setup occurrences within imported history | Not every possible outcome; gross historical forward returns, no independent validation |
| /trader-risk | Exposure, pending exposure, daily loss and whole-unit affordability checks | User inputs, not real broker snapshot; protects paper draft only |
| /trader-budget | Whole-unit sizing bounded by capital and modeled loss, including supplied costs/slippage | Long-only; gap and tax limitations |
| /trader-broker | Server-created expiring paper review, explicit approval, single consumption and session paper book | Hypothetical user-price fills only; session data lost on restart; no live order call |
| /trader-alerts | Manual threshold checks, existing private stream monitoring, optional sound and scheduled bell reminder | Page must stay open; current stream only; calendar/date selected by user |
| /trader-analyst | Structured current/prior earnings metric comparisons with units, periods and source references | No PDF extraction, accounting validation or automatic filings feed |
| /trader-pelosi | Imported U.S. disclosure records, filer/owner preservation, deduplication and filing-delay display | No continuous filing ingestion, no trading signals from disclosures |

## Import contracts

Use each screen's labeled synthetic example to see the exact JSON schema. Examples are invented test fixtures and never labeled real. Source URLs are retained as text and are not fetched by the app.

Candles: an object mapping symbol to ordered OHLCV arrays, each with timezone-aware date, open/high/low/close/volume. Use five-minute start timestamps from 09:15 through 15:25 India time. Cutoff excludes unfinished/future bars. Duplicate/out-of-order timestamps and malformed prices are rejected. Missing within-session bars suppress setup detection. No exchange holiday verification exists. Overall upload limit 7.5 MB; request body 8 MB. Thousands of symbols require sufficiently short windows within these limits.

News: records with title, symbols array, publishedAt and HTTPS url. Watchlist matching uses exact supplied symbol tags, not ambiguous name inference.

Earnings: metric, current, previous, unit, period, priorPeriod, publishedAt and HTTPS source. Percentage change uses absolute previous value; zero baseline returns no percentage. Confirm consolidated/standalone basis and comparable periods yourself.

Disclosures: filingId, filer, owner, asset, transactionDate, filedAt, amountRange and HTTPS source. This tool accepts any member's records; it does not label spousal transactions as a member's own trades. Amount ranges remain ranges. No allegations or investment edge are inferred.

Permission checkbox is required for imported analysis. No imported records are automatically written to disk, committed or sent to external providers. Trade-plan form fields can be carried across workspace links in browser sessionStorage; clear the tab session when finished. Paper book is server-session memory, not a permanent accounting ledger.

## Model limits

ORB uses a close crossing the high of 09:15/09:20/09:25 candles. Bull flag is a >3% pole followed by <3% five-bar range and close breakout. Oversold bounce uses a simple 14-change RSI below 35 and a higher close. These are illustrative definitions, not optimized or profitable strategies.

Time Machine samples imported close-to-close returns independently, seed 42, checking stop/target thresholds on sampled closes. Its percentiles and loss fraction describe the sampled distribution, not calibrated future probabilities. Historical matches enter at next open and report fixed-horizon gross returns. They do not simulate protective-order execution. No claim is made that all historical occurrences are present outside the supplied corpus.

Paper approval is not live authorization. Approval expires after 120 seconds and a draft is consumed once. Aggregate session-paper exposure is rechecked at approval. No paper record is a broker receipt. Existing live manual order entry remains separate and uses its own confirmation.

## Sources and testing

Official source references checked 2026-11-03: [Kite terms](https://kite.trade/terms/), [Kite order lifecycle](https://kite.trade/docs/connect/v3/orders/), [U.S. House disclosure portal](https://disclosures-clerk.house.gov/FinancialDisclosure). No feed rights or immediate filing availability are assumed. Automatic provider ingestion remains disconnected by user choice.

Run Python unittest discovery and node --check web/trader.js. Tests cover sizing, costs, risk blocks, completed bars, ORB, import permission, deterministic 10,000-path output, exact news-symbol matching, zero-base earnings comparisons, disclosure ownership/lag and threshold equality. These are software checks, not performance validation.

## Verification for this release

67 Python tests passed, including a 2,000-symbol synthetic scan and explicit single-use paper approval. Node account checks and trader JavaScript syntax passed. Local HTTP checks verified all 11 routes, missing-CSRF rejection, approval wording, duplicate approval rejection and cumulative paper exposure. Browser navigation verified all tools; scanner/news/earnings/disclosure synthetic imports and a sizing fixture completed successfully. No browser console errors were observed in those checked flows. Live stream alert/audio delivery, provider imports, real earnings PDFs and real broker execution were not tested.
