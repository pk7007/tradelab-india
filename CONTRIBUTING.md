# Contributing to TradeLab India

TradeLab India is a **local-first, single-user research and paper-trading prototype**, not a hosted or production-ready automated trading service. The goal is readable, reproducible and risk-aware engineering.

For an overview of the project, start with the [portfolio tour](docs/portfolio-tour.md), [development setup](docs/development-setup.md), [architecture](docs/architecture.md) and [capability map](docs/feature-status.md).

## Getting a local development environment

1. Fork or clone the repository and create a focused feature branch.
2. Install Python 3.10+ and Node.js. Follow the exact Windows or macOS/Linux instructions in [development setup](docs/development-setup.md).
3. Run the **synthetic** evaluation demo; no brokerage credentials are required.
4. Before opening a pull request, run the relevant Python and JavaScript tests and the restart-recovery fixture. Report any blocked test rather than describing it as a pass.

## What makes a useful contribution?

- Fix a reproducible bug with a regression test.
- Improve data-quality controls, modeled cost explanations, timestamp handling or documented risk boundaries.
- Make local setup and accessibility more reliable.
- Improve source attribution or paper-ledger recovery using non-sensitive fixture data.
- Propose larger features through an issue or a design note with assumptions, scope, safety and test criteria.

See the [remaining feature roadmap](docs/remaining-feature-roadmap.md). Avoid adding an AI agent, new strategy or broker connector merely to increase feature count.

## Pull-request checklist

- [ ] State the user problem, changed modules and expected behavior.
- [ ] Distinguish synthetic, mocked, historical, observed-forward and broker-reported evidence.
- [ ] Add or update tests for calculations, data handling and order/intent lifecycle changes.
- [ ] List local commands executed and their actual results.
- [ ] Describe security, privacy, source-entitlement and regulatory implications.
- [ ] Update user-facing docs, especially when a feature is incomplete or disabled.
- [ ] Exclude secrets, account data, private databases, licensed datasets and generated caches.
- [ ] Confirm that live order dispatch remains locked.

## Hard safety boundaries

- **No automatic or background live broker order execution** as a routine contribution. The existing *paper* worker is allowed to simulate orders, but must never bypass live dispatch locks.
- Never place developer keys, tokens, passwords, OTPs or UPI PINs in code, browser assets, tests, logs, issues or screenshots. Kite credentials are local to an ignored `.env` file.
- No investment advice, fabricated win rates, unvalidated profitability claims, or claims of SEBI/NSE approval.
- No redistribution of market data, paywalled content or full articles without documented permission.
- Keep simulated and imported observations clearly separate from actual forward-market evidence.
- Do not weaken protective exit processing when optional research or external sources are unavailable.

## Reporting issues

For reproducible bugs, include a minimal test case, OS/Python/Node versions, steps, expected versus observed behavior and **redacted** logs. For vulnerabilities, use [SECURITY.md](SECURITY.md); never disclose account or authentication information in a public issue.

A pull request invites review; it is not authorization to merge, deploy, activate real-money trading, or change someone else's financial limits. External contributions require maintainer review.
