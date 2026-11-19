# Trading-system repair and operating report — 18 November 2026

## Decision and scope

Offline research and imported-candle paper operation are usable within the documented model. Continuous forward paper trading and live-money readiness are **not demonstrated**. This work does not turn the prototype into a profitable autonomous trader. The attached brief's full product scope remains unfinished; unresolved requirements are listed below rather than treated as passing.

ECC's installed guide, feature-development and build-fix instructions informed discovery, scoped implementation, tests and independent cross-review. Three development agents owned execution, reservations and UI files; the parent owned paper controls, data validation, shared strategy calculations, provenance and integration checks. No external ECC service was invoked. No credentials were read or changed, no broker order was sent, and no GitHub push was made. Unrelated college attendance files and `.gitignore` changes remain untouched.

Baseline: 99 Python tests passed. New tests were run against missing controls and permissive historical validation before fixes; they failed as expected. Cross-review reproduced two additional defects before correction: accepting altered LIMIT prices in manual evidence and late mock acknowledgements overwriting reconciled states.

## Architecture and actual boundaries

1. Browser mutations pass loopback Host, Origin/CSRF and request validation. Authentication stores broker credentials in server memory. OAuth state is single-use with a ten-minute limit; sessions expire after thirty minutes of inactivity and are bounded to 128.
2. Manual order reviews bind to the login. Dispatch is gated off. The tested journal prepares a durable correlated intent before submission and tracks acknowledgement separately from execution. Broker order/trade reads can reconcile matching evidence. Positions and funding ownership are not established by this operation.
3. The mock coordinator stores versions and intents in a different ledger. Its shared funding tables atomically reserve integer-paise cash, fees and sellable units across named books. Unknown/partial orders retain reservations. Filled terminal outcomes block further admission until an explicit mock funding snapshot is reconciled.
4. Paper accounts are independently funded simulations. They do not consume that shared ledger or broker funds. Imported candles drive persisted SMA signals and assumed next-open fills. Full journal reconstruction checks balances before processing.
5. Evaluation and paper share completed-close SMA and full-fill price/fee calculations. They still differ in sizing, windows, forced final liquidation and risk gates; their raw P&L is not directly comparable. Portal evaluations now persist report fingerprints and repeated holdout exposure. CLI results remain ephemeral.
6. No AI provider or tool-calling model is integrated. News/earnings imports are deterministic research inputs, not instructions. A Kite key is not an AI credential. Model-specific output schemas, prompt-injection evaluations and provider-failure tests remain required when a model is selected.

## Prioritized gap register

| ID | Severity / trigger | Change and acceptance evidence | Remaining boundary |
|---|---|---|---|
| R1 | Critical: lost acknowledgement then new review or restart | Durable manual intent persists before submission; unresolved same instrument/product blocks a repeat; restart and concurrency tests | Manual/mock engines still separate; no exactly-once claim |
| R2 | Critical: another order or modified limit matches a tag | Validate tag, order ID, immutable fields, monotone quantities, unique trades and applicable fill prices | Broker reads mocked; prior-day absence cannot resolve an intent |
| R3 | Critical: competing portfolios spend/sell the last available funds/shares | Transactional shared mock reservation ledger includes fees; competing connections tested | Not wired into paper books or live broker snapshots |
| R4 | Critical: late response overwrites partial/terminal state | Cross-Coordinator submission/reconciliation tests preserve identity and state; funding mismatch rechecked at submission | Multi-process scheduling leadership remains absent |
| R5 | High: entry pause accidentally suspends exits | Separate entry pause/resume/cancel and requested-close controls; browser verified shares remain until next candle and ledger matches after exit | No liquidity model, live exit scheduler, stops or actual broker cancellation |
| R6 | High: recent receipt hides stale/revised data | Existing timestamp checks retained; conflicting duplicate history and Boolean OHLCV now rejected | Exchange calendar, corporate actions, quote depth and authorized forward feed incomplete |
| R7 | High: credential flag mistaken for readiness | Server hard readiness gate, separate configured/connected/ready UI and visible manual recovery | Live remains unavailable; do not remove gate as a setup shortcut |
| R8 | High: provider errors disclose sensitive request details | Generic broker failures, bounded idle sessions, atomic login identity changes, generic database failure response | No penetration test, remote multi-user security or encrypted database |
| R9 | High: repeated cost/parameter changes treated as fresh holdout | Dataset and holdout fingerprints independent of costs; every portal result retained, including underperformance | Hash tracking cannot prove point-in-time provenance or prevent modified-series gaming |
| R10 | Medium: edited form or late preview replaces approved inputs | UI invalidation and overlapping response tests; broker evidence escaped | Full browser testing of authenticated orders unavailable |

## Operating and recovery runbook

### Local setup

Use the existing virtual environment and `python app.py`, bound to loopback. Configure credentials only in local `.env`, using `.env.example`; do not paste them into chat. Authenticate through Zerodha's login. Read-only account/data access can then be checked separately from execution readiness. This repair did not inspect current credentials or connect to a real account.

Private databases default to `%LOCALAPPDATA%/TradeLabIndia/`: `paper.sqlite`, `automation.sqlite`, `execution.sqlite`, and `research.sqlite`. Their optional `TRADELAB_*_DB` variables select alternate private locations. These files must stay out of Git. Stop the app before making a consistent backup of these files; do not restore one ledger while allowing another process to trade.

### Paper controls

- Start ingestion allows accepted batches; it does not connect a feed or clear an entry pause.
- Pause new entries cancels an unfilled BUY and preserves a pending SELL. Existing position management needs continuing accepted candles.
- Cancel pending entry removes a BUY only; a later strategy signal may create another unless entries are paused.
- Request simulated close requires running ingestion and open shares. It queues SELL and pauses new entries. Missing data leaves the shares and exit visibly pending.
- Pause all ingestion freezes both entry and exit processing. Stop ingestion also cancels the local pending intent. Neither closes shares.
- Restart pauses previously running accounts. Review ledger, pending intent and data continuity before explicit resume. Resume new entries is a separate choice.
- A ledger mismatch blocks processing. Investigate/rebuild from evidence; do not edit balances to make the check green.

### Uncertain broker outcome

Use the recovery view to inspect durable intent state. Reconcile reads broker orders/trades; it never retries a submission. A missing/ambiguous response remains UNKNOWN. The broker's daily order/trade lists cannot settle missing older records; obtain authoritative evidence through the broker and a separately reviewed recovery procedure. There is no force-release/reset endpoint. Check net positions, working orders and holdings directly at the broker if actual exposure needs attention. The application's live gate remains closed.

### Failures

Expired session: reconnect through the ordinary broker flow and re-review old requests. Storage failure: stop new processing, preserve database files, investigate disk/path permissions, and rerun reconciliation before resume. Unknown order: do not submit a replacement. Feed gap/revision: recover missing history or start a separately attributed revised experiment; never silently overwrite already processed evidence.

## External requirements checked

Official pages were inspected during this work; they are references, not account-specific approval:

- [Kite orders](https://kite.trade/docs/connect/v3/orders/): acknowledgement is not execution; tags support correlation; order/trade lists are daily. Application tags do not imply broker idempotency.
- [Kite authentication](https://kite.trade/docs/connect/v3/user/): the normal token exchange and server-side secret handling remain necessary.
- [Zerodha API FAQs](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs): confirm current order API/static-IP requirements directly for this account before any future live readiness review.
- [NSE timings and holidays](https://www.nseindia.com/resources/exchange-communication-holidays?article_id=432919950.0): session/holiday notices are segment-specific; this application still has weekday/time heuristics, not a validated calendar adapter.

No data redistribution entitlement or continuous-candle retention permission was verified. Public accessibility and a paid subscription do not certify either. Real-data storage remains explicitly controlled; no market dataset was published.

## Remaining implementation and external dependencies

Critical before real money: unify manual/automated execution behind authoritative broker-level funding and ownership; approved exact strategy and limits; persisted scheduling/leadership; independent order/trade/position reconciliation; protective and partial-exit recovery; tested cancellation/flatten workflows; current instrument/tick/product/margin and session validation; observed read-only broker integration followed by separately authorized supervised live validation.

Before useful strategy promotion: licensed point-in-time universe and corporate actions, realistic fees/taxes/liquidity, untouched out-of-sample protocol, identical sizing and liquidation across evaluation/paper, real forward observations and independently reviewed evidence. Dedicated long-term contributions/dividends/total-return accounting remains missing. Synthetic success is not promotion evidence.

AI remains disconnected pending a provider/model choice. It will require source-linked structured output, trusted symbol/evidence registries, bounded age checks, adversarial-input tests and a strict lack of execution authority. There is no current autonomous AI money-management claim.

The current blocker is broader than API keys. Engineering work above remains necessary even after credentials are linked.

## Verification

Use these commands from the repository root:

```powershell
python -m unittest discover -s tests -q
node tests/account.test.js
node tests/order-review.test.js
node tests/research-display.test.js
python scripts/fixture_recovery.py
```

The HTTP fixture uses two real temporary server processes, empty credentials and isolated databases. Local socket permissions required running it outside the tool sandbox. It recovered the pending signal after restart, rejected a gap, skipped two overlapping/five retransmitted candles, and produced one simulated fill with journal-matched cash ₹8,798.1994 and ten shares. No broker order occurred.

Browser checks used isolated port 8772 and empty credentials: readiness remained locked; repeated synthetic evaluation displayed previous holdout viewing; account creation and imports worked; entry pause retained running ingestion; a requested close displayed ten exposed shares and pending SELL until the next batch; the subsequent fill left zero shares and journal-matched cash ₹10,006.39 with two fills and ₹2.41 modeled fees. This is invented test data, not a return claim. The original 8765 process was not restarted.

Final verification on **19 November 2026**: **140 Python tests passed**; the three JavaScript regression scripts passed; Python compilation, JavaScript syntax checks and `git diff --check` passed. The final isolated HTTP recovery rerun passed after the funding submission recheck and research-database handle fix. A pattern-based scan of changed project files found no credential-like literals; this is not a comprehensive secret audit. Automated checks exercise offline behaviors, not all requested production scenarios or every responsive/browser state.

The last funding fix re-reads the active reservation and funding account inside the same write transaction that claims submission. A second process reporting a mismatch, missing reservation/account, insufficient persisted cash or another uncertain intent now blocks the mock submission. Process-local pause state is still a mock limitation; durable scheduling leadership must precede a live adapter.
