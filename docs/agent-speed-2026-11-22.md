# Agent timing report - 22 November 2026

All 512 registered evidence roles were measured on Windows with Python 3.11.3.
Each role processed one synthetic record 25 times after one warm-up call.
These are local handler timings, not news delivery or live trading latency.
The report does not prove strategy performance or profitability.

Median local handler: 0.0262 ms; p95: 0.0917 ms; slowest observed call: 1.5561 ms.
Three isolated enqueue/subprocess/persistence runs had median 201.5 ms.
Queue measurements exclude review acceptance and do not establish tail latency.

At inspection, the running app reported 512 registered roles, 504 enabled roles
and four queue worker threads. Enabled means eligible for tasks; roles are not
504 continuously running AI models. Paper selection and its worker were disarmed.

## Configured cadence

| Component | Cadence or trigger |
| --- | --- |
| NSE filings, ET and Google RSS | 30 seconds after a healthy collection; sequential sources and network time add delay |
| Moneycontrol licensed collector | 60-second loop when configured; currently optional |
| News dashboard snapshot | Every 5 seconds; reads cached data |
| Automatic selection/paper scheduler | 30-second loop; strategy uses completed 5-minute candles |
| Fixed-symbol paper worker | 30-second loop when explicitly running |
| Department supervision and session evidence | 30 seconds after each check finishes |
| Department health tasks | One per department per 5-minute bucket |
| Research queue consumers | Four threads; idle wait up to 1 second |
| Entry review | On a completed signal; custom reviewer response timeout 100 ms |
| Alert inbox dashboard | 15 seconds |
| Independent local service watcher | 30 seconds; app outage recorded after 3 failures |
| Backup scheduler | Checks every 5 minutes; backs up missing/incomplete/older-than-one-day snapshots |

Cadence is not an end-to-end guarantee. Broker limits, queue load, provider
publication delays, outages and retry headers can extend these times.
Selection requires 20 completed candles. The 5-minute strategy is unchanged.

A single public NSE RSS request took 199.9 ms and returned 41 feed items during
this task. This is one observation, not a delivery SLA or broad benchmark.
Filings are links/metadata from that same feed; no additional PDF requests occur.

## Per-family local handler timings

Each family below contains 16 roles. The JSON artifact contains every role.

| Family | Median ms | p95 ms | Maximum ms |
| --- | ---: | ---: | ---: |
| instrument-reference | 0.0298 | 0.1528 | 0.2621 |
| exchange-calendar | 0.0236 | 0.0954 | 0.9373 |
| quote-observations | 0.0243 | 0.095 | 0.2378 |
| historical-candles | 0.0274 | 0.1451 | 0.2402 |
| corporate-actions | 0.027 | 0.0666 | 0.2093 |
| news-ingestion | 0.0213 | 0.0688 | 0.2327 |
| event-entity-mapping | 0.0207 | 0.096 | 0.2904 |
| earnings-disclosures | 0.0233 | 0.1077 | 0.4559 |
| fundamental-statements | 0.0278 | 0.1491 | 0.4756 |
| financial-ratios | 0.0252 | 0.0903 | 0.1806 |
| valuation-assumptions | 0.0262 | 0.0951 | 0.3081 |
| governance-evidence | 0.025 | 0.0665 | 0.8945 |
| sector-classification | 0.0241 | 0.0597 | 0.2353 |
| benchmark-data | 0.0277 | 0.0874 | 0.164 |
| technical-indicators | 0.0299 | 0.1046 | 0.3906 |
| momentum-relative-strength | 0.0272 | 0.1105 | 0.3929 |
| market-regimes | 0.0267 | 0.0555 | 0.2691 |
| liquidity-spreads | 0.027 | 0.1015 | 0.1804 |
| transaction-costs | 0.0266 | 0.114 | 1.1076 |
| position-sizing | 0.0263 | 0.1213 | 0.566 |
| trade-risk | 0.0251 | 0.1288 | 0.4016 |
| portfolio-exposure | 0.0213 | 0.0863 | 0.843 |
| backtest-execution | 0.0227 | 0.0846 | 1.5561 |
| statistical-validation | 0.0244 | 0.0902 | 0.1114 |
| benchmark-evaluation | 0.0299 | 0.1033 | 0.2819 |
| performance-attribution | 0.0269 | 0.089 | 0.2832 |
| strategy-versioning | 0.0236 | 0.0606 | 0.0865 |
| paper-execution | 0.0308 | 0.1147 | 0.2105 |
| order-position-reconciliation | 0.0347 | 0.1142 | 0.2731 |
| recovery-persistence | 0.023 | 0.0537 | 0.0815 |
| operations-security | 0.0255 | 0.0852 | 0.1306 |
| application-reporting | 0.0285 | 0.0877 | 0.4119 |

Full results: [all 512 roles](agent-speed-2026-11-22.json).
