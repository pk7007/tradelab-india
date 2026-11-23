# Master prompt: supervised paper automation from A to Z (owner logs in and arms)

Use with `docs/ecc-master-prompt.md` (ECC loop, roster, section 2 preflight, section 4 checks, 9/10 gate).
Where this file and `AGENTS.md` differ, `AGENTS.md` wins; ECC section 0 wins on attribution and branches.
Status: revised 24 Nov 2026 after a first review scored 5/10. Independent review: 5/10, then 8/10, then 9/10 (24 Nov 2026) with no critical, high or medium finding. That scores the document as a plan only; implementation, live data and profitability are unverified.

## Goal
Once the owner has logged in to Zerodha and armed one session, the rest runs without further clicks:
selection, data, signals, risk checks, sizing, PAPER execution, exits, the account's configured square-off
(reference 15:05 IST), reconciliation,
reports and alerts. Between sessions the supervisor only observes and alerts. It never arms, logs in or
resumes a faulted run on its own.

## Authority limits (never relaxed by this prompt)
- Owner-only: Zerodha login, the calendar and retention attestations, and arming (`docs/paper-run-runbook.md`).
  "Login detected" means the server-side session already holds an access token (`app.py` `session.get(
  'access_token')`); never handle credentials, TOTP or cookies, never read `.env`, never log tokens or URLs
  containing `request_token`.
- Arming stays an owner action unless the owner records, in the decision log and in chat, a standing,
  versioned calendar plus retention attestation and a bounded auto-arm, allowed only after phase 4 is
  reviewed at 9/10 or higher. Bounds: an expiry date, one account and its symbol scope, a maximum number of
  consecutive sessions, a revocation path (owner kill switch or deleting the decision-log entry), and no
  auto-arm after any fault, restart or idle expiry. Never fabricate an attestation. Faulted, restarted or idle sessions always need inspection and an explicit
  re-arm (`docs/continuous-paper-worker.md`).
- Paper only: modelled fills in the paper ledger. `LIVE_EXECUTION_READY` stays `False`. No loss-limit,
  strategy-promotion or permission change. Phase 7 makes NO call to any broker order, modify or cancel
  endpoint, not even a test one (Zerodha has no sandbox); mocks only. Read-only broker calls happen only
  while the owner is logged in.
- The agent that builds these phases never starts a worker, never logs in, never calls the broker. Real
  session verification is the owner's; mark it UNVERIFIED. Ending the 23 Nov deferral is not permission to
  start workers. No profitability claims.
- Work on a feature branch, never push to master (ECC section 0). Stage explicit paths. No force push, no
  history rewrite, no secrets or private ledgers in Git. Creating a Windows scheduled task or any persistent
  system configuration needs the owner's approval.
- Optional research failure may block new entries but never stops exits, protective exits, exposure
  reporting or ledger reconciliation.
- If the independent reviewer cannot run, the task is BLOCKED, not passed. Run ECC section 2 preflight and
  section 4 checks before each review request.

## Baseline first (prerequisite, not a phase)
ALL uncommitted work is reviewed and committed (commit guard) on a new feature branch before any phase
builds on it, never on master: the modified tracked files (`app.py`, `automation.py`, `market_data.py`,
`tests/test_orders.py`, `.github/workflows/checks.yml`), the new modules (`broker_transport.py`,
`execution_controls.py`, `api_rate_limits.py`, `market_observations.py`, `transaction_costs.py`) with their
tests, and `docs/audits/`. Exclude `.claude/` (including `launch.json`), `.env` and anything private or
secret. If the owner wants any part left out, it stays uncommitted and phases that depend on it wait. Until
committed, none of it counts as baseline.

## Design decisions fixed by this prompt
- Engine: automatic selection (`auto_selector.py`, market-wide calendar), not the fixed-symbol worker. The
  runbook requires selection off for the fixed-symbol path; this prompt uses the selector path only.
- Timeframe: the paper engine and `intraday_contract.py` are 5-minute; any strategy wired in must be
  5-minute. Reuse existing modules: `scripts/watch_service.py` (observer), `operational_alerts.py` (incident
  inbox), `scripts/project_report.py` and `weekly_digest.py` (reports), `validation_lab.py` (check what
  validation it already covers before building more), `experiment_registry.py`.
- Alert channel: the local incident inbox plus an on-screen/Windows notification. Email, Telegram or any
  external message needs separate owner approval.

## Phases (each: failing test first, independent review, recheck to >= 9/10, commit guard)
Order is mandatory: A, then 1 to 7.

**A. Lineage and entry gate (prerequisite for phase 2; may split into A1 store and A2 gate, each reviewed).** Scope: `docs/agent-integration-requirements.md`
"still to implement", a durable lineage store (input versions, availability times, task IDs) and a gate that
blocks NEW entries only when required evidence fails. Map each step to registry roles. Out of scope: gating
exits or reconciliation. Acceptance: (1) failed evidence blocks a new entry in a test; (2) the same failure
leaves a stop/square-off and reconciliation running; (3) lineage rows reference input version and
availability time; (4) a missing optional research input never blocks exits.

**1. Calendar and trading-day source.** Name the source (https, with version and `availableAt` as in the
runbook manifest), refresh cadence, and the data-terms/licensing check for NSE holiday lists. Special
sessions stay unsupported and fail closed. Acceptance: (1) non-listed date refuses to start; (2) stale or
non-covering calendar fails closed; (3) null/holiday day yields no processing; (4) the calendar supplies the
close that the square-off validation uses, and a fake clock at the configured square-off triggers it;
(5) source/version recorded in the session record.

**2. Daily pre-market pipeline.** Data validation, issuer/event mapping and stock selection via
`auto_selector`, with lineage from A. Acceptance: (1) bad data blocks selection for that day; (2) selection
records its inputs and availability times; (3) no stock selected means abstain, logged; (4) no network or
secrets needed for tests.

**3. Arming and session start (owner-initiated).** Provide a single "arm for today" owner action that shows
the attestations, calendar and selection, then starts the supervised session. Optional bounded auto-arm only
under the standing authorization above. Acceptance: (1) refuses without access token, calendar entry and
storage approval, and auto-arm refuses past its expiry, past the session cap, outside its symbol scope and
after any fault; (2) a fresh process starts disarmed; (3) idempotent start (no double worker); (4) owner
kill switch always wins; (5) no attestation is ever written by code.

**4. Supervision, token loss and recovery.** Reuse `watch_service` and `operational_alerts`. The watchdog
detects and alerts; it may restart the PROCESS only into the disarmed state. `scripts/fixture_recovery.py`
is a test replay, not production recovery. Token loss or idle expiry (1800 s idle, daily Kite expiry) with an
open modelled position: block new entries, keep square-off and exposure state visible, alert the owner, no
phantom fills. Acceptance (injected `clock` and `fetch`): (1) token loss with an open position raises an
alert and blocks entries; (1b) terminal state: the position stays open and is flagged EXPOSED, the alert
persists until the owner logs in and re-arms for recovery, and the final ledger shows no phantom fill (checked by comparing ledger fills with accepted candles);
(2) exit state remains reportable; (3) restart returns disarmed; (4) crash
reconciles the paper ledger; (5) HTTP-loopback restart tests that Windows blocks (WinError 10013) are
reported UNVERIFIED. Windows hosting (Task Scheduler or console), sleep, lock screen and the OneDrive path
risk are documented; setting it up is the owner's action.

**5. Strategy wiring, split into units.** (a) Fix the 5-minute timeframe and an explicit exit, stop, target
and sizing from saved risk limits for EMA 20/50 + ADX. (b) Check `validation_lab.py` for walk-forward before
building any; build only the gap. (c) Corporate-action-adjusted data (none exists today). (d) The control is the
paper account start approval ("Start authorizes one account, one session and its saved strategy and
limits", `docs/paper-approval-audit.md`); creating the account with the new strategy and starting it are
owner actions, and the strategy is not promoted. Acceptance per unit: tests seen failing
first, deterministic fixtures, no profit claim, the reviewer scores unit (d) separately.

**6. Reporting.** Automatic end-of-day report (positions, P&L, costs, slippage vs modelled fills,
abstentions, failures) and the weekly report via `scripts/project_report.py`. Output stays in the private
folder, not Git; ledger and broker-candle retention follows the runbook. Acceptance: a failed check shows as
failed; no profitability claim appears; nothing commits or pushes.

**7. Improvement proposals and live-path design (mock only).** Attribution on frozen experiments
(`experiment_registry.py`) writes PROPOSALS to a file or the inbox only; no automatic change to a running
strategy or limit. Live-path pieces (stops, reconciliation, kill with confirmed closure, rate limits) use
mocks and make no order-endpoint calls; proposals and live-path design get separate reviewer scores.
Acceptance: (0) a test or grep guard over tracked project sources (excluding `.venv`) proves no call site
such as `kite.place_order(`, `.modify_order(` or `.cancel_order(` on a Kite client object exists, with an
explicit allowlist for the existing local handler `Handler.place_order` in `app.py`, whose behaviour (gated
by `LIVE_EXECUTION_READY=False`) is recorded and reviewed; (1) proposals cannot alter config; (2) the kill path
returns cancel requests and exit intents with mocks; (3) reconciliation detects a mismatch in a fixture.

## Exit criteria before the owner may consider live trading (report only, not acted on here)
Floors, not proof of readiness: at least 20 observed paper sessions with logged abstentions, recoveries,
costs and slippage; walk-forward results across regimes with limits stated; independent review >= 9/10 on
phases A to 7; reconciliation proven against Zerodha's own records and broker-side stops as a SEPARATE
owner-decided step outside this prompt; the owner's explicit go-ahead in chat naming limits.

## Per-task final report
Files, tests added (seen failing first), commands and results, reviewer score and deductions, commit id and
remote tip, what is UNVERIFIED, and the owner's remaining actions (login and arm first, always).
