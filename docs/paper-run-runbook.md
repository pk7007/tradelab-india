# Owner runbook: one supervised paper session on Zerodha Kite

This runs the continuous paper worker (`paper_worker.py`, `worker_runtime.py`) for one session. It models fills from completed five-minute candles that Kite returns. **No real order is ever placed:** `LIVE_EXECUTION_READY = False` is a hard-coded constant in `app.py`, and `TRADELAB_ENABLE_LIVE_ORDERS=true` alone cannot change it. The worker has no order method.

## Who can do what

Only you can do these steps. An agent in a cloud session cannot do any of them, because it cannot log in to Zerodha, holds no Kite credentials, and has no route to your computer's loopback app:

- Put your Kite API key and secret in `.env`.
- Click **Connect Zerodha** and sign in (and any 2FA).
- Confirm your provider data-retention rights and set `KITE_DATA_STORAGE_APPROVED=true`.
- Confirm the session calendar and arm the worker.
- Watch the session and stop it.

Run everything on your own computer, from the repository root, in the project virtual environment.

## 1. Preflight (offline, safe to repeat)

```
python scripts/paper_readiness.py          # add --json for machine output
python scripts/paper_readiness.py --calendar docs/infy-paper-calendar-2026-11-20.json
```

Stop the app first (Ctrl+C) so the ledger copy is consistent: the check copies the database and its `-wal` file but not `-shm`, which SQLite rebuilds from the `-wal`. It makes no network call and prints no secret values (variable names only). With `--json` the output is `{generatedAt, istDate, ok, counts: {FAIL, BLOCKED, PASS}, checks: [{id, title, status, detail, ownerAction}]}` (also in the script docstring; `scripts/project_report.py` reads it). It reads a temporary copy of your ledger, never the original. Exit code is 1 only if a check says FAIL (for example `kiteconnect` not installed, a corrupt ledger, an invalid saved square-off, a failing fixture replay). BLOCKED lines are normal before you have logged in; each states your action. Fix every FAIL first (`python -m pip install -r requirements.txt`).

## 2. Configure `.env`

Copy `.env.example` to `.env` (git-ignored). Set `KITE_API_KEY`, `KITE_API_SECRET`, and keep `KITE_REDIRECT_URL=http://127.0.0.1:8765/auth/kite/callback` registered in your Kite developer console. Leave `TRADELAB_ENABLE_LIVE_ORDERS=false`. Optional private paths: `TRADELAB_PAPER_DB`, `TRADELAB_DATA_DIR` (see `.env.example`; defaults are under `%LOCALAPPDATA%\TradeLabIndia`).

Set `KITE_DATA_STORAGE_APPROVED=true` only after you have confirmed your rights to retain Kite candles (see `docs/market-data-setup.md`). While it is not `true`, `app.py` refuses `POST /api/paper-worker/start` and the automatic-selection start, and `market_data.py` refuses saving CSV history. The preflight reports this as BLOCKED.

## 3. Start the app and connect Zerodha

1. `python app.py`, then open http://127.0.0.1:8765/ (host and port come from `APP_HOST`, `APP_PORT`). A fresh process starts with the worker disarmed.
2. Click **Connect Zerodha** (top right of the Auto Trading page), sign in yourself. You return via `/auth/kite/callback`. Broker tokens are kept in memory only, so a restart means reconnecting. Local sessions idle out after 30 minutes (`SESSION_IDLE_SECONDS`), and the worker then refuses to continue until you reconnect and re-arm.
3. Confirm `GET /api/status` (or Settings) shows connected and `liveExecutionReady: false`.

## 4. Create the paper account

Open **Settings -> Paper imports & account setup** (`/trader-paper`). Create a new account: strategy **Intraday v1**, source **imported**, the exact NSE symbol, your capital, loss, exposure, cost and slippage assumptions, an entry cutoff (the reference schedule in `docs/paper-supervision-schedule.md` uses 14:30) and a square-off (15:05 there). `intraday_contract.py` requires entry cutoff before square-off, both on 5-minute IST boundaries, square-off no later than 15:25. The worker also refuses arming unless the square-off bar completes strictly before the session close. The account must be new and empty; an existing replay account cannot be attached (`paper_worker.py`). Re-run the preflight: **Session / square-off configuration** should now PASS.

## 5. Arm the worker for one session

On the Auto Trading page open **Settings -> Continuous paper worker · setup & health** (`web/portal.html`):

1. Select the account in the account picker.
2. Enter the exact NSE symbol and its verified positive Kite instrument token. The server re-checks the mapping against the instrument master.
3. Paste an attributed session-calendar JSON (`exchange` NSE, `segment` EQ, an https `source`, `version`, `availableAt`, explicit dates with timezone-aware `open`/`close`, `null` for confirmed holidays). The manifest must list every session date you want to run, **including today**: `PaperWorker.start` refuses to arm otherwise, and unlisted dates block processing. A starting point is `docs/infy-paper-calendar-2026-11-20.json`, which lists 20 to 27 November 2026 (24 November is `null`, a holiday); edit it to cover your dates. Confirming it is your own attestation, not exchange verification.
4. Tick the retention checkbox and the calendar checkbox, then **Start continuous paper worker**.

Automatic selection must be off (the server says "Stop automatic selection before starting the fixed-symbol worker"). Arming begins at the current five-minute boundary: earlier bars only warm up signals and create no entries. Backfill is bounded to seven days and 1,000 candles (`docs/continuous-paper-worker.md`).

## 6. What to watch

In the worker panel, **Refresh worker health** (`GET /api/paper-worker`): state, heartbeat, lease until, latest accepted candle, last failure, news context. A heartbeat alone does not prove fresh data; confirm the latest accepted candle advances every five minutes. Watch the account metrics (shares, stop and target, daily loss used, pending order). `GET /api/desk` and `/api/operations` show agent and storage health. Expect a state other than running when the calendar marks the day closed, the broker session idles, the login changes, or a fault occurs. Faulted or restarted runs need your inspection and an explicit re-arm.

News context is informational and never changes entries, exits or limits.

## 7. Stop

- **Stop worker** (`POST /api/paper-worker/stop`) pauses processing. It does not close shares or send an order. Pending exits need further accepted candles, so prefer to stay armed through the square-off bar (15:05 bar completes 15:10) and the final exposure check.
- **Pause new entries** (account controls) keeps modeled exits running without new entries.
- Ctrl+C in the terminal stops the app. Any open modeled position stays in the ledger; restart, reconnect and review before re-arming. Never edit balances to clear a mismatch.

## 8. Export session evidence

There is no one-click export. Capture, after the session:

- Worker panel health text and `GET /api/paper-worker` output.
- Account metrics and event history on `/trader-paper`, plus its **Verify balances from fills** button (`POST /api/trader/paper-reconcile`; it shows "Matches ledger" or "MISMATCH"), which must report the ledger matches.
- Settings -> **Back up current databases** (`POST /api/operations/backup`) and **Check an isolated restore**; backups are written under the private data folder, outside Git.
- The preflight JSON from step 1 (`--json`) as a record of configuration.

Keep these files private. Broker candles, ledgers and logs must not be committed or redistributed.

## 9. Reading the result

Success means: the worker armed; accepted candles advanced on schedule; no unexplained fault; no position left open after square-off; reconcile matches; no order was sent anywhere; the preflight showed live execution locked throughout.

It does **not** prove: profitability or an edge, realistic fills (fills use the paper model; slippage and liquidity are assumed), behaviour across market regimes, or readiness for live trading. One session is a single sample. Any P&L it shows is a modeled number, not evidence of future results, and engineering readiness scores are not probabilities of profit. Live-money readiness stays closed (`docs/intraday-readiness.md`, `docs/continuous-paper-worker.md`).
