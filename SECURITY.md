# Security policy

## Scope

TradeLab India includes a local single-user Zerodha connector prototype. It is not a public service or production-supported version.

## Reporting a concern

Do not include secrets, broker credentials, OTPs, UPI PINs, private customer information, or personal financial data in an issue. For a sensitive report, contact the repository owner privately using the contact method configured on the hosting platform. No response-time commitment is made until a maintainer process exists.

## Security principles

- Never ask for broker passwords, OTPs, or UPI PINs. Authentication must happen on Zerodha's own site.
- Kite developer credentials belong only in the local, ignored `.env` file. Do not share that file or expose API secrets or access tokens in browser code, logs, issues, or screenshots.
- The app binds to loopback and retains the access token in process memory only. Do not expose it to the internet or use it for multiple users.
- Live orders are disabled by default and require an explicit local configuration switch plus per-order review and typed confirmation.
- Review broker and applicable exchange/regulatory requirements before enabling orders or proposing a hosted service.
