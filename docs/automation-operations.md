# Automation control room — implementation status

Updated 2026-11-01 (India). The new UI and durable execution prototype are implemented; this is not a production automated trader.

## Implemented

- Dark automation-first UI across account, data and research views; responsive control room.
- Versioned validated configuration with user-entered symbols and financial limits. Blank defaults avoid inventing risk preferences. Each save is unapproved.
- SQLite migration version 1: configuration, intent ledger and append-only application audit events. Default path `%LOCALAPPDATA%/TradeLabIndia/automation.sqlite`; override with TRADELAB_AUTOMATION_DB. Local Windows account permissions apply; encryption at rest and tamper-evident audit are not implemented.
- Prototype order coordinator: serialized intent creation, durable duplicate key, pending exposure checks, ambiguous acceptance handling, partial/terminal state checks and restart disarming. Database transactions commit intent state before the mock submission.
- Mock-only dispatch. No HTTP endpoint accepts signals, broker callbacks or live execution approvals. Manual order trading remains a separate pre-existing feature.
- Pause and stop disable new entries; neither claims to cancel or close broker positions. Start checks report blockers. Cancellation and flatten UI are visibly unavailable.

## Boundaries and missing work

No production Kite automated execution adapter, automatic exit loop, feed-to-strategy scheduler, verified broker margin snapshot, static-IP validation, account ownership binding, durable approval workflow, automated cancellations/flattening, or actual broker reconciliation is implemented. The UI's ready/running transitions cannot be entered through the public API. Tests set running state explicitly for mock verification. Mock protocol checks are not protection for the manual order endpoint.

SMA configuration is a draft specification; the existing synthetic strategy lab supplies an educational example. Changing financial limits does not prove the strategy profitable. No market-data retention rights are inferred.

The prototype assumes a single server process. Cross-process scheduling/leadership, production retry budgets, historical daily loss recovery, market impact, tick-size checks, protective stops and partial-exit recovery need further implementation. Do not enable unattended trading on this release.

## Recovery

1. Stop new entries. Use the broker directly if orders or positions need intervention.
2. After a restart, the app is disabled. SUBMITTING intents become UNKNOWN; PREPARED records remain unsubmitted.
3. Reconcile broker order book, trades and net positions by account and exact order identity before retrying any ambiguous submission. Absence from one response is not proof of rejection.
4. Never edit the ledger to force an order retry. Back up the database with the app stopped before maintenance.
5. Re-authenticate through the normal Kite flow after session expiry. Do not log or persist tokens in the ledger.
6. Any eventual live resume must follow exact strategy/limits approval and verified recovery tests.

## Verified source register

Retrieved 2026-11-01; page publication dates not supplied unless stated.

- [Zerodha static IP requirements](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/static-ip): effective 1 April 2026, API order placement requires a registered static IP; data/read APIs differ. User must verify their registration.
- [Kite orders](https://kite.trade/docs/connect/v3/orders/): order IDs and order lifecycle require reconciliation; a successful placement request is not proof of execution. Broker-supported tags are correlation aids, not assumed idempotency guarantees.
- [Kite exceptions and limits](https://kite.trade/docs/connect/v3/exceptions/): token expiry, network errors and rate limits must be handled; the prototype's 30/minute configuration cap is an application restriction, not a claim of broker quota.
- [Kite authentication](https://kite.trade/docs/connect/v3/user/): normal broker login/token exchange remains required. No authentication bypass is implemented.

This is not an exhaustive exchange/legal readiness determination. Broker approval and current account-specific requirements remain pending.

## Tests

Run `.\.venv\Scripts\python.exe scripts/check_research.py`. See research-test-results.md for each result. Automation tests use temporary SQLite databases and a mock broker; no real orders are submitted.

Before live activation, provide chosen instruments, capital, fixed quantity/position sizing, exposure and position limits, daily loss threshold, order frequency, exact entry/exit rules, session times, protective exits, and recovery policy. The current UI saves the supported subset for review; missing production functions remain blockers.
