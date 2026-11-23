# Continuation audit and fixes — 23 November 2026 (evening run)

Scope: independent audit of the changes merged through PR #3 and PR #13, the Dependabot
bumps (0711bc4) and the Claude Code settings (4ac779a). Branch `claude/stoic-ritchie-rrgudu`.
No broker login, live paper session, live feed, network model call or paid service was used.
Complements `docs/current-state-audit-2026-11-23.md` and `docs/rating-2026-11-23.md`.

Classification: VERIFIED / PARTIAL / FAILED / NOT IMPLEMENTED / UNVERIFIED / BLOCKED.
"VERIFIED" means verified offline by the evidence cited, nothing more.

## Baseline

| Item | Value |
|---|---|
| Baseline SHA | `origin/master` = `4ac779afb1eba434d71c5eebff29da1f47e24327` (unchanged from the last observed SHA) |
| CI on baseline | "Offline application checks" run 83 on 4ac779a: success |
| Open PRs at start | None. #1 and #2 closed unmerged (17:41 UTC). #3 and #13 merged. #4–#12 closed; their bumps were applied directly in 0711bc4 (#12's settings in 4ac779a). |
| Environment | Linux, Python 3.12.3 venv, anthropic 2.13.0, pydantic 2.14.4, kiteconnect 5.2.2, Node (CI-equivalent `node tests/*.test.js`) |
| Run time | 2026-11-23 21:39–22:10 UTC |

## Checks executed

| Command | Baseline | After fixes |
|---|---|---|
| `python -m pytest -q` | 570 passed, 567 subtests | 573 passed, 567 subtests |
| `python -m unittest discover -s tests` | — | OK |
| `ruff check .` | clean | clean |
| `bandit -q -r . -c pyproject.toml --severity-level high` | exit 0 | exit 0 |
| 10 × `node tests/*.test.js` | all exit 0 | all exit 0 |
| `python scripts/structure_check.py` | integrity 0, info 2 | same |
| `python scripts/fixture_recovery.py` | pass | pass |
| `python scripts/paper_readiness.py --json` | ok, 7 PASS / 6 BLOCKED / 0 FAIL | same |
| `python scripts/project_report.py` | Overall PASS | — |
| `pip-audit -r requirements.txt -r requirements-ai.txt` | 3 advisories in autobahn 19.11.2 (see Security) | unchanged |

## Defects found and fixed

### F1 — AI news labeller could never succeed (P1, FAILED → fixed, live call UNVERIFIED)

- Evidence: `news_intelligence.py` `anthropic_completer` passed `temperature=0`. With the pinned
  `anthropic>=2.12` (2.13.0 installed), `Messages.create` has no `temperature` parameter, so each
  enabled call raised `TypeError` before any request. `assess_item` recorded it as `unavailable`
  and `news_assessor._tick` still counted the call against the daily budget. API version
  2026-10-21 (sent by this SDK) also rejects sampling parameters server-side.
- Reproduction: `ni.anthropic_completer('sk-fake')('hi')` → `TypeError: Messages.create() got an
  unexpected keyword argument 'temperature'`.
- Fix: no sampling parameters; `output_config={'effort': 'low'}`; `max_tokens` 400 → 1024 (current
  models think by default and thinking counts toward the cap); a `refusal` or `max_tokens` stop
  raises `IncompleteReply`, which the existing path records as `unavailable` with backoff.
- Tests: `CompleterRequestShape` binds the request kwargs to the installed SDK's real
  `Messages.create` signature (offline, fake client) and covers both stop reasons.
- Not changed: fenced-JSON replies are still rejected by design (existing test and doc).

### F2 — `ResearchRiskGate.kill()` could request an infinite exit (P0 area, low severity, fixed)

- Evidence: `research.py` `_exit_intents` validated each row as finite but not the merged total.
  Two BUY rows of `1e308` produced `{'quantity': inf}` with `exposureStatus: FLATTEN_REQUESTED`.
- Fix: a symbol whose merged quantity is not finite is rejected ("Merged quantity is not finite"),
  gets no exit intent, and the status falls to `UNKNOWN_NOT_FLATTENED`.
- Test: `test_merged_quantity_overflow_is_rejected_not_requested`.

## Independent review

One independent reviewer subagent (Python reviewer) reviewed both fixes and audited the areas
below, then rechecked after the F2 fix. Reported score for the combined diff: correctness 2,
integration 2, resilience 2, verification 1.5, usability 2 = **9.5/10**, no unresolved critical or
high issue. Deduction: no live-provider check; no test for a missing `stop_reason`/empty reply.
This is a code-review score only. It does not authorize orders, promotion or limit changes.

## Component findings

| Area | Status | Evidence / gap |
|---|---|---|
| Live execution isolation | VERIFIED (offline) | `LIVE_EXECUTION_READY = False`; readiness check `live-lock` PASS. Untouched by this run. |
| AI news intelligence: schema, grounding, symbol allow-list, prompt fencing, timestamps | VERIFIED (offline) | `tests/test_news_intelligence.py`; `availableAt = max(article, now)` |
| AI news intelligence: provider call | PARTIAL → fixed, **UNVERIFIED live** | F1. Needs a key via the secure credential form and owner approval for a paid call. |
| News assessor: SQLite, budget, single-flight tick | VERIFIED (offline) | Reviewer found no reproducible defect. Low: usage row written after the call returns, so a crash mid-call can under-count by one call; `stop()` waits 25 s while a call may take ~40 s (daemon thread, no hang). |
| Indicators (EMA, ATR, ADX) | VERIFIED (offline) | Reviewer's independent Wilder implementation matched on 20 random series, max abs diff 2.8e-14, warm-up positions identical. |
| EMA/ADX strategy | VERIFIED (offline), research only | No look-ahead; duplicate-signal across UTC offsets handled; mixed tz rejected. Not wired into trading (only its test imports it). No exits, sizing, costs or evaluation integration: NOT IMPLEMENTED by design. |
| `ResearchRiskGate.kill()` | PARTIAL | Intents only; never claims closure; never raises. F2 fixed. Low: symbol matching is case-sensitive (`X` BUY and `x` SELL are not detected as a conflict). Still not wired to any execution path. |
| Paper readiness preflight | VERIFIED (offline) | Reviewer diffed a copied tree before/after: no writes outside temp files/dirs. |
| Real paper run / Zerodha session | BLOCKED | Owner-only Kite login, credentials, calendar attestation and arming. Deferred market activation respected. |
| XML feed parsing | PARTIAL | `ET.fromstring` behind a case-insensitive DOCTYPE/ENTITY reject on decoded text (`announcements.py`, `news_agent.py`, `scripts/weekly_digest.py`); no bypass reproduced. `defusedxml` would be stronger. |
| CI | VERIFIED | Ruff, Bandit (high), syntax, JS tests, unittest, fixture recovery, structure check. `pip-audit` is report-only (`continue-on-error`). |
| Claude settings / ignore rules | VERIFIED (read) | `.claude/settings.json` denies reads of `.env*`, `data/private/**`, CSV/parquet/log. Side effect: `Read(./.env.*)` also hides `.env.example` from the agent. `.gitignore` excludes `.env*`, `*.sqlite*`, `data/private/`, `reports/`. |

## Security

- pip-audit: `autobahn 19.11.2` — PYSEC-2020-25 (×2) and PYSEC-2026-4027 (permessage-deflate size
  check bypass, server-side resource exhaustion). It is pinned exactly by `kiteconnect==5.2.2`
  (`autobahn[twisted]==19.11.2`), used only as a WebSocket *client* to Zerodha's ticker; the
  project runs no autobahn server. Not suppressed and not upgraded: upgrading needs a
  kiteconnect release that relaxes the pin, plus ticker regression testing. Accepting the risk
  is an owner decision; it stays visible in CI's report-only audit.
- No secrets in the diff. No credential was requested or used.

## PR #1 and PR #2

Both remain closed and unmerged. PR #1 (`feat/news-agent-codex-subagents`, 19 commits ahead, 22
behind) adds Codex subagent definitions only. PR #2 (`docs/portfolio-readiness-2026-11-23`, 9
ahead, 17 behind) is documentation. Neither contains runtime functionality missing from
`master`. Not reopened: no owner approval and no functional reason.

## Claimed vs verified

| Claim | Verdict |
|---|---|
| "Opt-in AI news labels" (PR #13) | Code paths verified offline; the provider call was broken until F1 and is still unverified live. |
| "EMA/ADX research code" | Numerically verified offline; research only. |
| "Kill switch" | Intents only; never flattens; F2 hardened. |
| "Paper readiness tooling" | Verified offline; real paper run BLOCKED on owner actions. |
| Profitability / live readiness | Not established. No evidence exists. |

## Scores (code quality only, out of 10)

| Component | Score | Note |
|---|---|---|
| AI news intelligence | 7 | Defensive design is solid; the provider path was dead until F1 and has no live check. |
| Indicators and EMA/ADX | 8 | Verified numerically; no exits/sizing/costs (by design). |
| Risk gate / kill | 6 | Correct for an intent-only contract; not connected to any OMS or broker. |
| Paper readiness tooling | 8 | Safe and honest; real-session evidence absent. |
| Security / CI | 7 | Good gates; pip-audit is report-only; pinned vulnerable transitive dep. |
| **Overall engineering quality** | **7.5** | |
| Paper-readiness | BLOCKED | Owner login and session evidence required. |
| Live-readiness | NOT READY | No broker-side stops, OMS reconciliation or live evidence; live execution locked. |

## Next five highest-value tasks

1. Owner-run supervised paper session during market hours (activation deferred until Monday
   23 Nov 2026 is now reached), following `docs/paper-run-runbook.md`, with ledger
   reconciliation evidence.
2. One owner-approved live check of `anthropic_completer` with a low daily cap, recording the
   accepted/rejected/fenced rate before any change to the strict JSON policy.
3. Write the EMA/ADX exit and sizing specification (versioned contract, explicit exits, costs,
   slippage, leakage checks) as a document before any evaluation wiring.
4. Normalise symbol case in `kill()` and record usage before the provider call in
   `news_assessor` (both low; add tests first).
5. Track a kiteconnect release that unpins autobahn; then upgrade with ticker regression tests.
