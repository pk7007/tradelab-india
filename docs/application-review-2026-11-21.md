# Whole-application review

21 November 2026, Asia/Kolkata. Scope is the current local working tree of
TradeLab India, including existing uncommitted paper-session improvements.
This assessment covers the requested personal research and trading platform.
Scores are engineering judgments, with profitability and actual-market
performance unobserved. The earlier 9/10 review covered unattended paper-session
engineering. The whole-application rating is 6.8/10.

## Independent assessment

Each dimension contributes up to two points. The independent reviewer inspected
the current implementation and its boundaries, with the following deductions.

| Dimension | Points | Evidence and deductions |
| --- | --- | --- |
| Correctness | 1.6/2 | Strong deterministic sizing, fills and accounting checks. Strategy contracts vary across research tools, and news issuer mapping lacks a representative independent benchmark. |
| Integration | 1.1/2 | The primary paper path connects selection, entry checks, sizing and exits. Licensed syndication lacks an application/worker connection. Long-term data and the complete agent workflow graph remain partial. |
| Resilience | 1.4/2 | Worker ownership, expiry, failure isolation, SQLite snapshots and replay/restart checks exist. Sustained provider operation and deployed restore drills require evidence. |
| Verification | 1.3/2 | Broad offline Python and JavaScript tests and isolated HTTP recovery checks pass. Authenticated forward sessions and realistic market outcome validation remain pending. |
| Usability | 1.4/2 | A simplified Auto Trading screen exposes session state and evidence. Advanced workflows remain complex and historical documentation has conflicting descriptions. |
| Total | 6.8/10 | Full application engineering assessment. Profitability N/A. |

## Surfaces inspected

| Surface | Current evidence | Remaining acceptance |
| --- | --- | --- |
| Local app and authentication | Loopback-only bind, strict Host header, CSRF and same-origin checks, memory broker tokens, bounded requests and response security headers in app.py. | This is a personal local application. Public deployment and multi-user authorization require a separate design and verification. |
| Market data and history | market_data.py and market_contract.py support bounded acquisition, mapping, freshness and session checks. | Provider entitlement, source-backed calendar, current login, point-in-time universe and coverage need operational verification. |
| Automatic selection and paper execution | auto_selector.py, entry_review.py, paper.py and paper_worker.py connect deterministic selection and risk checks to a durable paper ledger. | Observe actual scheduled sessions, skips, partial fills, outages and end-of-day reconciliation. |
| Risk and broker orders | Cost-aware sizing, reservations and recovery tests exist. app.py sets LIVE_EXECUTION_READY=False and rejects live dispatch. | Shared broker cash/inventory authority, uncertain order recovery and protective exits require integrated broker-side acceptance before real-money use. |
| News and events | dashboard_news.py runs an independent collector with a 30-second due interval, freshness, retries and source status. | Real publisher delivery latency, issuer accuracy, corrections and incremental trading value require measurement. Poll interval alone cannot guarantee immediate delivery. |
| Licensed news | syndication.py has mock-transport revision, cursor and retraction tests. | Provisioned feed access, app integration, scheduler ownership and purge of every retained copy require verification. |
| Evaluation and research | Chronological validation, holdout tracking, benchmark comparison and cost sensitivity are implemented. | Independent market samples, realistic costs, frozen experiment criteria and evidence of an economic edge remain absent. |
| Long-term, earnings and disclosures | Dated import analysis exists in fundamental_research.py and trader_suite.py. | Comprehensive permitted filings, restatements, valuation/sector evidence and dedicated India disclosure coverage are incomplete. Long-term expansion is deferred. |
| Agents and review | Role registry, handlers, monitoring, entry checks and retrospective evidence services exist. | The full durable reviewed graph across all requested roles remains partial. A registered role count does not measure completed integrations. |
| Storage and operations | storage_ops.py verifies SQLite snapshots and restoration to new paths. Existing storage/recovery tests exercise these paths. | Cross-ledger snapshots are individually consistent. Operational multi-ledger recovery, scheduled backups, retention and failure notification need observed drills. |
| Alerts and frontend | Browser regressions cover calculations, stale research, controls, recovery and automatic session state. | Durable alert delivery outside the browser and representative whole-interface browser coverage remain limited. |

## Verification performed for this assessment

- Python discovery executed 363 tests. Four HTTP tests initially encountered
  Windows connection restrictions. Those four passed on an authorized retry.
  Across those runs all 363 passed.
- All seven JavaScript regression files passed. Several files print more than
  one success message. web/platform.js passed the Node syntax check.
- scripts/fixture_recovery.py passed using two isolated real local server
  processes after the same Windows restriction was lifted. It verified pause on
  restart, restored intent, gap rejection, duplicate suppression and exact ledger
  agreement. It made zero broker orders. Its final exposure was ten simulated
  shares, which the report correctly retained.
- The existing docs/intraday-session-example.json contains controlled browser
  evidence for qualifying and zero-trade sessions. This assessment relies on
  that previously generated browser evidence. It did not rerun Chromium.
- Source inspection covered API security/dispatch boundaries, collector startup,
  storage operations, frontend tests, CI and the capability/gap documentation.
- git diff --check passed. No authenticated broker acceptance, provider feed
  provisioning, production load test or profitability experiment was performed.

## Repairs made during this assessment

- Added the session interface regression and platform.js syntax check to the
  existing GitHub checks workflow. Both checks passed locally. Hosted CI has
  not run these local changes yet.
- Updated README to distinguish the current whole-application assessment from
  the narrower paper review, and to describe the current collector interval.

## Next acceptance tasks

1. Verify the scheduled audit outcome, reviewed calendar and Monday 23 November
   login. Keep market-dependent activation deferred until that date.
2. Observe the automatic paper run and independently reconstruct cash, fees,
   shares and selection or skip reasons from its journal. A valid no-trade day
   requires an actual completed session and durable evidence.
3. Freeze evaluation criteria and gather independent sessions against a simple
   benchmark with realistic costs, drawdown and uncertainty.
4. Provision the approved news endpoint privately, connect its lifecycle to the
   app and verify revisions, outages and complete purge behavior.
5. Complete required agent handoffs using working handlers and actual evidence.
   Keep exits independent of optional research availability.
6. Run backup/restore and service recovery drills against isolated copies before
   claiming unattended operational maturity.

The remaining missing integrations and unavailable market evidence justify the
current score. Repeating the same synthetic checks cannot establish nine out of
ten across the full platform. Review again when new operational evidence or
integrated capabilities are available.
