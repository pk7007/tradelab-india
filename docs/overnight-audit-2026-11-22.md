# Scheduled offline paper audit

22 November 2026, Asia/Kolkata. Audit of the current uncommitted working tree,
preserving account history and existing work. Market activation remains deferred
until 23 November. No broker orders or authenticated market checks are required.

## Audit findings before repair

P1 confirmed independently. app.py's PAPER_BUILD_FILES omits strategy_contract.py
and research.py, although the paper path depends on their signals, fill math,
timestamps and candle validation. A change to these dependencies leaves the
reviewed build fingerprint unchanged. Reproduce without editing production code
by reading the file list through AST, hashing its bytes and changing the omitted
dependency bytes in memory. The aggregate is unchanged because those bytes are
absent. The supervised build check therefore cannot detect that strategy change.

The source audit also covers scheduled Start, CSRF and ownership, grant
revocation, selection, dated entry reviews, expiry, atomic consumption, modeled
costs, protective exits, reconciliation, restart and isolated restore, secret
handling and session reporting. Relevant regression families are
test_intraday_http, test_auto_selector, test_intraday_paper, test_paper_worker,
test_storage_ops, test_orders, test_session_evidence and test_intraday_session.
The bounded review has found no additional confirmed critical or high-severity
defect at this stage. Operational provider delivery and profitability remain
unverified.

## Repair and verification

Added both core dependencies to PAPER_BUILD_FILES and a new AST/in-memory
regression in tests/test_paper_build.py. It verifies that changing either file
changes the reviewed fingerprint, without importing the app or editing source.
The independent reviewer reproduced the issue and passed the repaired regression,
24 selector tests and three storage tests.

All seven JavaScript regression files passed. The initial complete Python run
executed 370 tests, with four HTTP connection permission errors. Those four
passed separately after authorization. The new build regression also passed.
A complete authorized rerun stalled and was interrupted; that run supplies no
passing claim. A subsequent restricted run was also interrupted after appearing
stalled. Final discovery with a diagnostic timeout completed 371 tests in 56.468
seconds, with only the same four Windows HTTP permission errors. Those four had
passed on the separate authorized retry against the repaired source. Across
completed discovery and retry runs, all 371 tests passed. No diagnostic timeout
fired in the final run.

The real Chromium fixture replay passed on the installed global Python after
the project virtual environment lacked Playwright. The restricted browser run
stalled and was interrupted, then the authorized run completed. It used isolated
databases and generated data, the real HTTP handler and selector loop. Both
qualifying and no-trade sessions required one Start click and no further trading
clicks, produced zero page errors and made zero broker orders. The qualifying
fixture ended with cash 10435.1616328, fees 20.2921672 and zero shares. The no-trade
fixture retained cash 10000, zero fees and zero shares. Both closing reports
matched the independent oracle. Fresh evidence is in intraday-session-example.json.
Existing reviewer-outage and malformed-review tests verify that protective exits
survive entry-review failure. The replay did not use a real broker account.

## Operational handoff

Both market-supervision and closing-review schedules now require fingerprint
3fbc6144de01613777d97c251e5cb7b490d3b512e796ed65d94600cc8840d23a.
The currently responding backend still reported the previous fingerprint and was
disarmed with no outstanding exposure. A guarded restart attempt stopped at
process identification because the Windows listener query could not find the
responding listener. No application process was terminated. Restart the main
application before Monday, then verify the fingerprint before supervised Start.
The schedules will block an old build instead of accepting it.

The independent scoped paper-engineering assessment remains 9/10. Whole-app
integration, authenticated forward-market operation and profitability remain
subject to their existing evidence gaps. No financial settings or active history
were changed. These repairs and the updated evidence remain local.
