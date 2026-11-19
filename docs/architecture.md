# Architecture

## Current state

The [current architecture/capability map](feature-status.md) and [20 November loss-path audit](gap-audit-2026-11-20.md) supersede historical feature claims below. Primary navigation is Intraday, Long-term and Auto Trading; account/data diagnostics remain at `/advanced`.

The app uses a single-user Python HTTP server, the official Kite Connect SDK, and a vanilla HTML/CSS/JavaScript interface. It binds to loopback, talks to Kite Connect from the server, and stores access tokens only in process memory. No market data is bundled. Historical jobs run on bounded worker threads; live quotes use one private KiteTicker connection with a bounded in-memory buffer. The browser reads its snapshot once per second. Storage is permission-gated and defaults to Windows Local App Data outside the repository.

## Proposed boundaries

Current persistence and execution boundaries are detailed in the [18 November repair report](system-repair-2026-11-18.md). `paper.py` has a durable independent simulation ledger; `automation.py` has a separate mock execution/reservation ledger; `execution_journal.py` correlates manual intents with broker evidence; `experiment_registry.py` retains portal research summaries and holdout fingerprints. These are not yet unified into a broker-funded multi-portfolio system.

- **Presentation:** local dashboard for account, holdings, positions, order book, and a manual order review flow.
- **Broker adapter:** Zerodha Kite Connect server-side requests; broker credentials are never sent to the browser.
- **Simulation service:** future deterministic calculations over fixed, versioned inputs, kept distinct from live brokerage state.
- **Data catalog:** provider provenance, license/terms, timezones, coverage, quality checks, and versioning.
- **Persistence:** minimal user data with access, retention, export, and deletion controls designed before use.
- **Digest automation:** isolated GitHub Actions job reading only enabled and reviewed public feed endpoints and writing linked Markdown summaries.

## Trust and safety boundaries

The app binds to loopback, keeps access tokens in memory, and blocks live order dispatch with a server-side readiness gate in addition to local configuration. A flag or API key alone cannot unlock it. Reviewed order validation and durable recovery are exercised with mocks; no live strategy scheduler is connected. Keep synthetic demos distinct from historical data. Fail visibly on source or data errors. Every calculation should expose its assumptions and version. The digest workflow is gated and must not publish externally.

## Future decision gate

Before any public deployment or additional broker adapters, document a threat model, broker terms/approval, current exchange and SEBI requirements (including any static-IP, API registration, tagging, and hosting conditions), calculation definitions, and an operations plan. This local prototype is not a multi-user service.
