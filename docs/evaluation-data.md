# Historical data for strategy evaluation

The working tree and TradeLab's default local market-data export directory contained no historical equity candle files when checked on 4 November 2026. The data directory in the repository contains a news-source registry. The test fixtures and seeded simulations can verify execution logic. They cannot establish how much the strategy would have earned in the Indian market.

## Obtain a private sample

Use an export you have permission to use for personal historical strategy testing. Record the provider, product, instrument and exchange, interval, timezone, coverage dates, retrieval date, adjustment method, and scope of permitted local retention alongside the file. Keep the original in a private folder outside this OneDrive checkout. Share a filesystem path with the person running the evaluation. They do not need your trading password or API secret.

* **Zerodha.** The Kite terms restrict permanent copies of returned content and use of the APIs or live data in virtual trading applications. If using a Kite export, identify the permission covering this particular historical evaluation and any local retention. TradeLab's export setting records your choice and conveys no additional rights. [Kite Connect terms, sections 2 and 4](https://kite.trade/terms/)
* **Another personal provider.** Groww documents a historical-candle endpoint specifically for backtesting, including NSE cash equities. It requires an authenticated subscription or entitlement. A subscriber should check the provider's applicable export and retention conditions before supplying a file. TradeLab does not require that you purchase another subscription. [Groww historical backtesting API](https://groww.in/trade-api/docs/curl/backtesting)
* **Exchange or vendor supply.** An NSE market-data agreement specifies intended use and distribution rights. Check the agreement for a licensed vendor export before placing raw candles in a shared directory or GitHub repository. [NSE Data Sharing and Usage Policy](https://www.nseindia.com/static/market-data/nse-data-policy)

## Before interpreting a result

At [Strategy evaluation](http://127.0.0.1:8765/trader-evaluate), choose your CSV or JSON file, its interval, an ISO cutoff including its timezone, starting cash, estimated fees and slippage. CSV expects `date,open,high,low,close,volume`; TradeLab's optional `oi` column is ignored. For CSV or an unkeyed JSON array, enter the symbol. Keyed JSON uses `{"SYMBOL":[...bars...]}`. Use completed daily or five-minute candles in chronological order. Five-minute results may include overnight positions and are **not** a same-day square-off simulation.

To run without a browser, use `python evaluation.py --input PATH`. Supply a JSON request with `candles` (one symbol mapped to its bar array), `interval` (`day` or `5minute`), `asOf` (with timezone offset), `capital`, `costBps`, `slippageBps`, `source: "imported"` and `permitted: true`. The run fingerprints the completed bars and assumptions. The output contains summary statistics, not the original prices.

Neither cost input is a verified historical charge schedule; use the applicable bills and product charges when choosing assumptions. [Zerodha's published charge categories](https://zerodha.com/charges/) distinguish brokerage, statutory charges and other costs.

1. Pick the instrument, trading rule, costs and test dates before inspecting the holdout returns. Record unsuccessful runs alongside successful ones. Selecting today's biggest gainers or surviving stocks retrospectively changes the question being tested.
2. Verify the exchange timezone, bar interval and price units. Cross-check the dates against the exchange calendar and investigate missing bars, duplicate timestamps, splits, bonuses and dividends. Preserve missingness and describe how adjustments were applied to each OHLC field.
3. Keep the source version fixed. Save a SHA-256 hash alongside the evaluation settings and the resulting holdout dates, using `Get-FileHash -Algorithm SHA256 -LiteralPath $candleFile` in PowerShell with `$candleFile` pointing to the private source file.
4. Compare the strategy with a benchmark over the same dates. Review net return, drawdown, trade count, costs and the effect of worse fills. Results from one instrument or period provide evidence only for that particular test.
