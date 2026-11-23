# Master prompt: structure check, paper-run readiness, auto report, new rating (23 November 2026)

This is a filled-in task list for `docs/ecc-master-prompt.md`. Follow that prompt's authority limits,
ECC loop (plan, failing test first, implement, independent review, verify, improve, commit), subagent
roster, section 4 checks and 9/10 gate. Where this file and `AGENTS.md` differ, `AGENTS.md` wins.

## Owner request
1. Check the repository structure and keep everything intact, using the ECC method.
2. Make paper trading run successfully with the Zerodha API.
3. Produce a complete report (done, next steps, fixes) that runs automatically.
4. Produce a complete, fresh rating of the application.

## Limits that shape the tasks
- Paper trading with Zerodha needs the owner's interactive Zerodha login and a live connection to Kite.
  A cloud agent session has neither. The agent prepares, verifies offline, and writes the runbook. It must
  never claim a Zerodha paper run succeeded unless it observed one. Mark it UNVERIFIED otherwise.
- Paper means modelled fills in the paper ledger. No real broker order is placed. `LIVE_EXECUTION_READY`
  stays `False`, and no limit, strategy promotion or broker permission changes.
- Keep everything intact: no deletions, moves or renames of tracked files, no history rewrite.
  Structure work is read-only except for new files that report on it.
- Ratings are judgments from evidence. The automatic report may compute measurable facts only. It must not
  compute or imply a profitability rating.

## Tasks
**S1. Structure check (read-only, automated).** Add `scripts/structure_check.py` that, without changing any
file, reports: Python modules versus the `py_compile` list in `.github/workflows/checks.yml`; modules
without a matching test; web scripts versus `node --check` coverage; docs with broken relative links;
tracked files over 500 KB; secrets-pattern hits (names only); tracked paths that should be ignored
(`.env`, `*.sqlite`, `data/private`). Exit non-zero only for integrity failures (missing CI coverage of a
module that exists, a tracked secret/database). Tests first, using temporary fixture trees.

**S2. Paper-run readiness (offline) and runbook.** Add `scripts/paper_readiness.py` and
`docs/paper-run-runbook.md`. The script checks, without network or secrets: live execution locked; Kite
variable NAMES present or missing (never values); `kiteconnect` importable; private data directory
writable; paper database opens and integrity-checks; the worker is disarmed by default; the fixture
recovery replay passes; session and square-off configuration valid; storage-approval flag state. It prints
a PASS/FAIL/BLOCKED checklist and the exact owner steps: connect Zerodha in the browser, confirm the
storage-approval and calendar settings, arm the paper worker for one session, and export the session
evidence. State plainly which steps only the owner can perform.

**S3. Automatic report.** Add `scripts/project_report.py` that runs the offline checks (pytest counts, ruff,
bandit, JS tests, structure check, paper readiness) and writes a dated Markdown report: what changed since
the last tagged report (git log), check results with real counts, open findings carried from
`docs/current-state-audit-2026-11-23.md` and `docs/tooling.md`, recommended next steps, and a link to the
latest human-reviewed rating. Add `.github/workflows/status-report.yml` (weekly schedule plus manual
trigger, read-only permissions) that uploads the report as a build artifact. It must not commit, push or
touch broker settings. Tests first for report assembly with stubbed check results, including that a
failed check is shown as failed and that no profit claim appears.

**S4. Fresh rating.** After S1 to S3 are reviewed, write `docs/rating-2026-11-23.md` from observed
evidence: the same aspects as the earlier rating, what changed since and why, and an explicit statement of
what is unverified (live Zerodha run, real model call, forward paper results, profitability). An independent
reviewer must check every score against evidence. Do not raise a score to meet a target.

## Execution order
Apply the pending reviewed patches first (T1 kill safety, T2 hardening, T3 EMA/ADX), then S1, S2, S3 in
parallel in isolated worktrees based on the latest pushed tip, then S4. Each task gets its own independent
reviewer, repair rechecks by the same reviewer, and its own commit by the commit guard under the owner's
identity with no AI attribution lines.

## Final report
Per task: files, tests added (seen failing first), commands run with results, reviewer score, commit id,
remote tip. Overall: baseline versus final counts, the Zerodha run status (UNVERIFIED unless observed),
the owner's remaining actions in order, and the new rating.

## Outcome (recorded 23 November 2026)
- T1 to T4 (earlier task list), then S1 to S3, were each implemented test-first, independently reviewed
  and rechecked to 9/10 or above, and committed under the owner's identity: `0dcd205` (`kill()` fail-safe),
  `e7f5e83` (hardening), `5d24962` (EMA/ADX), `0121fe3` (news label UI), `09a7659` (S1), `111c667` (S2),
  `57c9076` (S3).
- A review of every commit then found two regressions from earlier commits (strict UTF-8 feed decoding;
  assessor database created at import time). `2474a07` fixes both. All ten commits are in open pull
  request pk7007/tradelab-india#13.
- S4 is `docs/rating-2026-11-23.md`.
- Not done, and not claimable: a Zerodha paper run (owner login required), a real model call, forward paper
  results, and any profitability evidence. The owner's remaining actions are in `docs/paper-run-runbook.md`.
