# Development setup and verification

This guide is for a **local, single-user research prototype**. Do not expose TradeLab on a public network. The synthetic demo and offline tests do not require a Zerodha account, real market data, an AI API key or a paid service.

## Prerequisites

- **Python 3.10+** with `venv` and `pip`
- **Node.js** for JavaScript syntax and regression checks; the [CI workflow](../.github/workflows/checks.yml) uses Node 22
- Git, a terminal, and a browser

Only the [pinned Python dependency](../requirements.txt) is installed by `pip install -r requirements.txt`. Optional external providers require separate credentials, permissions and review.

## Clone and run — Windows PowerShell

```powershell
git clone https://github.com/pk7007/tradelab-india.git
cd tradelab-india
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

## Clone and run — macOS / Linux

```bash
git clone https://github.com/pk7007/tradelab-india.git
cd tradelab-india
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

Open **http://127.0.0.1:8765/** and keep the terminal open. A server start confirms only that the local app runs; it is not proof of broker access or scheduled trading readiness.

## First thing to try

Visit **http://127.0.0.1:8765/trader-evaluate** and select **Run synthetic demo**. The dataset is invented and does not measure Indian-market returns. See [evaluation inputs](evaluation-data.md) for permitted CSV/JSON imports, and the [portfolio demo tour](portfolio-tour.md) for an interview-friendly walkthrough.

To run the standalone deterministic CLI demo:

```bash
python evaluation.py --demo
```

Use the Python executable in your virtual environment when multiple Python versions are installed.

## Optional broker configuration

Copy [`.env.example`](../.env.example) to a **local**, ignored `.env` file only if you intend to set up the Zerodha read connection. Never commit secrets, account records or licensed data. Consult [market data setup](market-data-setup.md) for the redirect URL, provider permissions and retention rules.

**No switch or credential can enable live order dispatch in the current release.** The server's readiness gate keeps it locked. Broker connection is **not** required for the demo or offline verification.

## Verification commands

### Windows PowerShell

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Get-ChildItem tests\*.test.js | ForEach-Object { node $_.FullName }
.\.venv\Scripts\python.exe scripts/fixture_recovery.py
```

### macOS / Linux

```bash
.venv/bin/python -m unittest discover -s tests -v
for file in tests/*.test.js; do node "$file" || exit 1; done
.venv/bin/python scripts/fixture_recovery.py
```

The repository's [.github/workflows/checks.yml](../.github/workflows/checks.yml) also runs Python/JavaScript syntax checks and regression tests. Tests use fixtures and mocks. They do **not** certify profitability, provider entitlement, market-hours operations, exchange compliance or production readiness.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Python is unavailable | Confirm Python 3.10+ is installed and available as `python` or `python3`; use that executable consistently |
| Virtual environment command fails | Confirm `python -m venv .venv` succeeded; use the PowerShell path on Windows and `.venv/bin/python` on macOS/Linux |
| Port 8765 already in use | Stop the other local instance or inspect `APP_PORT` in `.env.example` and the app configuration; don't expose a public interface |
| Broker tools report disconnected | This is expected for an offline demo; do not add credentials merely to run synthetic evaluation |
| News source unavailable | Check the [news agent guide](news-agent.md) and source-specific entitlement/health; absence of a paid feed is not a code failure |
| Tests fail due to local networking | Inspect the exact failing test and OS socket restrictions; do not mark blocked tests as passing |

## Safe contribution workflow

Create a feature branch, make one focused change, run the relevant tests, update behavior documentation, and open a pull request. Read [CONTRIBUTING.md](../CONTRIBUTING.md) and [SECURITY.md](../SECURITY.md) first. Explicitly note whether evidence is synthetic, mocked, imported historical, observed forward, or broker-reported.
