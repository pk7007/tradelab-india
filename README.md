# TradeLab India

### An Indian-market research and trading workspace

The home workspace now groups the product into **Intraday**, **Long-term**, and **Auto Trading**. Settings and advanced research remain available without filling the main navigation. See the [simple portal guide](docs/simple-portal.md). The previous control room is available at `/advanced`; existing paper and research records are preserved.

New paper accounts can explicitly opt into **Intraday v1**: cost-aware sizing, modeled stop/target exits, volume-participation limits and observed-candle square-off. Legacy accounts keep their original behaviour. An explicitly armed completed-Kite-candle paper worker is now available; fills remain modeled and live dispatch stays locked. See [continuous paper setup](docs/continuous-paper-worker.md). See [intraday readiness and operations](docs/intraday-readiness.md).

TradeLab brings market data, strategy evaluation, risk planning and reviewed manual orders into a local browser application. Built with Python, JavaScript and Zerodha Kite Connect, it makes the assumptions behind a trading idea visible—from the data used to the costs and risks modeled.

**Status:** research and durable paper-trading prototype. Manual and automated live dispatch are locked pending integrated broker funding, ownership, risk and exit validation. Real-market profitability is unproven.

Latest full algorithm audit: [complete audit and pending steps](docs/complete-algorithm-audit-2026-11-20.md).

Latest review: [20 November gap audit](docs/gap-audit-2026-11-20.md) and [external-source procurement plan](docs/external-source-plan.md). The local assessment is 5.45/10; live operation remains materially incomplete; the new paper worker has offline regression coverage but no sustained authenticated forward-run evidence. The audit fixes order-conflict handling, reservation integrity, revision/cursor races and stale frontend decisions. NSE RSS context is implemented; Moneycontrol remains an offline mock adapter. No score represents a probability of profit.

[Get started](#quick-start) · [Features](#features) · [Evaluation](#strategy-evaluation) · [Roadmap](#roadmap) · [Documentation](#documentation)

## Features

- **Broker workspace:** Zerodha account overview, holdings, positions, order book and manual order review.
- **Market research:** private live charts, historical candle viewing and imported chart-setup scanning.
- **Reproducible evaluation:** CSV/JSON inputs, chronological validation, final holdout, matched buy-and-hold comparison and cost sensitivity.
- **Risk planning:** whole-share position sizing, exposure limits, remaining daily loss checks and explicit paper-order approvals.
- **Durable paper accounts:** imported-candle SMA replay with persisted fills, costs, duplicate protection and restart recovery. An opt-in fenced worker can poll completed Kite candles with explicit retention/calendar confirmation; credentials stay in memory.
- **Integrated news agent:** five-minute personal NSE/ET/Google RSS checks in Intraday research and paper-worker context, with per-source freshness, exact NSE company mapping and no headline-triggered orders. See [news agent](docs/news-agent.md).
- **Source-aware analysis:** imported watchlist news, publication/availability timestamps, deduplication and structured earnings comparisons.
- **Automation foundation:** versioned strategy drafts, a SQLite intent ledger and audit history. Automated live dispatch is not connected.
- **Recovery and research evidence:** durable manual intent reconciliation, mock shared cash/share reservations, and a local experiment registry that flags repeated holdout viewing. These are separate components; they do not constitute a unified live execution system.

## Workflow

**Try the feed-recovery milestone (fixture replay only):** From the repository root run `python scripts/fixture_recovery.py`. This starts two successive local app processes against one temporary synthetic paper ledger, interrupts a pending signal, reconnects with overlapping bars and checks the dashboard balances against the full fill journal. It does not access a broker or enable live execution. [Results and scope](docs/paper-feed-recovery.md).

**Research → Evaluate → Plan risk → Review an order**

Inspect permitted data, test a rule against a benchmark, review its assumptions, and size a hypothetical position. Paper approval and manually reviewed broker orders are separate workflows. Authenticated forward paper verification remains the next acceptance stage.

## Quick start

For a standalone Indian-market RSS reader with watchlist filtering and continuous polling, see the [news agent guide](docs/news-agent.md). Run `python news_agent.py --once` or `python news_agent.py --watch`. The same reader is also connected to dashboard research and paper-worker context.

Requires **Python 3.10+**. Node.js is used for JavaScript development checks.

```powershell
git clone https://github.com/pk7007/tradelab-india.git
cd tradelab-india
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open **http://127.0.0.1:8765**. Keep the server terminal running. The synthetic demo and permitted-file evaluation work without a broker account.

### Connect Zerodha (optional)

1. Register `http://127.0.0.1:8765/auth/kite/callback` as your Kite Connect app's redirect URL.
2. Copy `.env.example` to `.env` if it does not already exist, then enter your API key and secret locally.
3. Restart TradeLab and select **Connect Zerodha**. Complete authentication on the broker's own page.

Live orders are blocked by a server-side readiness gate as well as configuration. Setting `TRADELAB_ENABLE_LIVE_ORDERS=true` cannot unlock dispatch in this release. Read-only broker functions remain available after authentication. See the [current repair report and operating runbook](docs/system-repair-2026-11-18.md) before changing settings.

A Kite Connect key connects to the broker; it is not an AI-model credential. No AI provider is connected, and no model controls funds or risk limits.

## Strategy evaluation

Open **http://127.0.0.1:8765/trader-evaluate** and select **Run synthetic demo**, or import permitted candles for one stock.

The fixed SMA(5/20) rule uses completed closes for next-open decisions. Two chronological validation windows precede a final holdout. Strategy and buy-and-hold use the same starting cash, whole shares, modeled fees and slippage. A second holdout run doubles fees and slippage.

```powershell
.\.venv\Scripts\python.exe evaluation.py --demo
```

See [evaluation inputs](docs/evaluation-data.md) for the CSV/JSON format and command-line import instructions.

### Example results

The [reproducible demo report](docs/evaluation-demo.json) uses **invented prices**, with 300 bars and a 60-bar final holdout. It does not represent Indian stock-market performance.

| Final holdout measure | SMA strategy | Buy-and-hold |
| --- | ---: | ---: |
| Return after modeled costs | 1.08% | 2.32% |
| Maximum bar-close drawdown | 4.66% | 5.75% |
| Completed round trips | 2 | 1 |
| Return with doubled fees and slippage | 0.47% | 2.01% |

The strategy underperformed the benchmark in this fixture. Two trades do not establish a dependable advantage. Software tests verify behavior, not investment returns.

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

## Development checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/account.test.js
node tests/order-review.test.js
node tests/research-display.test.js
node --check web/trader.js
node --check web/evaluation.js
```

The [current repair report](docs/system-repair-2026-11-18.md) records the latest test results and browser checks. The [checks workflow](.github/workflows/checks.yml) runs Python and JavaScript regressions plus HTTP fixture recovery. These tests do not establish production readiness or profitability.

Open `/trader-paper` for the separate persistent paper-account workflow. Creation requires your financial assumptions and permission to retain imported candles locally. Start enables ingestion; pause preserves pending intents; stop cancels unfilled local intents without closing positions. Restart pauses accounts. The original session-based paper approval tool remains separate.

Use **Pause new entries** to keep running exit processing, or **Request simulated close** to queue an exit at the next accepted candle open. The latter pauses new entries and leaves exposure visible until a simulated fill. **Pause all ingestion** freezes exits too. These controls never act on broker positions.

Evaluations run through the portal retain report summaries, settings and dataset/holdout fingerprints in a private SQLite registry, including unsuccessful results. Reusing a holdout is flagged even when costs change. Raw evaluation candles are not saved by this registry; paper imports have their own explicit retention permission. CLI-only evaluations are not registered.

## Repository map

| Path | Purpose |
| --- | --- |
| `app.py` | Local HTTP server, sessions and broker request handling |
| `market_data.py` | Historical jobs and private streaming |
| `trader_suite.py` | Scanner, planning, risk and imported news/filings |
| `evaluation.py` | Fixed-rule evaluation and deterministic demo |
| `research.py`, `validation_lab.py` | Research utilities and synthetic stress simulation |
| `automation.py` | Strategy configuration, intent ledger and coordinator state |
| `execution_journal.py` | Durable manual intent correlation and broker-evidence checks |
| `strategy_contract.py`, `experiment_registry.py` | Shared signal/fill assumptions and research result provenance |
| `web/` | Browser interface |
| `tests/` | Offline regression tests |
| `docs/` | Setup, feature contracts, evidence and limitations |

## Documentation

| Guide | Contents |
| --- | --- |
| [Market-data setup](docs/market-data-setup.md) | Broker configuration, charts, historical jobs and data rights |
| [Evaluation inputs](docs/evaluation-data.md) | Candle formats, timestamps, provenance and assumptions |
| [Trader suite](docs/trader-suite.md) | Tool behavior and implementation boundaries |
| [Automation operations](docs/automation-operations.md) | Current coordinator behavior and unavailable live operations |
| [Research implementation](docs/research-implementation.md) | Research methods and remaining validation work |
| [News sources](docs/news-source-research.md) | Indian-market source discovery and research prompt |
| [Architecture](docs/architecture.md) | Application structure and design context |
| [Current repair report](docs/system-repair-2026-11-18.md) | Gap register, tests, recovery and remaining live blockers |
| [Capability map](docs/feature-status.md) | Route-by-route implementation status |

## Safety and scope

TradeLab is a local, single-user prototype. It binds to loopback and keeps broker access tokens in server memory; restarting clears login sessions. Do not expose it to the public internet.

Keep credentials, account records and licensed market exports out of Git. No real market dataset is bundled. Imports require permission for the intended use; public accessibility does not imply redistribution rights.

Historical simulations assume fills and costs. Liquidity, taxes, corporate actions, gaps and outages can materially change real outcomes. Five-minute evaluation may hold overnight and is not an intraday square-off simulation. News feeds and automatic filing ingestion remain disconnected. The original paper-approval tool has a session-only book; `/trader-paper` uses a separate durable ledger with hypothetical fills.

This project does not promise returns or loss-free trading and makes no investment-adviser or regulatory-approval claim. Its tests verify software behavior, not profitability or production readiness.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing changes. Include reproducible steps and appropriate tests for calculation or execution changes. Report security issues through the guidance in [SECURITY.md](SECURITY.md), and never include credentials or account data in an issue.
