# Product brief

## Product

TradeLab India is a local-first Indian market workspace. The first runnable slice connects one user's Zerodha account through Kite Connect to inspect account state and submit manually reviewed orders. Historical replay, simulations, and journaling remain planned product areas.

## Problem hypothesis

People learning to reason about market decisions may benefit from a replay and journal that makes data limitations, assumptions, and decision context visible. This is a hypothesis to validate through interviews and prototype research, not an established market gap.

## Intended users

Initial research participants may include self-directed learners, finance students, and people practicing structured decision review. Recruitment and interview findings are not yet complete.

## Goals

- Keep broker authentication and API calls on the local server, never in browser code.
- Present holdings, positions, and order status clearly.
- Require review and explicit confirmation before a live order request.
- Later, make historical simulations reproducible and explain their data and modeling assumptions.

## Non-goals and boundaries

- No automated strategy or background order placement.
- No broker passwords, OTPs, or UPI PINs collected by this app. Developer API credentials are local server configuration only.
- No buy/sell signals, advice, profit promises, or claims of profitable strategies.
- No claim of SEBI/NSE approval or compliance.
- No market-data scraping or redistribution without permission.
- No reproduction of full news articles; a digest links to sources and uses only permitted short metadata/excerpts.

## Candidate MVP

Current slice: Zerodha account profile, holdings, positions, orders, quotes, and manual order entry with a review step. Future simulation MVP: session selector, historical replay, hypothetical trade-plan entry, transparent costs and slippage, journal and review, data-source and quality labels, and reproducible run records.

## Success measures to validate

- Task completion and time for replay, plan entry, and review tasks.
- User ability to explain that outcomes are historical/synthetic and not predictive.
- User ability to locate source, data-quality, cost, and slippage assumptions.
- Reproducibility of a saved run under the same versioned inputs.

These are proposed measures, not reported results.
