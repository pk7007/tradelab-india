# Improvement execution record

21 November 2026. Executed the first offline phases of
[the reusable improvement prompt](improvement-execution-prompt.md) against the
existing working tree. Existing user changes were preserved. This record covers
the bounded improvements below. It does not close the full platform roadmap.

| Phase | Baseline gap | Delivered result | Verification | Remaining acceptance |
| --- | --- | --- | --- | --- |
| Signal consistency | Shared SMA already existed, but equivalent callers lacked explicit cross-path boundary evidence and intraday replay omitted its signal-contract identity. | Added signalContract to intraday_evaluation.py and tests/test_signal_consistency.py. | Warmup, equality, rising/falling inputs agree across scanner, reviewer and replay. Historical evaluation uses prior completed closes. A signal cannot fill at its own bar open. | Actual-market observations and strategy outcome evaluation remain pending. |
| Storage recovery | Generic SQLite restore tests did not exercise a held paper position with a partial exit. | Extended tests/test_storage_ops.py with an isolated live-paper-schema backup/restore drill. | Seven remaining shares, cash, fees, cost basis, protection and pending SELL survive restoration. Subsequent fixture liquidity closes the restored position, with ledger agreement and source state untouched. | Operational drills against controlled copies of actual configured multi-ledger storage remain pending. |
| Licensed feed prerequisite | The cache accepted injected transport, without a safe provisioned HTTP implementation. | Added syndication_transport.py, four security regression tests and commented .env.example fields. | Explicit approved HTTPS host, bounded requests, documented endpoints/params, disabled redirects, hidden credentials, redacted failures and malformed payload rejection. Sixteen cache/transport tests pass. | Actual access, app/scheduler integration, publisher compatibility, source-health display and purge operations remain pending. No real service was contacted. |
| Documentation and ongoing checks | Historical setup instructions could be read as current; new modules needed ongoing syntax coverage. | Marked docs/intraday-readiness.md as historical and linked current setup. Extended .github/workflows/checks.yml syntax checks. Saved the executable master prompt. | Syntax and whitespace checks pass. Reviewer verified prompt feasibility. | Hosted CI and runtime feed acceptance remain unobserved. |

## Regression evidence

Python discovery executed 370 tests. Four HTTP tests were initially blocked by
Windows local-connection permissions and passed on authorized retry. All 370
therefore passed across those runs. All seven JavaScript test files passed.
The independent reviewer separately executed nine focused tests across the
signal, storage and transport phases. Python syntax and git diff --check passed.
No Chromium rerun was performed in this batch.

## Independent review

The batch scored 9/10 with no unresolved critical or high-severity finding.
Correctness 2/2, integration 1.5/2, resilience 2/2, verification 2/2 and usability
1.5/2. Deductions cover unobserved publisher compatibility and the incomplete
provisioning and runtime connection. The whole-application score remains 6.8/10.
Profitability and actual-market operational performance remain unverified.

## Next work and prerequisites

- Obtain the actual approved feed URL, host and credentials in local private
  configuration. Configuration readiness alone reports connected=False. Do not
  activate ingestion until scheduling, correction monitoring and permitted
  retention across all copies have been reviewed.
- Verify the calendar and broker login before the deferred 23 November market
  session. Interactive login belongs to the user. Trace the actual closing
  report and journal through the existing closing-review automation.
- Finish the durable graph of required agent handoffs, persistent alerts and
  representative end-to-end interface coverage. This batch adds tests and a
  provisioning foundation, not completion of those larger integrations.
- Freeze evaluation criteria before observed trials and gather independent
  outcomes after costs. Long-term expansion remains deferred.

Changes are local and have not been published by this batch. The live-order gate,
saved financial limits and current trading sessions were not changed.
