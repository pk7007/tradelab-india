# Assumptions and calculations

## Current status

No simulation calculations are implemented. The definitions below are requirements for future design and must be reviewed before implementation.

## Proposed run record

Store immutable references to instrument, session, data version, timezone, strategy or user-entered plan version, parameter values, fee schedule, slippage model, corporate-action policy, and calculation version. A run should be reproducible from these inputs.

## Assumption requirements

- State whether prices are adjusted or unadjusted and how splits/dividends are handled.
- Define execution timing so future information cannot leak into a decision.
- Make transaction costs, taxes, and slippage explicit and configurable only within documented bounds.
- Document order-fill, liquidity, market-hours, rounding, and missing-bar assumptions.
- Distinguish gross and net hypothetical results and show modeled costs separately.
- Define each metric mathematically before presenting it.

Historical simulation is not a forecast. No result should be described as proof of profitability or expected income.
