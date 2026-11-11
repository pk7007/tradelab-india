# Implementation log — 6 November 2026

## Baseline and confirmed findings

80 Python tests passed before changes. Existing paper approvals are session-only: restarting loses their hypothetical book and reserved risk. The coordinator persists mock intents but deliberately blocks live start. Existing host, CSRF and manual-order regression checks passed; this is not a full security audit. Unrelated workspace changes were preserved.

## Delivered: persistent paper accounts

The separate `/trader-paper` workflow uses `paper.py` and SQLite. It creates explicitly configured single-symbol accounts, ingests permitted completed five-minute candles and records signals, next-open modeled fills, fees, cash, positions, realized P&L and audit events. No broker API exists in this engine.

The fixed SMA(5/20) rule uses completed closes. Fills assume full execution with supplied costs/slippage. Identical duplicate bars are ignored, including concurrent submissions. Revised processed bars, missing intraday intervals and incomplete session boundaries are rejected. A failed batch rolls back atomically.

Exposure is checked against entry cost; later price movement can exceed it. Daily loss is net equity decline from the previous session close. A breach blocks new buys for the imported session; it does not liquidate or guarantee a maximum loss. Overnight holding is allowed. Pause preserves pending intents; stop cancels them, leaving positions unchanged. Restart pauses running accounts and requires explicit resume.

Database defaults to `%LOCALAPPDATA%/TradeLabIndia/paper.sqlite`; override with `TRADELAB_PAPER_DB`. Creation and ingestion require acknowledged local-retention permission. The UI displays the latest 100 events across accounts; the database retains all events and candles. Local file permissions apply; encryption and tamper-evident auditing are unavailable. This does not migrate the older session paper book.

## Verification

88 Python tests passed. Eight new tests cover accounting, fee reconciliation, concurrent duplicates, restart with pending intent, rollback on missing data, revised candles, gap/exposure rejection and stop semantics. JavaScript syntax passed. Run `python -m unittest discover -s tests -v`.

## Remaining work in dependency order

1. Licensed data adapters, retrieval/availability metadata, exchange calendars and corporate-action handling. No continuous feed is connected; old imports are historical replay, not forward evidence.
2. Separate strategy contracts, additional baselines, walk-forward experiments, realistic liquidity and partial fills. Real-market profitability is unproven.
3. Authorized completed-bar scheduler with freshness checks, recovery and provider outage handling. This increment processes explicit imports only.
4. Unify planning, coordinator and paper risk interfaces; add portfolio/session limits and broker reconciliation before live execution. Automated live dispatch remains disabled.
5. Licensed news, corrections and point-in-time sector classification. Existing import tools remain available.
6. Retention/archive controls, load tests and broader accessibility checks. No production-readiness claim.

## Local demonstration

An isolated paper-only preview runs at http://127.0.0.1:8766/trader-paper with a separate synthetic database. The existing port 8765 workspace was not restarted. The preview processed 40 synthetic bars, ignored all 40 duplicate submissions, and rejected a request without a CSRF token. Browser start and pause controls were verified; shares and cash remained unchanged. No broker orders were submitted. Changes remain local and uncommitted.
