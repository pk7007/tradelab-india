# News Agent upgrade — Codex subagent orchestration

This document provides **Codex instructions and task definitions**, not proof that any agent thread, monitoring daemon, live feed or strategy was launched. Use an opened Codex workspace on this branch to start a real multi-agent run. The current project supports Python 3.10+; avoid extra packages until justified.

## Quick start in Codex

Open the `tradelab-india` checkout and give Codex this prompt:

> Execute the News Agent upgrade described in `AGENTS.md` and `docs/news-agent-subagents.md`. Use custom project agents. First spawn `repo_audit`, `source_compliance`, and `implementation_planner` concurrently **read-only**, wait for all three, and produce a baseline evidence matrix. Then have the main agent assign one file owner per implementation workstream and dispatch only the highest-priority P0 tasks. Limit concurrent subagents to three; use additional waves only if dependencies and previous tests allow. Implement real changes, run targeted and full offline tests, report measured results; never invoke live trades, paid APIs, or restricted feeds. Ask for approval before adding paid dependencies or external data access. Return a compact stage-by-stage summary, modified files, commands, test counts, and blockers.

The `[agents]` config caps parallel threads at 3; it **does not** launch the threads by itself. In Codex CLI use `/subagents` to inspect active threads. Verify your Codex client supports the model IDs configured in each TOML; substitute a supported model if necessary.

## Roles and acceptance gates

| Phase | Codex agent | Primary responsibility | Acceptance proof |
|---|---|---|---|
| 1 | `repo_audit` | Trace all news paths, source state and tests | Evidence matrix with file references |
| 2 | `feed_ingestion` | RSS collection, persistence, health, failures | Fixture-based source and restart tests |
| 2b | `source_compliance` | Entitlements, terms, privacy and provenance review | Source permissions matrix; no bypass |
| 3 | `symbol_resolver` | NSE/BSE identifiers, aliases and ambiguity | Ambiguous-name fixtures |
| 4 | `financial_intelligence` | Event extraction, sentiment and uncertainties | Strict typed output plus negative tests |
| 5 | `ai_budget` | Opt-in provider, caching and hard budget enforcement | Zero-key and exhausted-budget tests |
| 6 | `event_impact` | Point-in-time event studies and evaluation | No-lookahead synthetic fixtures; real performance unverified |
| 7 | `research_integration` | Read-only research and paper context | Broker/order invariants retained |
| 8 | `news_runtime` | Worker lifecycle, recovery and telemetry | Restart/idempotence/offline checks |
| 9 | `news_dashboard` | Honest per-source and event dashboard | API/UI contract tests |
| 10 | `security_reliability` | Secrets, prompt injection and failure review | Findings with reproductions |
| 11 | `qa_regression` | Suite coverage and failure injection | Counted tests, no masked failures |
| 12 | `benchmark_evals` | Quality metrics and calibration protocol | Reproducible scoring definition |
| 13 | `implementation_planner` | Dependencies, file ownership, milestone plan | No conflicting writers |
| 14 | `codex_efficiency` | Token/call minimization, unnecessary work review | Focused diff and cost checkpoints |
| 15 | `release_auditor` | Independent final verification and runbook | Evidence-backed before/after scores |

There are **16** roles for 15 phases; phase 2 has an additional independent source compliance review.

## Dependency-driven waves

**Wave 0 — read-only baseline:** `repo_audit`, `source_compliance`, `implementation_planner`. Parent waits, confirms actual files and selects highest-value fixes.

**Wave 1 — P0 foundation:** `feed_ingestion`, `symbol_resolver`, `news_runtime`. Delegate each to a distinct file set where possible. If integration into `news_agent.py` is required, let the parent integrate serially. Then have `qa_regression` test the merged result.

**Wave 2 — P1 opt-in intelligence:** `financial_intelligence`, `ai_budget`, `security_reliability`. No paid calls in test or default runtime. The security agent reviews before a provider is enabled.

**Wave 3 — integration and UI:** `research_integration`, `news_dashboard`, `qa_regression`, scheduled in sub-waves based on edit overlaps. Preserve old API clients and execution gates.

**Wave 4 — research only with data rights:** `event_impact` and `benchmark_evals`. Do not report validated alpha until authentic point-in-time out-of-sample evidence exists.

**Wave 5 — closeout:** `codex_efficiency` and `release_auditor`; collect actual test commands, outputs, scope of verification and deferred issues.

Skipping a wave is valid when data rights, runtime access or budget is absent. The parent—not a subagent—decides when to advance.

## Ownership and merge policy

- `news_agent.py`, `app.py`, `dashboard_news.py`, `worker_runtime.py`, and `research_context.py` are shared integration surfaces. **One writer at a time** for each; the coordinator integrates cross-boundary patches.
- Prefer additive focused modules: `news_symbols.py`, `news_intelligence.py`, `news_ai_budget.py`, `news_impact.py`, `news_service.py`, each with matching `tests/test_*.py`.
- An agent may read any file, but before editing must declare the files it will own; if ownership conflicts, pause that write and ask the coordinator to serialize it.
- Do not have multiple subagents commit directly to the shared branch at once. The coordinator reviews, tests and commits the integrated changes.
- No mass refactor of the trading engine, no broker order capability, no surprise paid services.

## Initial verification commands

```shell
python news_agent.py --once --json
python -m unittest discover -s tests -p "test_news_agent.py" -v
python -m unittest discover -s tests -v
```

The first command accesses configured external RSS feeds and can fail if the network or source is unavailable; do not call it an offline test. The last two are intended to be offline. Existing JS tests and configured GitHub Actions should also pass where available. Inspect `docs/news-agent.md` for Windows commands.

## Status vocabulary

- **CONFIGURED**: project-level subagent TOML is present.
- **SPAWNED**: Codex has started a real agent thread.
- **IMPLEMENTED**: relevant code exists.
- **OFFLINE TESTED**: deterministic tests passed.
- **LIVE FETCH VERIFIED**: authorized external feed fetched at a recorded time.
- **FORWARD VALIDATED**: sustained external observations and trading evaluation completed.
- **PRODUCTION READY**: independently reviewed operational criteria met.

These labels are not interchangeable. Do not call this upgrade complete merely because `.codex/agents/` exists.

## Reporting contract

Each agent returns: `scope`, `findings`, `files_read`, `files_changed`, `tests_run`, `risks`, `blocked_items`, and `next_step`. Use concise evidence with paths and line numbers. The main agent produces a final score using the original weighted framework, marks unavailable evidence honestly, and reports the exact environment in which tests ran.
