# Intraday readiness increment — 19 November 2026

This is a historical implementation record. Use
[current intraday automation](intraday-automation.md) for the automatic feed,
session controls and current acceptance steps, and the saved account profile
for its actual limits. The original figures and manual-ingestion workflow below
describe the 19 November release.

## Outcome and boundaries

An opt-in `intraday-v1` paper model adds risk-sized entries, modeled protective stops, partial exits and session square-off. Existing account configuration and history are preserved; the legacy SMA model is unchanged. This is imported-candle simulation, not unattended real-money execution or evidence of profit. The user’s ₹1,000 capital, ₹25 planned trade loss and ₹100 daily threshold remain the approved financial settings; stop distance, target multiple, participation and session times require explicit research inputs. These choices have not been approved for live deployment.

ECC’s installed discovery and code-review checklists informed the work. Separate agents owned the intraday engine, evidence validation and UI; independent review produced fixes for missing quote mapping, permissive calendar source URLs, retained recovery flags and dropped trading-halt metadata. The parent added exact-engine replay and integration checks. No credentials were read, live orders placed or GitHub publication performed.

## Implemented

- Long-only completed-close SMA signals, next observed open entries, whole-share caps, cash/exposure checks and entry/stop cost estimates. Entry size fits the smaller of per-trade allowance and remaining daily allowance.
- Price gaps can exceed planned risk. For ambiguous OHLC stop/target crossings the model chooses the stop. Participation limits cap total modeled shares per bar; unfilled entry remainder is cancelled, unfilled exits remain pending.
- Entry pause preserves exits. No candle means no invented exit. A missed prior-session exit carries visible exposure into recovery with entries paused. Explicit resume is required after recovery; there is no real broker square-off guarantee.
- Restart pauses running accounts and preserves stop/target and pending exit state. Journal reconstruction checks accounting before ingestion.
- `POST /api/trader/evaluate-intraday` replays the same engine and sizing in a temporary database. It reports unresolved exposure rather than inventing final liquidation. It is a diagnostic replay without independent holdout or benchmark certification.
- Provider-neutral quote/session validation requires mapped instruments, attributed timestamps, uncrossed quotes and explicit session coverage. Unknown calendar dates fail closed. This standalone contract is not a connected/verified calendar service.
- An optional research-output boundary separates cited facts, inferences and missing information, with exact symbol allowlists and source-time checks. Unknown execution/settings fields are rejected. Untrusted prose remains inert text; schema validation does not prove semantic truth. AI remains disconnected.

## Setup and operations

Restart the app to load the new backend. From Auto Trading, expand Setup and open paper account setup. Select Intraday v1, explicitly copy saved risk limits if desired, enter provider/provenance, costs/slippage, share cap, stop distance, target multiple, entry cutoff, square-off and participation assumptions. These are research settings, not a profitable strategy recommendation. New account creation does not alter old accounts or enable a provider.

Start permits ingestion; it does not connect a continuous feed. Import completed permitted candles in order. Watch pending exits, shares, protection and recovery status. Stop ingestion leaves shares held and cancels the local intent. Pause new entries keeps exit processing eligible. A partial close remains open until future accepted observations supply modeled liquidity.

After crash or mismatch, preserve files, review state and reconstruct the ledger before resuming. Never edit balances to clear a mismatch. Broker exposure, if any exists outside this simulation, must be managed through the broker; this engine cannot cancel or close it.

## Readiness rubric

Scores below are subjective assessments of the local offline product, with all dimensions retained. Nine requires operational integration evidence and no material unresolved loss paths; passing fixtures alone does not qualify.

| Dimension | Weight | Offline score | Evidence / limitation |
|---|---:|---:|---|
| Execution/recovery | 20% | 6 | Durable fixtures, partial exits and restart; no unified production scheduler |
| Accounting/ownership | 20% | 6 | Journal reconstruction and shared mock reservations; real ownership disconnected |
| Risk/exits | 20% | 6 | New stops/session/partial assumptions tested; OHLC and absent data remain limitations |
| Data integrity | 15% | 4 | Input checks and source contracts; no authorized forward feed/calendar adapter |
| Research validity | 15% | 3 | Same-engine replay and experiment history; no validated profitable edge or total-return long-term research |
| Security/operations | 5% | 5 | Loopback, CSRF, redaction, bounded sessions; no independent production security assessment |
| Usability | 5% | 6 | Three tabs and model-specific status; account creation/import remains Advanced |
| Weighted local readiness | 100% | **5.2/10** | No live-money or profitability claim |

Software prototype: 5.2/10 by the rubric. Imported-candle paper readiness: approximately 6/10 within documented model scope. Live-money readiness remains 2/10 because broker-wide funds/ownership, scheduling, session validation and confirmed exit integration are absent. Profitability is unproven and not rateable. These scores are not probabilities of profit.

## Remaining blockers

Critical before live money: one authoritative production execution/reservation path; broker funding/position/external-trade reconciliation; durable strategy approvals and scheduling leadership; verified instrument/product/margin/session rules; order IDs and monotone lifecycle across the full adapter; cancellation and protective/partial exit recovery under actual broker evidence. Live readiness gate remains closed.

Research dependencies: permitted historical/forward datasets, point-in-time universe/corporate actions, realistic taxes/spread/latency, independently defined promotion protocol, untouched holdouts and forward observations. Long-term fundamental/valuation and cash-flow total-return accounting are still incomplete. No website scraping or data rights were inferred.

External references checked: [Kite order lifecycle](https://kite.trade/docs/connect/v3/orders/), [historical candle format](https://kite.trade/docs/connect/v3/historical/) and [NSE session/holiday notices](https://www.nseindia.com/resources/exchange-communication-holidays). These do not certify account-specific permissions or the application's operational integration.

## Verification

Baseline 150 Python tests passed. Final suite: **178 Python tests passed**, all five JavaScript regression scripts passed, changed Python compilation and JavaScript syntax passed. `python scripts/fixture_recovery.py` again verified portal routes and legacy two-process paper restart with one fill, two skipped overlaps, five skipped retransmissions and a matching ledger. Tests use synthetic inputs/temporary databases; no provider-backed trading verification was performed.

The browser preview at `http://127.0.0.1:8775/` uses empty broker credentials and temporary ledgers. Account setup explicitly copied saved risk limits, required model assumptions, created Intraday v1, processed 21 invented candles and displayed nine shares, cash ₹80.62, modeled stop ₹99.96, target ₹106.08 and remaining daily allowance ₹99.52. Those prices and returns are fixtures, not market recommendations. All three tab views were inspected at a narrow viewport and screenshots captured. Broader device/accessibility/security testing remains outstanding.

Reproduce with `python -m unittest discover -s tests -q`, `node tests/intraday-ui.test.js`, the other regression scripts in CI, and `python scripts/fixture_recovery.py`. Replay API requires `{permitted:true, config:{strategy:'intraday-v1', ...explicit account assumptions}, bars:[...completed candles]}`. It uses temporary data only and does not publish an independent promotion record.

Known simulation limitation: per-order status events are journaled, but the new OHLC model does not yet share durable broker order IDs or the live coordinator's reservation ledger. There is no exhaustive rejected/uncertain real-order lifecycle claim. Halt/rejection flags and zero modeled volume suppress fills while exposure remains visible. Actual queue position and executable liquidity are unverified.
