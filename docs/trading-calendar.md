# Trading calendar: source, refresh and limits

`trading_calendar.py` validates the attributed NSE EQ session manifest that the paper worker needs. It
makes no network call and verifies nothing with the exchange. The manifest is your own attestation.

## Source
- The manifest names its own https `source` and `references` (the shipped sample,
  `docs/infy-paper-calendar-2026-11-20.json`, cites NSE circulars). For holiday and special-session dates
  use NSE's official holiday list and trading-holiday circulars, and copy dates by hand.
- Each manifest needs `version`, `availableAt` and an explicit entry for every date to run (`null` =
  confirmed holiday). Weekdays are never assumed open.

## Refresh cadence
- Refresh when NSE publishes a holiday or special-session circular, and in any case before the manifest is
  30 days old. Arming and `scripts/paper_readiness.py` refuse a manifest whose `availableAt` is older than
  30 days (stale). The shipped sample goes stale on 20 December 2026.
- Refreshing is a manual owner step; nothing downloads or scrapes the exchange.

## Licensing and terms
- Status: NOT CHECKED. Whether you may copy NSE holiday data into this file, and for what use, is for you
  to confirm from NSE's terms of use. The code records the source and a manifest fingerprint on each armed
  session but does not assess rights. Do not describe the manifest as exchange-verified.

## Behaviour
- Unlisted date: refuses to arm. Holiday (`null`): arming is allowed and ticks wait, with no fetch.
- Special sessions (weekend or non-09:15 open, or a close other than 15:15 or 15:30) are unsupported by
  the paper engine. They are accepted at arming (as before) and block processing with `UNSUPPORTED_SESSION`
  on each tick; `trading_calendar.validate(..., strict_sessions=True)` rejects them outright. This keeps a
  multi-day manifest armable when a future date is special. Decision recorded 24 Nov 2026.
- Square-off: the chosen account's square-off candle must complete strictly before the close the calendar
  gives for every listed open session (`PaperWorker.start`). The armed session records `squareOffAt`
  for today, plus `calendarVersion`, `calendarSource` and `calendarFingerprint`.
- Dates are judged in IST, not UTC.
