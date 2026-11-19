# Continuous paper worker

Implemented 20 November 2026. This is completed-candle paper observation, not broker execution or a validated trading edge. Offline verification: 238 Python tests and six JavaScript regression scripts passed. No authenticated forward run was performed. The separate HTTP process-restart fixture could not run in this environment because Windows denied loopback socket access (WinError 10013); this is not a passing recovery result.

## Start deliberately

1. Run the updated backend using the existing local launch instructions. An already-running process needs a restart to load backend changes.
2. Connect Zerodha locally. Keep credentials in the local environment; never commit them.
3. Confirm provider retention rights before setting KITE_DATA_STORAGE_APPROVED=true. The application also requires an explicit retention checkbox.
4. Create a new imported Intraday v1 paper account with the intended symbol and limits. Old replay accounts cannot attach to this worker. Portal settings do not rewrite an existing account's limits.
5. In Auto Trading, select that account and expand Continuous paper worker. Enter the exact NSE symbol and current broker instrument token. The server checks the mapping.
6. Supply an attributed, versioned session-calendar manifest with explicit timezone-aware open/close values and confirmed holidays as null. Unknown dates block processing. Calendar confirmation is user attestation, not independent exchange verification. Special sessions are currently blocked.
7. Confirm the calendar and start. The server polls every 30 seconds, processes completed five-minute bars, and exposes heartbeat, accepted candle, lease, errors and news context. Keep the local broker session active. Restart, login changes, idle sessions or faults require inspection and explicit re-arming.

## Recovery boundaries

A durable SQLite owner/epoch lease fences ingestion at transaction start and completion. A competing or expired owner cannot commit. Worker-bound accounts reject manual candle ingestion, even while stopped. A fresh process starts disarmed. Broker credentials are held only in memory.

Past bars before the arm boundary warm up signals without new entries. Existing exits may still be modeled during catch-up. Receipt and decision timestamps are stored separately from bar timestamps; fills use the paper model and do not demonstrate executable live prices. Backfill is bounded to seven days and 1,000 candles. Stop pauses processing and preserves exposure; it does not liquidate shares or send an order. Pause entries is the control for continuing modeled exits without new entries.

## News agent

The dashboard adapter uses news_agent.py for NSE, ET and the fixed Google News query. A five-minute in-memory cache retains unchanged current items because the reader emits only new/changed items. Failed-source items are removed. Only identity hashes/timestamps persist in the news database; publisher text remains in memory. Personal-use source restrictions still apply.

Research and each worker provider fetch record eligible context available at receipt. Future, stale, older-than-24-hour and unmapped items are excluded from symbol-specific context. Only exact NSE company-name mappings qualify; editorial keyword matches never establish a verified symbol. Missing news is explicitly shown and does not disable modeled exits. News does not alter entry rules, risk limits or create orders. Moneycontrol stays disconnected pending real licensed endpoint credentials.

GET /api/news-agent returns source health and summaries; GET /api/paper-worker returns worker health. Start/stop require the existing local POST protections. POST /api/broker/snapshot performs bounded read-only reconciliation; its sequential responses are explicitly non-atomic and grant no execution authority.

## Remaining evidence

Sustained authenticated forward paper sessions, independent out-of-sample strategy evaluation, execution/slippage realism and unified broker cash/inventory/exit ownership remain open. The existing live gate remains locked. No engineering score is a probability of profit, and loss limits cannot guarantee a realized loss cap.
