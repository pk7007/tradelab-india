# TradeLab India

TradeLab India is a personal, local-first Indian market workspace. Its first broker connector is Zerodha Kite Connect. The app keeps the broker API secret and access token on the local server and requires a separate review before sending a live order.

**Current stage: research and manual trading prototype. Automated live execution is not implemented; profitability is unproven.** The direction is a personal trading workstation that researches opportunities, tests strategies and manages execution under explicit user controls.

## Feature status

| Area | Available today | Remaining boundary |
| --- | --- | --- |
| Zerodha workspace | Account, holdings, positions, order book and reviewed manual orders | Requires broker login; live orders disabled by default |
| Market data | Live charts and historical viewing | Relevant Kite entitlement required; retention needs permission |
| Chart scanner | Imported opening-range breakout, flag and bounce heuristics | Snapshot analysis; rules unvalidated |
| Strategy evaluation | CSV/JSON import, fixed SMA(5/20), separate validation and holdout periods | One stock per run; modeled fills and costs |
| Risk and sizing | Whole-share sizing, exposure limits and remaining daily loss checks | User-entered snapshots; stops cannot guarantee a maximum loss |
| Paper orders | Explicit approval, single-use drafts and aggregate reserved risk | Hypothetical fills; session book lost on restart |
| News and filings | Watchlist filtering, deduplication, availability cutoff and structured imports | Continuous feeds and automatic report extraction disconnected |
| Automation | Strategy drafts, durable intent ledger and audit history | No automated live dispatch, cancellation or flattening |

## Recorded demonstration

The [reproducible demo report](docs/evaluation-demo.json) uses **invented prices**, with 300 bars and a 60-bar final holdout. It does not represent Indian stock-market performance.

| Final holdout measure | SMA strategy | Buy-and-hold |
| --- | ---: | ---: |
| Return after modeled costs | 1.08% | 2.32% |
| Maximum bar-close drawdown | 4.66% | 5.75% |
| Completed round trips | 2 | 1 |
| Return with doubled fees and slippage | 0.47% | 2.01% |

The strategy underperformed the benchmark in this fixture. Two trades do not establish a dependable advantage. Software tests verify behavior, not investment returns.

## Evaluate a strategy

With the local app running, open [Strategy evaluation](http://127.0.0.1:8765/trader-evaluate). Run the synthetic demo or supply a permitted, single-stock OHLCV file and your own assumptions. The fixed moving-average rule and buy-and-hold pay the same modeled costs. The report separates the two validation windows from the final holdout and repeats the holdout with doubled fees and slippage. This screen requires no broker login.

Run the same deterministic demonstration offline: `python evaluation.py --demo`. For private data and the import format, see [evaluation inputs](docs/evaluation-data.md). The [recorded demo report](docs/evaluation-demo.json) contains only synthetic results.

## Current automation status

The redesigned control room includes versioned strategy drafts, explicit financial-limit fields, a durable SQLite intent ledger and an audit timeline. Automated live dispatch, cancellations and flattening remain unavailable. See [operator guide and exact implementation limits](docs/automation-operations.md). The UI does not claim that a saved strategy is approved or running.

## Trading and risk disclosure

Live order support is disabled by default. If explicitly enabled, orders are sent to the connected Zerodha account and can result in financial loss. Research signals and setup matches are unvalidated. The app is not investment advice, does not promise income, and does not claim that any strategy is profitable. No SEBI/NSE approval or compliance is claimed. Use the broker's own login page for authentication; never enter broker passwords, OTPs, or UPI PINs into this app.

## Product direction

- Zerodha account profile, holdings, positions, and order book through Kite Connect.
- Manual order entry with a review step and explicit live-order confirmation.
- Historical replay and simulation on permitted imports; historical market data is not bundled.
- Historical NSE equity candle viewing, editable date ranges, progress reporting, and permission-gated local CSV storage.
- A private live-price chart backed by Kite WebSockets; the browser refreshes its view once per second.
- A synthetic strategy research example with explicit fees, slippage, and next-bar execution; no automated live strategy is configured.
- A weekly digest of public-source updates that links to originals and avoids advice or copied articles.

See [the product brief](docs/product-brief.md) and [the roadmap](docs/decision-log.md).

## Project roles

For a solo portfolio project, these are responsibilities, not claims of a staffed or certified team:

| Responsibility | Focus |
| --- | --- |
| Product Manager | User problem, scope, priorities, research synthesis, success measures |
| Product Designer | Journeys, prototypes, accessibility, interface clarity |
| Backend Engineer | APIs, persistence, simulation orchestration, audit history |
| Frontend Engineer | Replay and review workflows, responsive UI, accessible chart summaries |
| Data Engineer | Licensed data ingestion, timestamps, quality checks, provenance |
| Quant Researcher | Simulation assumptions, metric definitions, bias review; no profit guarantees |
| QA/Reliability Engineer | Calculation correctness, failure states, reproducibility, monitoring |
| Security Engineer | Threat model, secrets handling, access control, privacy |
| Compliance Reviewer | Current applicable rules and product claims, reviewed with qualified expertise |

## Local setup

Requires Python 3.10 or newer and the pinned official Kite Connect SDK. Install it in the project environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

1. Create a Zerodha Kite Connect app and register `http://127.0.0.1:8765/auth/kite/callback` as its redirect URL.
2. Copy `.env.example` to `.env` and fill in your own API key and secret. Keep `.env` private; it is gitignored.
3. Start the app with `.\.venv\Scripts\python.exe app.py` and open `http://127.0.0.1:8765`.
4. Choose **Connect Zerodha**. Authentication happens on Zerodha; this app never asks for your broker password, TOTP, or PIN.
5. Live order submission stays disabled unless you deliberately set `TRADELAB_ENABLE_LIVE_ORDERS=true` in `.env` and restart the app. Check Zerodha and current exchange/API requirements, including any static IP registration rules, before enabling it.

The server binds to loopback (`127.0.0.1`) and keeps access tokens in memory only. This is a local single-user prototype, not safe to expose to the public internet or deploy for other users. Do not share your `.env` file or browser session.

See [market-data setup](docs/market-data-setup.md) for historical viewing, live charts, data rights, local storage, and the synthetic strategy lab. Permanent market-data storage is locked until rights are confirmed; no broker data is published to GitHub.

## Data provenance and licensing

Do not commit licensed market data unless its terms explicitly permit redistribution. Record provider, instrument, interval, timezone, adjustment method, retrieval date, permitted use, and attribution for any future data. Treat public availability as distinct from permission to reuse. The source registry in `data/digest-sources.json` is an unapproved research inventory; all entries are disabled until their terms and endpoint behavior are reviewed.

## Weekly public-source digest

The planned GitHub Actions workflow is manually triggerable and has a weekly schedule gated by the repository variable `ENABLE_WEEKLY_DIGEST=true`. Manual runs require `confirm_sources_reviewed=true`. Keep both gates closed until the source list and repository are reviewed. GitHub schedule times use UTC: Monday 03:30 UTC is approximately Monday 09:00 India Standard Time (UTC+05:30). Scheduled events may be delayed by GitHub. The workflow writes `updates/YYYY-MM-DD.md` and refreshes `updates/README.md`; it does not publish to external services. It uses feed metadata only, short excerpts only where permitted, canonical-link deduplication, and visible failure reporting. It does not generate market advice, predictions, or trading signals.

## Roadmap

These milestones are planned capabilities, not shipped features or promised release dates.

| Stage | Deliverable | Evidence needed to advance |
| --- | --- | --- |
| 1. Reliable data | Permitted historical datasets and news/earnings feeds; gap, timestamp and corporate-action checks | Documented provenance, usable rights and reproducible quality reports |
| 2. Strategy research | Comparisons across stocks, sectors and market conditions | Results after realistic costs on untouched periods; unsuccessful runs retained |
| 3. Forward paper trading | Evaluate strategies as prices arrive; durable signal, fill, rejection and loss logs | Observed behavior matches the strategy contract; failures recover correctly |
| 4. Controlled live automation | Broker reconciliation, duplicate-order prevention, exposure/loss limits, restart recovery and kill switch | Reviewed operational tests, applicable broker requirements and explicit user configuration |
| 5. Unified control room | Research, news, positions, strategy health and alerts in one dashboard | Clear states, understandable explanations and tested workflows |

**Next milestone:** trustworthy real-data evaluation and forward paper trading. Profitability is a question to measure, not a feature to promise. Identifying a weak strategy before risking money is a useful outcome.

## Known limitations

- No real market data is bundled. Permitted historical imports and replay are supported, but the recorded evaluation uses synthetic prices. Real-market profitability remains unproven.
- Five-minute strategy evaluation may hold positions overnight; it is not a same-day square-off simulation. Liquidity, tax schedules and corporate actions require further validation.
- Automated live strategies and forward paper execution remain unimplemented.
- No interviews, usability findings, or competitor claims have been validated yet.
- Digest sources and automated reuse permissions are pending review; the workflow is gated off by default.
- This project is not a broker, investment adviser, exchange, or regulator-approved system.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and the [compliance review checklist](docs/compliance-review-needed.md). Do not add credentials, personal financial data, or private customer information.

## Development checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/account.test.js
node --check web/trader.js
node --check web/evaluation.js
```

Latest local verification: **80 Python tests passed on 5 November 2026**. The [checks workflow](.github/workflows/checks.yml) runs offline regression and syntax checks. Live broker execution and production reliability are not established by those tests.

## Repository map

| Path | Purpose |
| --- | --- |
| `app.py` | Local HTTP server, sessions and broker request handling |
| `market_data.py` | Historical jobs and private streaming |
| `trader_suite.py` | Scanner, planning, risk and imported news/filings |
| `evaluation.py` | Fixed-rule evaluation and deterministic demo |
| `research.py`, `validation_lab.py` | Research utilities and synthetic stress simulation |
| `automation.py` | Strategy configuration, intent ledger and coordinator state |
| `web/` | Browser interface |
| `tests/` | Offline regression tests |
| `docs/` | Setup, feature contracts, evidence and limitations |

For source discovery, see [Indian news sources and reusable research prompt](docs/news-source-research.md).

## Research implementation

Strategy lab now includes descriptive price rankings and a synthetic execution stress lab. See [research status, sources, and limitations](docs/research-implementation.md) and [test results](docs/research-test-results.md). These features are not validated trading recommendations or live automation.

## Trader suite

Open [Chart Scanner](http://127.0.0.1:8765/trader-scanner) for the eleven import-first workspaces. Includes setup heuristics, manual-source news and earnings/disclosure analysis, risk and sizing tools, 10,000-path scenario sampling, explicit paper-order approvals, and open-page alerts. See [feature contracts and limitations](docs/trader-suite.md). This is not a connected autonomous live bot; provider feeds and live automation remain incomplete.
