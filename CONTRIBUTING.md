# Contributing

Contributions should keep TradeLab India local-first, make live broker actions explicit, and make assumptions easy to inspect.

## Before proposing a change

- Explain the user problem and scope.
- Cite evidence for research claims and label assumptions as unvalidated.
- Document data provenance, license/terms, permitted use, and attribution.
- Describe security and privacy implications.
- Include relevant verification steps and known limitations.

## Boundaries

- No automated trading strategies or background order execution.
- Never place credentials in source, browser code, logs, issues, or screenshots. The local Zerodha connector reads developer credentials from the ignored `.env` file only.
- No buy/sell signals, profitability claims, investment advice, or claims of regulatory approval.
- Do not add market data or article text unless reuse and redistribution are permitted.
- Keep any demo and historical simulation labels visible and separate from broker data.

The current app is a local single-user prototype; it is not a hosted multi-user service. Do not commit or publish changes without explicit project-owner instruction.
