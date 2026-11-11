# TradeLab loss-path review | 11 November 2026

## Owner briefing

**Decision.** Continue isolated research and paper recovery testing. Live-money readiness remains unverified. The local baseline passed 91 Python tests. After the changes, 99 passed, as did the JavaScript account check, changed-script syntax checks and two-process HTTP recovery test. GitHub's master branch and local HEAD both pointed to `26609f8`. The durable paper engine, fixture adapter and this audit were working-tree changes. Data, tokens, acceptances and prices used in business-path tests were synthetic. GitHub and public documentation were consulted separately.

1. **A reviewed order could reach a different login.** The review recorded the order and time. A successful broker re-login could replace the session token within that review window. A mock submission using the second session succeeded. Preview now binds approval to the broker login and a changed login requires a new review. A missing acknowledgement ID now produces an uncertain outcome. [Handler](../app.py) · [Regressions](../tests/test_loss_paths.py)
2. **An unrelated broker ID could complete a partial order.** A mock timeout followed by one matched share and then an update for a different order completed the original two-share intent. The coordinator now preserves the known broker ID and filled quantity and faults the mismatched update. The matching final update resolves it. The manual route still lacks this durable coordinator. [Coordinator](../automation.py) · [Mock lifecycle test](../tests/test_automation.py)
3. **A green paper balance check could hide incorrect profits.** Adding ₹500 to stored realized P&L and marked equity passed the old check. Fill-journal reconstruction now also verifies cost basis, realized P&L, equity and the last bar against the stored data. Both import paths block further processing on drift. Restoration requires investigation. [Paper accounting](../paper.py) · [Failure injection](../tests/test_loss_paths.py)
4. **Two independent simulations can spend the same assumed capital.** Two accounts initialized with ₹10,000 each bought ₹9,600 each. This is valid for independent experiments. It would overallocate a single ₹10,000 broker balance by ₹9,200 if both were treated as funded mandates. Broker-wide cash/share reservations and external manual-trade reconciliation are outstanding. [PaperEngine.create and ingest](../paper.py)
5. **The sample strategy lagged before charging costs.** On the fixed daily holdout it lagged by 0.941 percentage points at zero friction and 1.240 points at the supplied friction. Better execution alone would not have reversed the observed ranking at those prices. Market liquidity, actual charges and forward performance are unknown. [Attribution command](../scripts/loss_audit.py)

## Three journeys through the code

**A. Lost acknowledgement, then an exit is due.** In the manual HTTP route, the user supplies exchange, symbol, quantity and product. The preview normalizes them, then placement consumes the confirmation before contacting the broker. A duplicate click on this confirmation yields one POST. Kite's order and trade records supply broker execution evidence. TradeLab's session memory cannot establish the outcome after a restart, or prevent a separately reviewed repeat. The mock coordinator has a different path: prepare persists an intent and checks the supplied cash and exposure snapshot, submit persists SUBMITTING before calling the adapter, and uncertain acceptance leads to UNKNOWN. In a fresh process an empty update cannot resolve that uncertainty. The audited mock progressed from UNKNOWN to one partial fill to two shares complete with a single submission. There is no verified broker-driven exit scheduler. Remain exposed until broker fills and net positions establish the exit. [Manual handler](../app.py) · [Coordinator](../automation.py) · [Mock tests](../tests/test_automation.py)

**B. Two portfolios and an external trade in the same stock.** The existing local books have independent configured capital, candle-derived prices and their own fills. The broker account screen reads holdings, net positions and orders, and its net-position calculation includes closed-position P&L. No durable allocation links those totals to intraday versus delivery ownership. The mock coordinator consumes a caller-provided mismatch flag. The manual route has no cross-book reservation check. Test cash reservations under contention, sellable shares after an external sale and reconciliation by account/exchange/instrument/product before promoting either mandate. [Paper ledger](../paper.py) · [Account display](../web/account.js) · [Coordinator](../automation.py)

**C. Evaluation appears promising, paper performance weakens.** The first validation window beat holding while losing money in absolute terms. The second held cash while the benchmark fell. On the final window the strategy lagged. Evaluation uses historical closes for decisions, next-open trades, whole shares from starting capital, and liquidation at each window's final open. Paper uses fixed units, exposure gates and open positions marked to the last close. Different sizing, liquidation and timestamps invalidate a direct P&L comparison. A matched paper-forward comparison still needs a common signal, fill, cash-flow, benchmark and cost contract plus authorized observations. [Evaluator](../evaluation.py) · [Recorded windows](evaluation-demo.json) · [Paper engine](../paper.py)

## Gap register

Confirmed means reproduced or directly observed in code as indicated. Tests rule out a failure only within their fixture scope.

| ID and workflow | Trigger, observed behavior and consequence | Evidence, confidence and disposition |
|---|---|---|
| L1 manual approval | Login switches before placement. Old review could submit against the new account. | High, mock reproduced. Fixed by login binding. Normal preview followed by token replacement gives 409 and zero broker calls. [Tests](../tests/test_loss_paths.py) |
| L2 manual acknowledgement | Success envelope lacks order ID. Old HTTP 200 claimed acceptance. | High, reproduced. Now returns uncertain outcome, consumes review and sends one POST across replay. Durable cross-review recovery still open. [Tests](../tests/test_loss_paths.py) |
| L3 mock partial fill | Another broker ID reports the remaining share. Old intent became COMPLETE. | High, reproduced. Now UNKNOWN, one share preserved, mismatched ID excluded. [Test](../tests/test_automation.py) |
| L4 paper P&L | Cash and quantity match while realized profit, basis or last mark drifts. Old verification could pass. | High, reproduced. Independent rebuild and ingestion block tested. Audit history itself lacks tamper resistance. [Test](../tests/test_loss_paths.py) |
| L5 instrument | Raw candles explicitly tagged OTHER were accepted for the account symbol. Wrong prices triggered a fill. | High, reproduced. Explicit conflicting symbols/exchanges and unmapped token/ISIN metadata rejected. Untagged imports still rely on the operator's attribution. Product/lot mapping across brokers unverified. [Test](../tests/test_loss_paths.py) |
| L6 alerts | An old trade arrives now. The previous alert predicate checked receipt age alone. | High from code. Alerts now require recent exchange, trade and receipt timestamps. Missing or future times fail the check. Instruments lacking a trade timestamp suppress these alerts. Real streaming and browser audio delivery unverified. [Stream](../market_data.py) · [Test](../tests/test_loss_paths.py) |
| L7 liquidity and exits | Paper assumes full fills at modeled next open. Stops, circuits, venue closure, partial exits and expiry can strand real exposure. Weekday filtering alone does not implement an exchange calendar. | Confirmed model limitation. Stop retains shares in tests. Real exit recovery and alerts require a permitted feed and supervised tests. [Paper tests](../tests/test_paper.py) |
| L8 shared capital | Independent accounts reserve ₹19,200 combined in the example above. External sale may change actual available inventory. | High for fixture, real attribution unverified. Implement one transactional broker-level reservation ledger and reconcile external activity. [Engine](../paper.py) |
| L9 data timing and crashes | Duplicates, revised prices, incomplete bars, gaps, overlapping recovery and a database failure after inserting a fill. | Tested paths reject revisions/gaps, skip duplicates and roll back partially applied writes. Restart then produces one fill. Real provider outage, independent market marks and receipt-to-decision latency unverified. [Fixture recovery](paper-feed-recovery.md) · [Fault tests](../tests/test_loss_paths.py) |
| L10 long-term wealth | Contributions, dividends, splits, delistings and rebalances could distort price-only return or ownership. Historical sector membership and filing vintages unavailable. | Confirmed missing capability. Cash-flow-matched total-return benchmarking and corporate-action inventory reconciliation are required. Long-term stock selection remains unsupported. [Research contract](../research.py) |
| L11 risk and operations | Daily loss threshold blocks buys, leaves exits eligible and resets on a new imported day. Actual price gaps can exceed the threshold. Legacy approval UI, coordinator and paper books implement different limits. | Source inspection plus boundary tests. Unified two-book limits, session-aware liquidation, production database failure handling, external notifications and manual-order supervision unverified. [Risk tests](../tests/test_trading_audit.py) |
| L12 research selection | Choosing symbols after seeing winners, tuning repeatedly on a holdout, or taking headlines before availability can inflate apparent performance. | Earlier-window invariance, next-open timing and availability cutoffs tested. No point-in-time universe or enforced independent promotion registry. AI outage or malicious research input has no validated autonomous execution workflow. [Research tests](../tests/test_evaluation.py) · [News tests](../tests/test_trading_audit.py) |

## Performance and skipped decisions

Fixed synthetic 300-bar daily fixture, final 60 bars. Two completed trades at the base settings. Each row reruns both portfolios with the indicated friction. Sizing can change between runs. These are scenario differences rather than additive estimates of independent market costs.

| Per-side fee / slippage (bps) | SMA return | Hold return | Difference (percentage points) |
|---|---:|---:|---:|
| 0 / 0, next-open gross | 1.686% | 2.627% | −0.941 |
| 0 / 5 | 1.486% | 2.523% | −1.037 |
| 10 / 5 | 1.079% | 2.319% | −1.240 |
| 20 / 10 | 0.475% | 2.013% | −1.538 |

Next-open timing is present in all four rows. No same-close windfall is counted. At base friction the strategy's maximum bar-close drawdown was 4.657%, reported exposure 57.63% and fees ₹407.70 on ₹100,000 initial cash. The matched holding benchmark had 5.746% drawdown. Queue position, effective spread, market impact, fill rejection, exact historical taxes, worst real session and deployment delays are unmeasured. A price-only daily fixture cannot estimate real intraday or long-term returns. [Report](evaluation-demo.json)

The separate five-minute shadow study fixes a five-bar horizon and logs all rejected or loss-blocked BUY signals, their original reason, and hypothetical P&L from the next open through the fifth close after modeled costs. A deliberately tiny exposure limit rejected all entries on a 75-bar synthetic tape. Four outcomes were positive, 20 negative and zero incomplete. Actual paper equity stayed ₹10,000. Signals overlap and the hypothetical trades compete for cash, so summing them as attainable missed profit would mislead. The demo is a diagnostic fixture. No promotion threshold, investment decision or validated edge follows from it. [Script](../scripts/loss_audit.py)

## Competitor task comparison

OpenAlgo source inspection used revision 68f91cf. Its Zerodha adapter correlates an uncertain POST against the broker order book using a tag. TradeLab's manual handler consumes the review and tells the operator to check. This is a material recovery gap for an operator facing a timeout. Implement durable correlation and an unresolved-order screen before live automation. Its sandbox checks internally inconsistent quotes and conditionally claims fills. TradeLab's replay has atomic duplicate-bar handling and a reproducible restart demonstration. There was no matched runtime or speed benchmark. [OpenAlgo adapter](https://github.com/marketcalls/openalgo/blob/68f91cf58da2dddba2502eaebd034479b1cd4452/broker/zerodha/api/order_api.py) · [Sandbox](https://github.com/marketcalls/openalgo/blob/68f91cf58da2dddba2502eaebd034479b1cd4452/sandbox/execution_engine.py)

QuantConnect LEAN's equity fill model has order-specific stale-data handling and best-effort pricing. Its official documentation describes configurable fill models. TradeLab's full next-open fills are simpler to reproduce but offer little evidence about execution quality on a thin instrument. Add matched liquidity/latency sensitivity when permitted quote/trade data is available. A US-equity model would require separate validation for NSE. Other comparisons, including broker-wide reservations, operator diagnosis time and relative profitability, remain unmeasured. [Pinned LEAN source](https://github.com/QuantConnect/Lean/blob/093766e4319ef24c75835c9449e33ebb99ecf6f4/Common/Orders/Fills/EquityFillModel.cs) · [Official fill-model documentation](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/trade-fills/key-concepts)

## Engineering scores

Reviewer judgments on a 0–10 scale. Five means usable with material boundaries under fixtures. Nine requires passing the defined operating scope and resolving its critical loss paths. The two numeric scores cover local prototype functionality only. Real-data performance and production properties remain unverified.

| Dimension and weight | Historical research | Paper operation | Live money |
|---|---:|---:|---|
| Accounting and ownership 25% ([accounting tests](../tests/test_evaluation.py)) | 6, matched single-stock valuation | 6, rebuilt single-book balances | Unverified across books |
| Risk and execution 25% ([execution tests](../tests/test_loss_paths.py)) | 5, next open and cost controls | 5, atomic replay and gated buys | 2, reviewed handler tested with mocks |
| Data integrity 20% ([feed tests](../tests/test_fixture_feed.py)) | 4, file checks and fingerprints | 4, fixture times and gap checks | Unverified on authorized forward feed |
| Research and costs 15% ([attribution](../scripts/loss_audit.py)) | 5, holdout and matched benchmark | 3, fixed-unit friction | Unverified on broker executions |
| Recovery 10% ([restart](../scripts/fixture_recovery.py)) | 6, repeatable offline result | 7, actual process restart with fixture | 2, durable reconciliation only in mock path |
| Usability 5% ([operator guide](paper-feed-recovery.md)) | 6, reproducible run commands | 6, visible ledger diagnostics | 4, manual review and uncertainty messages |
| Weighted assessment | **5.20/10** | **5.00/10** | **Live readiness not demonstrated** |

Keep all six dimensions in the denominator. For live scope, 60% of the weight lacks the necessary evidence. The two-decimal totals are arithmetic on subjective scores. The shortest paths to stronger evidence are a point-in-time, costed dataset for research, a permitted forward session plus shared reservations for paper, and broker-matched unknown-order/partial-exit recovery for live assessment.

## Reproduce locally

Run these from the repository root with the project environment. The recovery command needs loopback sockets. Each fixture uses an isolated temporary database.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv\Scripts\python.exe scripts/fixture_recovery.py
.\.venv\Scripts\python.exe scripts/loss_audit.py
node tests/account.test.js
```

No real broker call, private market dataset, real trading credential or money was used in the audit scenarios. The scope excludes a live integration test, exhaustive security assessment, independently witnessed broker reconciliation and complete historical corporate-action validation.
