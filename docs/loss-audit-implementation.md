# Loss-audit repairs — 20 November 2026

Source changes are verified offline. The running main application has **not**
been restarted. Existing paper account settings and real-order locks are unchanged.
No candidate passed promotion. Private research output stays outside this repository.

| Root cause | Repair | Regression evidence | Historical effect / limit |
|---|---|---|---|
| Fixed 75-candle expectation discarded complete shorter continuous sessions | `paper.py`, `paper_worker.py`: explicitly attributed calendar bounds and earlier-exit arm checks | `tests/test_worker_loss_regressions.py`: consecutive 72-bar sessions, missing closing candle, late exit rejected | Frozen original fills identical; newly included periods are separate experiments. CAS eligibility remains security-specific. |
| Checking only adjacent endpoints allowed omission of an entire open day | `paper.py`: intervening dates must be explicitly closed | Missing-open-day and unknown-day regressions in worker loss tests | No silent skipped sessions with a supplied calendar. Legacy no-calendar behavior remains compatible. |
| Batch filter silently moved final window backwards | `scripts/paper_research_batch.py` now refuses unreviewed complete 72-bar days; `scripts/data_quality_audit.py` explains exclusions | `tests/test_calendar_evaluation.py`, `tests/test_data_quality_audit.py` | Original experiment is preserved; calendar-aware results are versioned separately. |
| Exact-window hashes allowed shifted and validation-to-final evidence reuse | `strategy_lab.py`: durable exposure windows, reservations before replay, conservative legacy handling | `tests/test_loss_audit_regressions.py`: shifted windows, validation reuse, restart, legacy seals | No economic fill changes; previously exposed evidence cannot regain independence through another hypothesis. |
| Candle receipt counts could qualify losing, unrelated forward history | `strategy_lab.py`: candidate-specific executable quote receipts, marks, positive performance and uncertainty gates | Losing 30-trade, missing-mark, wrong-lineage and candle-receipt regressions | Quote producer remains unimplemented; current candle workers cannot qualify for promotion. Rollback tests still pass. |
| Replay fingerprint omitted calendar | `intraday_evaluation.py`: calendar-bound evidence hash and implementation hashes | `tests/test_calendar_evaluation.py`: same fills, changed calendar, different fingerprint | Legacy data/config fingerprints remain compatible when no calendar is supplied. |
| Generic worker errors discarded actionable diagnosis | `paper_worker.py`: allowlisted reason codes and stages | Revised-bar, gap and provider-secret tests | Exact earlier failure cannot be reconstructed. Unknown provider messages remain excluded from persisted diagnostics. |
| Calendar timestamps were treated as numeric domain prices | `agent_handlers.py`: calendar time fields use their temporal contract | All-role fixtures in `tests/test_agent_runtime.py` | Research role validation repair; no trading signal change. |
| Database test connections remained open on Windows; recovery drill used default news storage | `tests/test_storage_ops.py` closes connections; `scripts/fixture_recovery.py` isolates all data paths | Storage tests and real HTTP restart/disconnect/recovery drill | Temporary test state only; active account not used. |

## Reproduce the audit

Use the existing permitted CSV and original private batch. Scripts never place
broker orders or modify the configured paper account:

- `scripts/batch_loss_audit.py`: independently group partial fills, reconcile
  costs, reproduce original trials and retain all exploratory outcomes.
- `scripts/data_quality_audit.py`: read-only attributed session-quality assessment.
- `scripts/cas_research_batch.py`: preregister three bounded entry/exit candidates,
  evaluate validation with an explicit calendar, leave reserved outcomes unopened.
- `scripts/render_batch_audit.py`: render a new private report and source snapshot.

Always choose a **new private output directory**; previous results are preserved.
The old synthetic `scripts/loss_audit.py` remains unchanged and is a different tool.

## Operational limits

Keep the main paper worker stopped until its earlier failure and calendar-safe
configuration are reviewed. Do not change existing account assumptions invisibly.
The current account's square-off cannot occur at a continuous session's closing
boundary. A reviewed new experimental account is needed if immutable assumptions
must change. Restarting the main app will require verification and may require
another Zerodha login. No new paid AI API is needed for these offline checks.

The supervisor was subsequently updated and verified on 20 November 2026 to
prevent automatic re-arming of the blocked account or restarting the backend
until a reviewed calendar-safe configuration and loaded fixes are verified.
Scheduled checks remain active and unchanged blocked states stay quiet.
Executable quote simulation, corporate-action verification and profitable
candidate-specific forward evidence remain open requirements.
