# Intraday paper automation

TradeLab opens on one Auto Trading screen. Settings holds broker connection,
saved assumptions, imports and diagnostics. Long-term research is deferred until
intraday forward-market acceptance is complete.

## Start and supervise

Run `.\.venv\Scripts\python.exe app.py` from the repository root and open
http://127.0.0.1:8765/. Existing account history stays in the configured local
SQLite storage. A fresh server starts disarmed and requires broker reconnection.

Choose an imported Intraday v1 assumptions account, review its actual limits,
connect Zerodha in Settings and verify saved storage permission and the displayed
calendar. Start paper trading activates discovery and completed-candle processing
inside a confirmed session. Calendar coverage and market-dependent activation
remain subject to the existing reviewed dates and deferral.

The intended profile is capital ₹10,000, planned trade loss ₹250 and daily loss
threshold ₹1,000. Existing accounts retain their own limits. The screen displays
differences. Selection creates one managed account per session and carries
reconciled available cash forward. Losses reduce subsequent available capital.

The selector screens current NSE equity quotes, checks full five-minute history
for up to twenty affordable names ranked by turnover proxy, then uses the shared
SMA 5/20 condition and sizing constraints. Twenty completed session candles are
required, so the earliest regular-session selection is 10:55 IST. No qualifying
candidate leaves cash uninvested. Quote coverage and candle coverage are shown
separately.

## Controls and recovery

| Control | Result |
| --- | --- |
| Start paper trading | Validate permissions, calendar, account state and ownership, then select or recover the existing managed account |
| Pause new entries | Cancel pending buys and prevent entries while retaining position management |
| Resume new entries | Re-enable entries only where the saved session and risk checks allow it |
| End session and reconcile | Prevent further entries, request required exits and continue observations until flat and reconciled |

An End request is distinct from a completed exit. Missing observations, inadequate
modeled volume, expired authentication or a closed observation window can leave
exposure unresolved. The main screen keeps quantity, pending exits and recovery
instructions visible. A newly requested exit cannot receive an observation from
before the request. Previously existing protective rules retain their original
eligibility.

Repeated Start and replayed bars reuse durable selection and ledger identities.
Worker leases fence simultaneous writers. Restart preserves account history and
pending protection while pausing processing. Existing managed exposure can be
recovered after the entry cutoff, including a prior session where the explicitly
supplied calendar covers the required dates. Required missing history blocks
processing visibly. Recovery after the cutoff or from a prior session suppresses
new entries. Earlier same-day recovery preserves the saved entry controls.
Legacy manual mutation and
import endpoints reject managed accounts so they cannot bypass session controls.

Read-only `GET /api/intraday-session` presents readiness, actual profile,
outstanding account exposure, selection, closing report and evidence. Mutations
use the normal session and CSRF protection. Paper mode has no broker-order
authority.

## Timing and research

Prices are completed five-minute observations. Paper fills are modeled OHLC
outcomes, recorded when observations arrive. The evidence distinguishes signal
bar, modeled fill bar, provider receipt, decision time and journal recording time.
This is an explicit historical execution assumption. It does not establish a
price available to a live order submitted at receipt.

Permitted news is attached as advisory context. A news outage leaves protective
price processing available. No validated sentiment or news-to-entry rule has
been established. Sources with unavailable credentials remain disconnected.

The scheduled desk observer also runs actual registered descriptive evidence
roles over strategy version, candles, fills, costs, sizing, risk, exposure,
reconciliation and attribution when those records exist. Each analysis has a
separate handler re-computation, stored input hash, task identity and immutable
attempt history. Retries stop after three failed attempts. The main screen shows
roles that ran and missing stages. These retrospective checks have no financial
control authority. They do not approve a strategy or establish profitability.

## Verification

Run `python -m unittest discover -s tests` and the existing Node test files.
The regression suite uses isolated databases and fixture broker observations.
`tests/test_intraday_http.py` exercises actual local HTTP routes through selection,
pause, end and ledger reporting. It covers no-trade sessions, CSRF rejection,
managed-account mutation bypasses and optional news failure.

With Playwright and its Chromium installed in the testing environment, run
`python scripts/check_intraday_ui.py`. This launches an isolated server and
drives one Start click and the real selector loop through automatic closure in two
isolated sessions. The qualifying fixture bought and sold 97 simulated DEMO
shares, ending at ₹10,435.16 after ₹20.29 of fees. The no-trade fixture retained
₹10,000. Each had zero further trading clicks and zero broker orders. Both reports
survived a page reload. These figures describe controlled price inputs.

The [approval inventory](paper-approval-audit.md) covers standing permissions,
service reviews, protective exits and the independent manual tools.

## Remaining acceptance

Forward-market observation, current broker login and source-backed session
calendar checks remain necessary. Strategy profitability and a news-to-signal rule still require validation. Long-term
research implementation follows this intraday acceptance. Real-money activation
has its own broker inventory, cash, order-reconciliation and approval dependencies.
