# End-of-day and weekly paper reports (Phase 6)

`eod_report.py` and `scripts/eod_report.py` build a Markdown report from the paper ledger. They are read-only:
the database is opened with SQLite `mode=ro`, the paper engine is never constructed (constructing it pauses running
accounts), nothing logs in, no order is placed and no network is used.

## What it reports (per account, per day)
- Position, modelled P&L (equity change over the day; labelled a modelled paper result, not evidence of edge).
- Fills with the candle open they were modelled from, slippage in bps and in rupees, and fees.
- Abstentions (`rejected` / `skipped` events) with their reasons; restarts and invalidated entry reviews as notes.
- Failures, each making the status FAILED: ledger that does not reconcile, a fill with no accepted candle, slippage
  that differs from the saved model, a candle-feed error, an intraday position still open after the last candle,
  any open incident in the inbox, a missing or unreadable database.

Status is PASS, FAILED, or NO DATA (a day without candles is never PASS). No profitability claim is made.

## Running it
```
python scripts/eod_report.py --day 2026-11-25
python scripts/eod_report.py --week-ending 2026-11-27
```
Exit code 0 PASS, 1 FAILED, 2 NO DATA, 3 bad arguments. A missing default incident inbox is noted in the report as not checked; an explicit `--alerts` path that does not exist makes the report FAILED. Output goes to `%LOCALAPPDATA%\TradeLabIndia\reports` (private, outside Git).
Nothing commits or pushes. The repository status report remains `scripts/project_report.py`.

## Scheduling (owner action)
Run the command after the close (for example 16:00 IST) with Windows Task Scheduler. Creating a scheduled task is a
persistent system configuration and needs your approval; this project does not create one.

## Limits
- A report describes the ledger as of when it runs: position and open-position checks apply to the latest day only.
- Slippage "vs modelled fills" compares the ledger fill with the saved assumptions; real broker fills do not exist in paper mode.
