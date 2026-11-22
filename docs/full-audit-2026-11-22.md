# TradeLab India full application audit

22 November 2026, Asia/Kolkata. Audited the current local working tree, including
uncommitted integration, paper-session and UI improvements. Independent whole
application engineering assessment is **7.2/10**, increased from the dated 6.8/10
review. Actual-market performance and profitability are **unrated**.

## Scoring method

The whole-app score uses five dimensions worth two points each. The area scores
below assess each named capability within its stated scope. They are judgments
supported by the evidence listed, not measured availability or expected returns.
The whole score is the sum of the five dimensions, not an average of area scores.

| Dimension | Points | Main deduction |
| --- | --- | --- |
| Correctness | 1.6/2 | Modeled execution and uncalibrated research interpretation still need observed acceptance. |
| Integration | 1.4/2 | News handoffs now connect, while the full agent graph, long-term inputs and broker execution remain incomplete. |
| Resilience | 1.4/2 | Recovery controls pass isolated tests. Sustained provider operation and complete operational restore drills remain unverified. |
| Verification | 1.3/2 | Strong offline coverage, with no accepted actual-market strategy sample or deployed reliability measurement. |
| Usability | 1.5/2 | Home and news are clearer. Advanced/import screens remain technical. |
| Total | **7.2/10** | Whole requested application scope. |

## Capability ratings

| Capability | Rating /10 | Evidence and remaining gap |
| --- | ---: | --- |
| Automatic paper workflow | 9 | Real browser and scheduler-loop fixtures exercise qualifying and no-trade sessions, review gates and reconciliation. Market-hours acceptance remains pending. |
| Paper risk controls | 8 | Cost-aware whole-share sizing, cash/exposure checks, modeled protection, loss controls, expiry and ownership tests. Gap losses and unavailable fills remain possible within the model. |
| Data acquisition and validation | 7 | Kite adapters, mapping, completed bars, gaps, duplicates and freshness checks. Comprehensive point-in-time coverage, corporate-action handling and actual provider operations need verification. |
| Full-platform integration | 7 | Shared news service reaches UI, research, workers and descriptive review. Required broader workflow handoffs remain partial. |
| News ingestion and context | 6.5 | RSS polling, dated context, exact mapping, retries and licensed-feed lifecycle tests. Licensed service is disabled, publisher delivery unverified and sentiment/trading impact unvalidated. |
| Strategy evaluation tooling | 7 | Chronological validation, holdout protections, benchmarks, cost sensitivity and shared signal tests. Independent market samples and an economic edge are absent. |
| Technical research | 6.5 | Deterministic scanners and imported setup tools exist. Automatic selection uses a quote screen and at most twenty candle histories under a fixed SMA rule. |
| Long-term research | 4.5 | Dated imported fundamentals and valuation evidence can be checked. Comprehensive permitted filings, sector coverage and production feeds remain deferred. |
| AI self-improvement foundation | 4 | Versioned hypotheses, bounded candidates, holdouts, scenario tests and rollback exist. Automatic evidence-backed proposals, quote-based forward validation and the continuing improvement loop remain incomplete. |
| Agent workflow integration | 6.5 | Registered handlers, four consumers, monitoring, entry reviews and descriptive provenance exist. All-stage durable reviewed dependencies and demonstrated outcomes remain partial. |
| Storage and recovery | 8 | SQLite integrity, checksummed snapshots, isolated restores, retained protection and journal reconstruction pass. Operational multi-ledger recovery and backup coverage need further drills. |
| Local application security | 8 | Loopback restriction, Host/CSRF checks, bounded inputs, in-memory credentials, redacted failures and live dispatch lock. Public/multi-user deployment and comprehensive penetration testing are outside verified scope. |
| Scheduling maturity | 6.5 | Active local supervisor, reminder and closing review schedules have matching build pins and bounded calendar scope. Successful scheduled market operation and durable external alerts remain unobserved. |
| Whole-interface usability | 7.5 | Connection state, simplified news times, disclosures and status checks improve home. Advanced forms, JSON workflows, mobile/assistive-technology acceptance remain incomplete. |
| Offline verification | 8.5 | Broad Python/JavaScript regressions, actual HTTP fixtures, Chromium replay and process recovery checks pass. Production and market-dependent outcomes remain outside these tests. |
| Real-money execution readiness | 2 | Server dispatch remains explicitly locked. Shared broker funding/inventory, uncertain-order recovery and protective-exit reconciliation require acceptance before release. |
| Actual profitability | N/A | No independently accepted actual-market performance evidence. |

## Current runtime observations

Read-only local API observations were taken during this audit. No broker data
request, order, trading activation, provider entitlement change or account edit
was performed.

- Main paper selection reported disarmed, processing disabled and zero accounts
  with outstanding exposure or pending intent.
- The running paper build matched both supervisor pins at
  97ad1507e602c7c9ef5a19c994f66bf9ba308ec36ffbdee1181497256f177145.
- All six ledgers in the Operations health list returned SQLite integrity ok.
  This check covers the configured Operations list, not every private file or
  downloaded market-data archive.
- The most recent backup metadata was complete and dated 20 November. Its seven
  recorded databases differ from the current six-ledger Operations list. This
  audit did not certify that older backup as a complete current-system restore.
- NSE, ET and Google cached source health reported fetched and fresh at the
  observation time. Moneycontrol reported disabled. This is one source-health
  snapshot, not sustained delivery or publisher-accuracy evidence.
- The current registry reported 512 roles, 504 enabled and four live consumer
  threads. Its queue contained 283 desk-reviewed monitoring tasks. Its accepted
  canonical-role demonstration counter was zero. Desk service reviews and human
  certification have different acceptance definitions.
- The agent database retains 612 agent rows, including historical/compatibility
  records. That table count does not represent 612 concurrent agents. The current
  dependency table had zero rows. Dedicated entry-review and session-evidence
  paths are separate from that generic task graph.
- The experiment and strategy-lab ledgers contained no registered experiments,
  hypotheses, evaluations or promotions at observation time. Existing paper
  receipts alone do not establish a validated strategy-improvement sample.

## Findings and repair

No new critical or high-severity software defect was confirmed in this bounded
source review. Release blockers below remain material acceptance gaps.

One P2 reporting defect was confirmed in StrategyLab.status. It set
automaticPromotionReady from the presence of a paper engine, while current
candle workers cannot produce the executable quote evidence required by
forward_evidence. The local fix reports paperEngineConnected separately, keeps
automaticPromotionReady false and supplies the concrete blocker. A regression
checks connected and disconnected engines. All eleven strategy-lab tests pass.
The repair changes readiness reporting only. The running process loads it after
its next restart, which was not performed during the user's connected session.

## Fresh verification

| Check | Result |
| --- | --- |
| Complete Python discovery | 381 tests executed in 78.452 seconds. Five HTTP tests encountered Windows connection restrictions. |
| Authorized HTTP retry | All five passed against isolated local servers. |
| New readiness regression and strategy suite | Eleven tests passed after the reporting repair, including the additional regression. Across discovery and targeted checks, 382 distinct Python tests passed. |
| JavaScript regressions | All eight test files passed. |
| Browser scripts | Every web JavaScript file passed Node syntax checking. |
| Real Chromium replay | Qualifying and no-trade paths passed at 390 by 844, each with one Start click, no additional trading mutations, zero page errors and zero broker orders. |
| Independent oracle | Qualifying fixture cash 10435.1616328, fees 20.2921672 and zero shares. No-trade fixture cash 10000, zero fees and zero shares. Both reconciled. |
| Two-process recovery fixture | Restored paused intent, rejected a gap, suppressed duplicates and reconstructed its ledger. Ten simulated shares correctly remained visible. Zero broker orders. |
| Storage regression | Isolated restore retains a partial exit and protection, reconciles, and leaves the source ledger intact. |
| Dependency consistency | Application environment pip check passed. Installed Kite SDK matches requirements at 5.2.2. This is dependency consistency, not a vulnerability scan. |
| Version control checks | Whitespace check passed. Existing application work remains uncommitted locally. |

Fresh browser evidence is in intraday-session-example.json. The original
qualification scenario intentionally uses generated prices. The reported gain
is a controlled fixture result.

## Graphify contribution and limits

The installed local graph was queried first to locate component relationships.
Source, callers and tests then supplied the correctness evidence. After the
readiness repair the incremental graph contains 1477 nodes, 4406 edges and 63
communities. This was a code-only run with no semantic documentation processing.
CSS remains unsupported. Inferred edges, unresolved dynamic Python calls and
community cohesion are navigation evidence, not automatic bug verdicts.

## Next steps in priority order

1. Complete the first deferred market-hours paper session on 23 November with
   user login, source/calendar checks and the scheduled supervisor. Reconstruct
   selection or skip reasons, fills, fees, cash, protection and final exposure.
2. Freeze the research protocol and collect independent sessions with costs,
   benchmarks and uncertainty before changing or promoting a strategy.
3. Provision and verify the actual licensed news source, correction/retraction
   lifecycle and all retained copies. Connected code alone cannot prove access.
4. Complete required durable agent handoffs using actual evidence. Preserve
   deterministic exits during optional research outages.
5. Implement executable quote paper observations and reconciled equity marks
   before candidate forward acceptance or unattended improvement can advance.
6. Verify current backup coverage and run an isolated complete-system restore,
   then test process/feed failure alerts beyond an open browser.
7. Simplify advanced navigation and setup forms, and complete mobile and
   assistive-technology testing. Long-term expansion follows intraday acceptance.
8. Integrate and accept broker funding, inventory, order uncertainty and
   protection before any separately authorized real-money activation.

## Review boundary

One independent reviewer inspected current source and relevant callers, repeated
focused tests and assessed the five-part rubric. This audit covers the named
entry points and regressions. It does not certify every source line, historical
backup, third-party vulnerability, broker state, exchange calendar or actual
market outcome. Source and test coverage support the current engineering score.
They cannot establish profit probability or a nine-out-of-ten whole platform.
