# Agent integration and continuous review requirements

Recorded from the user's request on 20 November 2026.

## Requested outcome

Attach relevant agents to all stages of automatic market research and the
trading workflow. Each meaningful task produces evidence for a reviewer before
downstream use. Target nine out of ten engineering quality through review,
repair and re-verification. Preserve the distinction between tested software
quality and demonstrated economic results.

## Required handoffs

| Stage | Responsible role families | Review requirement |
|---|---|---|
| Universe and market research | instrument-reference, exchange-calendar, historical-candles, quote-observations | Identity, session, source, freshness and coverage |
| Issuer and event research | news-ingestion, event-entity-mapping, corporate-actions, earnings-disclosures | Availability, issuer ambiguity, corrections and attribution |
| Long-term research | fundamental-statements, financial-ratios, valuation-assumptions, governance-evidence, sector-classification | Dated filings, period/unit consistency and stated assumptions |
| Ranking and strategy | technical-indicators, momentum-relative-strength, market-regimes, benchmark-data | Reproducible rules, completed observations and missing evidence |
| Risk and allocation | liquidity-spreads, transaction-costs, position-sizing, trade-risk, portfolio-exposure | Shared funds, remaining loss allowance, costs and uncertainty |
| Paper execution and recovery | paper-execution, order-position-reconciliation, recovery-persistence | Single ownership, exact-once processing, visible exposure and ledger agreement |
| Evaluation and improvement | backtest-execution, statistical-validation, benchmark-evaluation, performance-attribution, strategy-versioning | Frozen experiment, independent samples and attributed results |
| Operations and reporting | operations-security, application-reporting | Actionable failures, task lineage, review backlog and user-visible state |

## Runtime acceptance still to implement

- A durable workflow graph connects actual task outputs to downstream inputs.
- Each record carries source, observed time, first availability and revision.
- A separate reviewer verifies each handoff using appropriate domain checks.
- Failed reviews block dependent tasks. Repairs create traceable new versions.
- Research/review failures block affected new entries while existing deterministic
  risk controls, protective exits, exposure reporting and reconciliation continue.
  Optional research or review availability must not gate required exit processing.
- Repeated defects trigger probation or quarantine with retained history.
- Passing software checks leaves economic performance and market acceptance
  explicitly unverified until independent evidence exists.
- Strategies and risk changes follow existing approval controls.
- The dashboard shows responsible role, evidence, reviewer, findings, score and
  the next action for each stage.
- Review execution is bounded, idempotent and recoverable after restart.

## Current implementation

The registry contains 512 evidence-processing role contracts. Four local task
workers run monitoring tasks. The desk coordinator connects source health and
ledger checks. The automatic selector connects quote screening, bounded candle
ranking and a paper account using deterministic logic. The session evidence
observer now runs registered analysis, independent descriptive review and feature
handlers over available ledger facts, with persistent versions and bounded
retries. The primary screen shows actual role execution. These retrospective
checks do not yet gate every trading handoff before entry. See
[intraday automation](intraday-automation.md) for the implemented scope and limits.

### Phase A subset (lineage store and entry gate)

`lineage_store.py` persists each entry handoff task durably (source, source version, observed and
available times, input hash, parents, revision, state). Records are append-only; a changed outcome for the
same input becomes a new revision and the old one is marked superseded. Review defects are counted per
account and domain; repeated defects quarantine the domain until a clean probation, with history kept.
`entry_gate.py` blocks NEW paper entries only, when required evidence failed review, is missing, was
available after the decision time, has a lineage gap, or is quarantined. Exits, square-off, exposure
reporting and reconciliation never call it. A lineage-store failure blocks the new entry and is logged.

Knowingly out of scope for this subset: only the five existing entry stages are covered
(instrument-reference, historical-candles, technical-indicators, position-sizing, trade-risk). Market
research, issuer/event mapping, long-term research, reconciliation, reporting and improvement roles are not
yet recorded in the lineage. There is no periodic review, no dashboard stage view and no retention policy
for the lineage table. Square-off is covered only indirectly: the tests prove a stop exit and reconciliation
run when the lineage store fails; a square-off-specific test is an accepted gap and the next useful check. These remain requirements above.

AGENTS.md establishes the Codex development review workflow for subsequent work
in this repository. It is read by coding agents that support project instructions.
Runtime continuous review requires application implementation and operational
verification in addition to these instructions.
One reviewer reports to the lead agent. Rechecks reuse that reviewer, with no
recursive delegation of review subtasks.

## Autorun execution prompt

Execute the current authorized TradeLab task end to end. Make routine reversible
implementation decisions using the request, saved settings and repository
conventions. Inspect, implement, verify and assign one independent review
subagent. Repair confirmed issues and reuse the reviewer for rechecks toward
the nine-out-of-ten engineering target. Recover from failures and continue useful
independent work when a prerequisite is missing. Avoid routine confirmation
requests and offers to continue. Stop for a required approval, an unresolved
material decision or a concrete blocker, and identify the smallest user action.
Honor existing risk settings, provider permissions, live-market deferrals,
credential handling and tool approval requirements. Include evidence and actual
limitations in the final result. A desired score never justifies invented
verification or guaranteed performance.

## Reviewer assignment prompt

Review this TradeLab task independently against the user's request and the
applicable project instructions. Inspect the delivered changes and their normal
entry points. Identify incorrect behavior, integration gaps, missing evidence,
recovery problems and misleading user claims. For a master prompt or plan,
verify feasibility, dependencies, permissions and concrete acceptance criteria.
Report actionable findings with file references and verification steps. Score
correctness, integration, resilience, verification and usability from zero to
two each. Explain every deduction and identify any critical or high-severity
blocker. Recheck repairs using evidence. Mark live operation and profitability
unverified when observations are absent. Never raise a score merely to meet
the nine-out-of-ten target.
