# Current-state audit against the project history — 23 November 2026

Scope: checkout of `master` at 9b6d369 (branch `claude/awesome-johnson-pp0xfq`, no local
changes at the start). The audit compares the A–Z project history (reconstructed from earlier
conversations) with source, tests and GitHub state observed today. It is a code and documentation
audit. No broker session, market-hours run, live feed or paid service was used.

## Status vocabulary

| Status | Meaning |
|---|---|
| COMPLETED | Implemented in source and exercised by a passing automated check. A bracketed qualifier such as "(offline)" or "(paper)" states the only environment in which that was shown; anything beyond it is UNVERIFIED. |
| PARTIAL | Implemented for a bounded case; a named gap remains. |
| FAILED | Implemented behaviour does not meet the requirement the history set for it. |
| NOT IMPLEMENTED | No source found (searched by name and concept). |
| UNVERIFIED | Needs live data, broker access, sustained observation or an external review. |

## Evidence collected today

| Check | Result |
|---|---|
| `python -m pytest -q` | 393 passed, 547 subtests passed, 12.7 s |
| Nine `tests/*.test.js` files, each run with `node` | All exit 0. CI runs them as individual `node tests/<file>` steps plus `unittest discover` and `scripts/fixture_recovery.py`. |
| Live-order guards in `app.py` | `LIVE_EXECUTION_READY = False` is hardcoded (`app.py:60`). `place_order` also needs `TRADELAB_ENABLE_LIVE_ORDERS=true`, a typed confirmation, an unexpired review and an unseen confirmation id. |
| GitHub | Open draft PR #1 (`feat/news-agent-codex-subagents`, head f31fe2d, base abc28e7; read through the GitHub connector today) and open draft PR #2 (`docs/portfolio-readiness-2026-11-23`, head c0ecee8, base 9b6d369). Neither is merged. `origin/master` has no `.codex` files. |

Passing tests support code claims only. They are not evidence of market performance, live
operation or compliance.

## Corrections to the historical record

1. **Agent registry.** The history says about 108 responsibilities and three implemented
   handlers. The current `agent_catalog.py` defines 32 evidence domains × 16 generic
   responsibilities = 512 role contracts, and all 16 responsibilities are marked implemented
   through shared handlers in `agent_handlers.py`. `docs/agent-integration-requirements.md`
   already records 512. These are bounded evidence-processing tasks (schema, freshness, duplicate
   and descriptive checks). They are not 512 independent skills, and no model is connected.
2. **Test count.** The 238 tests cited on 22 November have grown to 393 passing today.
3. **Local branches.** `master` and this working branch are the only local branches. PR #1 and
   PR #2 branches exist only on the remote and are unmerged.
4. **The 31/100, 7.2/10, 9/10 and 8.5/10 scores** are historical assessments with different
   scopes. This audit does not re-score them.

## Classification of previously identified gaps

### Execution, risk and safety (P0)

| Item | Status | Evidence | Gap / next verification |
|---|---|---|---|
| Live execution isolated | COMPLETED (code) | `app.py:60, 833–840`; README and `docs/feature-status.md` agree | Live path remains untested against a real broker, by design. |
| `ResearchRiskGate.kill()` closes exposure | **FAILED** | `research.py:145–149` sets `killed`, returns cancel intents and `positionsClosed: False`. Only `research.py` and tests use the class. | The history flagged this on 19–20 November and it is unchanged. Either wire a flatten/exit path or leave the class explicitly labelled research-only. |
| Unified OMS | PARTIAL | `execution_journal.py` records intent, order and trade correlation and keeps contradictory identity UNKNOWN. `automation.py` and `desk_coordinator.py` have mock reservations. | Mock-only. `docs/feature-status.md` states live dispatch is locked and `positionsReconciled` is false. |
| Broker reconciliation | PARTIAL | `broker_snapshot.py` is read-only and non-atomic. Paper ledger reconciliation exists and is tested. | No authoritative live order or position reconciliation. UNVERIFIED without a broker session. |
| Order idempotency | PARTIAL | Idempotency keys in `agent_service.py:107–123`. Deterministic paper account ids in `auto_selector.py:473`. Confirmation-id dedupe in `app.py`. | Not shown for live broker acknowledgement loss. |
| Broker-side stops and targets | NOT IMPLEMENTED | Stops are modelled on candles in paper only (`intraday_contract.py`, `paper_worker.py`). No GTT or broker stop code. | Needed before any live use. |
| Independent square-off scheduler | PARTIAL | Square-off is evaluated by the paper worker and `auto_selector.py`, both clock-driven, and `intraday_contract.py:80` adds a recovery exit. | The worker still depends on observed completed candles. Behaviour in a real session is UNVERIFIED. |
| Crash recovery (paper) | COMPLETED (paper, offline) | `scripts/fixture_recovery.py`, `tests/test_worker_loss_regressions.py`, `tests/test_supervised_service.py` | Fixture replay only. Live lifecycle recovery is UNVERIFIED. |
| Supervision and alerting | PARTIAL | `worker_runtime.py`, `operational_alerts.py`, `scripts/watch_service.py` | Local process only. No evidence of an external supervisor or escalation channel. |
| Cost and liquidity realism | PARTIAL | Costs, volume-participation limits and next-open fills in `intraday_contract.py` and `evaluation.py`. | No spread or queue model. Real-fill calibration UNVERIFIED. |

### Data

| Item | Status | Evidence | Gap |
|---|---|---|---|
| Historical candles and import | COMPLETED (offline) | `market_data.py`, `market_contract.py`, tests | |
| KiteTicker streaming | PARTIAL | `market_data.py:210–221`, `reconnect=True`, `reconnect_max_tries=5` | No sustained-run or outage evidence. UNVERIFIED. |
| Stale and missing candle detection | PARTIAL | `market_contract.py` freshness and session manifest; `scripts/data_quality_audit.py` | No production calendar importer (`docs/feature-status.md`). |
| Corporate-action adjustment | UNVERIFIED | Repeated limitation text in `research.py`, `strategy_lab.py`, `scripts/*` | No verified adjusted-price source. |
| Point-in-time news availability | PARTIAL | `news_agent.py`, `announcements.py`, `nse_filings.py`, `integrated_news.py`: publisher delivery time sets availability | Historical late-discovery and retraction coverage needs fixtures. |

### Strategies and research

| Item | Status | Evidence | Gap |
|---|---|---|---|
| SMA(5/20) baseline | COMPLETED (offline) | `evaluation.py`, `tests/test_evaluation.py` | Not evidence of profit. |
| Opening-range, flag and RSI<35 heuristics | PARTIAL | `trader_suite.py:77–99` (descriptive, unvalidated) | |
| EMA 20/50 + ADX, VWAP, Supertrend/ATR, Bollinger | NOT IMPLEMENTED | No source matches for these names | |
| Market-regime classifier | NOT IMPLEMENTED | `agent_handlers.py` only summarises caller-supplied regime labels | |
| Strategy versioning and experiments | COMPLETED (offline) | `strategy_lab.py`, `experiment_registry.py`, tests | Auto-promotion applies to PAPER only. |
| Walk-forward validation | NOT IMPLEMENTED | `validation_lab.py:109` says no walk-forward claim | Chronological split and holdout exist (`research.py`). |
| Forward paper evidence | UNVERIFIED | Needs observed sessions | |
| Monte Carlo (10,000 paths) | PARTIAL | IID resampling per `docs/feature-gap-matrix.md` | Not a validated risk model. |
| F&O engine | NOT IMPLEMENTED | | |

### News and AI

| Item | Status | Evidence | Gap |
|---|---|---|---|
| News ingestion (NSE, ET, Google RSS, NSE filings) | COMPLETED (offline mock) / UNVERIFIED (live) | `news_agent.py`, `nse_filings.py`, tests | Live feed health unobserved today. |
| Exact NSE symbol mapping | PARTIAL | `announcements.py` exact loaded-name map | Ambiguity and alias coverage limited. |
| LLM sentiment or reasoning | NOT IMPLEMENTED | No OpenAI, Anthropic or other model client in any `.py` file | Deterministic keyword classification only. |
| Importance scoring and source credibility | PARTIAL | `news_agent.py` categories | |
| News → order | NOT IMPLEMENTED (intentional) | Research context only | |
| 16 Codex subagent configs (PR #1) | UNVERIFIED | Present only on the unmerged PR branch | Not run. Not merged. |

### Multi-agent platform

| Item | Status | Evidence | Gap |
|---|---|---|---|
| Role registry | COMPLETED (as registry) | 512 contracts | Registry presence is not capability. |
| Generic evidence handlers | PARTIAL | `agent_handlers.py` | Descriptive checks, no domain-specific models. |
| Debate, bull/bear, trader and portfolio-manager agents | NOT IMPLEMENTED | No such handlers | |
| Review gating before entry | PARTIAL | Session evidence observer is retrospective (`docs/agent-integration-requirements.md`) | Does not block entries before the fact. |

### Repository and documentation

| Item | Status | Gap |
|---|---|---|
| CI | PARTIAL | Workflow defines compile, JS, unit and fixture-recovery steps and the same steps pass locally. The remote run result was not inspected, so it is UNVERIFIED. |
| README and docs honesty | COMPLETED | The README keeps unproven claims out. |
| Portfolio PR #2 | PARTIAL | Open draft, unmerged, `master` unchanged. |
| LICENSE file | NOT IMPLEMENTED | Owner decision. |

## Material risks to track

1. `ResearchRiskGate.kill()` does not neutralise exposure. It is currently research-only. This
   must be fixed or clearly fenced before any path could reach live dispatch.
2. The 512-role registry could be read as 512 working agents. Documentation already warns
   against that. Dashboard wording should keep the warning.
3. Forward performance, live data resilience and compliance remain unobserved. The system must
   not be described as profitable or live-ready.

## Recommended next verification

1. Decide whether to flatten-on-kill or relabel `ResearchRiskGate` (small, testable).
2. Merge or close PR #1 and PR #2 after owner review.
3. Observe sessions with the paper worker during market hours. `AGENTS.md` defers
   market-dependent activation until Monday, 23 November 2026, which is the date of this audit.
   No market-dependent activation, broker login or worker start was performed here; starting
   one needs the owner's interactive Zerodha login and decision.
4. Add a point-in-time late-publication fixture for news.
5. Implement one additional strategy (for example EMA/ADX) only with a numerical fixture and a
   consuming strategy contract.

## Limitations of this audit

Classification relied on name searches and targeted reading, not a line-by-line review of every
module. Statements marked UNVERIFIED need live access that this session did not have.

## Review

An independent reviewer spot-checked 14 claims against source and scored the first draft 9/10 with
no critical or high findings. Its medium and low findings (deferral wording, status qualifiers,
CI status) are fixed in this version. The reviewer did not recheck the edits.
