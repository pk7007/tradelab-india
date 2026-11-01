# Architecture

## Current state

The app uses a single-user Python HTTP server, the official Kite Connect SDK, and a vanilla HTML/CSS/JavaScript interface. It binds to loopback, talks to Kite Connect from the server, and stores access tokens only in process memory. No market data is bundled. Historical jobs run on bounded worker threads; live quotes use one private KiteTicker connection with a bounded in-memory buffer. The browser reads its snapshot once per second. Storage is permission-gated and defaults to Windows Local App Data outside the repository.

## Proposed boundaries

- **Presentation:** local dashboard for account, holdings, positions, order book, and a manual order review flow.
- **Broker adapter:** Zerodha Kite Connect server-side requests; broker credentials are never sent to the browser.
- **Simulation service:** future deterministic calculations over fixed, versioned inputs, kept distinct from live brokerage state.
- **Data catalog:** provider provenance, license/terms, timezones, coverage, quality checks, and versioning.
- **Persistence:** minimal user data with access, retention, export, and deletion controls designed before use.
- **Digest automation:** isolated GitHub Actions job reading only enabled and reviewed public feed endpoints and writing linked Markdown summaries.

## Trust and safety boundaries

The app binds to loopback, keeps access tokens in memory, and hides live order submission unless explicitly enabled by local configuration. Each order has a review and typed confirmation step; no automated strategy or background execution is implemented. Keep synthetic demos distinct from historical data. Fail visibly on source or data errors. Every calculation should expose its assumptions and version. The digest workflow is gated and must not publish externally.

## Future decision gate

Before any public deployment or additional broker adapters, document a threat model, broker terms/approval, current exchange and SEBI requirements (including any static-IP, API registration, tagging, and hosting conditions), calculation definitions, and an operations plan. This local prototype is not a multi-user service.
