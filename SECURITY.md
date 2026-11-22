# Security policy

## Scope

TradeLab India includes a local single-user Zerodha connector prototype. It is not a public service or production-supported version.

## Reporting a concern

Do not include secrets, broker credentials, OTPs, UPI PINs, private customer information, or personal financial data in an issue. For a sensitive report, contact the repository owner privately using the contact method configured on the hosting platform. No response-time commitment is made until a maintainer process exists.

## Security principles

- Never ask for broker passwords, OTPs, or UPI PINs. Authentication must happen on Zerodha's own site.
- Kite developer credentials belong only in the local, ignored `.env` file. Do not share that file or expose API secrets or access tokens in browser code, logs, issues, or screenshots.
- The app binds to loopback and retains the access token in process memory only. Do not expose it to the internet or use it for multiple users.
- **Live order dispatch is locked in the current release**, by a server-side readiness gate in addition to configuration. Setting `TRADELAB_ENABLE_LIVE_ORDERS=true`, connecting a brokerage account, or completing an old manual review flow does **not** unlock live orders.
- Paper-order controls use simulated data and a separate local ledger; they are not authorization for actual broker orders.
- Before any separately approved real-money capability, require account ownership, broker funding and inventory reconciliation, uncertain-order recovery, risk/exit validation and review of applicable broker/exchange rules. See [readiness and operations](docs/intraday-readiness.md).
- Review broker and applicable exchange/regulatory requirements before enabling orders or proposing a hosted service.
