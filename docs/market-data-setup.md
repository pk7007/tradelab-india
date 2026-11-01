# Connect market-data workspace

## Status

The application includes NSE equity search, historical-candle viewing, a broker WebSocket last-price chart, and an educational strategy simulator using synthetic prices. No live strategy is configured. No automatic order loop exists.

Install the pinned official SDK in a project environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Stop the previous TradeLab process first if port 8765 is occupied. Reconnect Zerodha after a server restart; broker tokens remain in memory only. Keep the existing redirect URL `http://127.0.0.1:8765/auth/kite/callback` registered in the developer console.

## History

Open **Market data**. Search current NSE equities and enter up to 25 exact symbols. The starting basket (RELIANCE, INFY, TCS, HDFCBANK, ICICIBANK) is an illustrative research scope, not a recommendation or representative market sample. Presets select five years of daily candles or 90 days of five-minute candles; dates and symbols are editable.

Requests use 30-calendar-day windows, serialized at no more than 2.5 historical requests per second. The UI reports progress, empty windows, cancellation, and failures. Invalid candles stop the job; missing periods are never fabricated. Completed symbols remain available after a partial failure. Restarting the server loses in-memory jobs. A new request replaces the previous completed request for that browser session. The viewer displays the most recent 200 candles; a request is limited to 200,000 candles per instrument and 400,000 overall.

“All history” is not guaranteed: coverage varies, current instrument lists omit expired contracts, and continuous historical contracts have separate restrictions. This first screen supports current NSE equities only. Corporate-action adjustments and survivorship bias are not independently verified. See [Kite historical API](https://kite.trade/docs/connect/v3/historical/) and [rate limits](https://kite.trade/docs/connect/v3/exceptions/).

## Storage rights and location

Permanent storage is disabled by default. The [Kite terms](https://kite.trade/terms/) restrict permanent copying and redistribution unless expressly permitted. Paid API access is not treated here as blanket permission to archive or publish data. Obtain confirmation of the rights applicable to your personal historical-data use before setting `KITE_DATA_STORAGE_APPROVED=true` in `.env` and restarting.

With that permission configured, select **Save CSV files to this computer** before loading history. CSV and JSON provenance records go to `%LOCALAPPDATA%\TradeLabIndia\market-data\<request-id>` on Windows, outside the OneDrive workspace. `TRADELAB_DATA_DIR` may override this location; choose a folder you control and account for any cloud-sync settings. No credentials are included in exports. Source, symbol, instrument token, interval, requested dates, timezone, download timestamp, row count, and adjustment limitations accompany each file. Empty CSVs represent no returned data, not a valid complete market archive.

Broker data must not be committed to GitHub without separate redistribution permission. Source code can be hosted privately; `.env`, market-data files, logs, virtual environments, and local publication-review output are excluded from Git.

## Live chart

Enter a current NSE equity symbol and click **Start stream**. One private stream is available at a time. The official KiteTicker SDK receives full WebSocket ticks on the server. The browser reads a bounded snapshot once per second; access tokens never enter browser code. The chart retains the latest 1,000 last-price ticks in memory and marks receipt age. It is a line chart, not a historical candle or tick archive. Weekends and closed markets may produce no new ticks. Reconnect failures are visible. Stop explicitly, or leave the tab idle for 90 seconds to close the upstream connection.

## Strategy research

The strategy lab runs a deterministic synthetic moving-average example with editable windows, per-fill fees, and slippage. Signals use completed bars and execute at the following open. Results disclose open positions at the end, modeled fees, drawdown, and simplified assumptions. This demonstration is not evidence of profitability, does not consume Kite live data, and cannot place orders.

Live automation remains pending exact entry/exit rules, eligible instruments, position size, daily loss limits, stale-feed handling, order reconciliation, shutdown behavior, and broker/exchange requirements. No trading rule or money limit will be inferred from “all strategies.”

## Checks

```powershell
python -m unittest discover -s tests -v
python -m py_compile app.py market_data.py
node --check web/app.js
node --check web/market.js
```

These checks use synthetic fixtures and mocked broker behavior; they do not authenticate or submit orders. Real history and streaming require the SDK installation and your browser's authenticated Kite session.
