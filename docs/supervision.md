# Supervision, token loss and recovery

What the paper system does when the broker login is lost or the process dies. Paper only: nothing here
places an order, and a failure of the incident inbox never stops exits, square-off, exposure reporting or
reconciliation.

## Token loss or failed selection (running process)
- Selection stops, new entries are paused (`pause_entries`), the worker stops, and the state is `blocked`.
- Incidents (local inbox, `operational_alerts.py`): `paper:token-loss` (critical if a position is open,
  otherwise a warning) and `paper:exposed` (critical while any modelled position or pending order exists).
- An open position **cannot close without accepted candles**, so it stays open and is flagged `EXPOSED` in
  `status()['exposure']`, with its configured square-off time and ledger reconciliation. No fill is
  invented: `supervision.phantom_fills()` finds any ledger fill with no accepted candle behind it.
- You log in and re-arm recovery through the normal Start. That resolves `paper:token-loss`;
  `paper:exposed` stays until the ledger is flat.

## Restart or crash
- A fresh process is always disarmed, the engine pauses running accounts and invalidates unused entry
  reviews, and the ledger reconciles. At startup the app records `paper:exposed` if exposure remains.
- Nothing resumes by itself: it needs your Zerodha login and an explicit re-arm.

## Watchdog on Windows
- `scripts/watch_service.py` (separate process) polls `/api/service-health`, writes the same inbox and raises
  `app:unreachable`. It detects and alerts; it does not restart the app. Restarting the process (Task
  Scheduler, a console window, or by hand) is an owner action, and a restart always comes back disarmed.
- Creating a scheduled task or any persistent system configuration needs your approval. Sleep, the lock
  screen and the OneDrive folder path can interrupt a long-running process; keep the machine awake and the
  project outside a syncing folder if you rely on it.
- Alerts are local (inbox plus on-screen). Email, Telegram or other messages need your separate approval.

## Limits
- `scripts/fixture_recovery.py` is a test replay, not production recovery.
- The loopback HTTP restart tests are UNVERIFIED where Windows blocks local sockets (WinError 10013).
- Idle expiry of the browser session (1800 s) does not revoke the selector's market-data grant, which ends
  at the calendar date change or explicit logout.
