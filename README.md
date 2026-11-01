# TradeLab India — Automation workspace

TradeLab India is a personal, local-first Indian market workspace. Its first broker connector is Zerodha Kite Connect. The app keeps the broker API secret and access token on the local server and requires a separate review before sending a live order.

## Current automation status

The redesigned control room includes versioned strategy drafts, explicit financial-limit fields, a durable SQLite intent ledger and an audit timeline. Automated live dispatch, cancellations and flattening remain unavailable. See [operator guide and exact implementation limits](docs/automation-operations.md). The UI does not claim that a saved strategy is approved or running.

## Trading and risk disclosure

Live order support is disabled by default. If explicitly enabled, orders are sent to the connected Zerodha account and can result in financial loss. The app is not investment advice, does not promise income, does not generate buy/sell signals, and does not claim that any strategy is profitable. No SEBI/NSE approval or compliance is claimed. Use the broker's own login page for authentication; never enter broker passwords, OTPs, or UPI PINs into this app.

## Product direction

- Zerodha account profile, holdings, positions, and order book through Kite Connect.
- Manual order entry with a review step and explicit live-order confirmation.
- Historical replay and simulation remain planned; historical market data is not bundled.
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

1. **Frame the product:** clarify problem, non-goals, risks, and the manual-only broker boundary.
2. **Research users and alternatives:** review OpenAlgo and related projects, interview target users, and distinguish evidence from assumptions.
3. **Prototype:** test a clickable flow with synthetic data for task completion and comprehension.
4. **Simulation MVP:** replay, hypothetical plans, costs, journal, source labels, and reproducible runs.
5. **Verify data and calculations:** use only permitted data; check timestamps, gaps, duplicates, corporate actions, look-ahead leakage, and calculations.
6. **Polish the portfolio:** accessibility, privacy, failure states, honest case study, limitations, and demo instructions.
7. **Optional future commercial review:** no live trading in this repository's default roadmap. Any proposal requires separate qualified legal/compliance review, broker authorization, security review, operational readiness, and explicit product approval.

## Known limitations

- No market data is bundled. Strategy research currently uses synthetic prices only; live automated strategies and historical replay remain unimplemented.
- No interviews, usability findings, or competitor claims have been validated yet.
- Digest sources and automated reuse permissions are pending review; the workflow is gated off by default.
- This project is not a broker, investment adviser, exchange, or regulator-approved system.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and the [compliance review checklist](docs/compliance-review-needed.md). Do not add credentials, personal financial data, or private customer information.

## Research implementation

Strategy lab now includes descriptive price rankings and a synthetic execution stress lab. See [research status, sources, and limitations](docs/research-implementation.md) and [test results](docs/research-test-results.md). These features are not validated trading recommendations or live automation.
