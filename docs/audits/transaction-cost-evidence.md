# Transaction-cost evidence - 22 November 2026

## Delivered boundary

`transaction_costs.estimate_order` is an opt-in Decimal planning interface for
NSE resident-individual equity intraday, equity delivery, equity futures and
equity options normal trades. It never places an order or changes existing paper
accounts. Legacy `costBps` and slippage assumptions remain unchanged.

The caller must provide the explicit cost version, exchange, account type,
segment, settlement, side, price, executed units, as-of date, slippage and other
charges including tax. Delivery sells also require the actual applicable DP
debit charge including tax. Option prices mean premium and quantities mean units,
not lots. Aggregate all partial fills of one executed broker order before using
the per-order brokerage cap. Applying the cap to each fill is unsupported.

## Verified schedules

- [NSE/FA/73061](https://nsearchives.nseindia.com/content/circulars/FA73061.pdf),
  dated 27 February 2026, effective 1 March 2026: cash/futures/options combined
  exchange plus IPFT outflows are respectively INR307/183/3553 per crore.
  The separate IPFT contribution is INR0.01 per crore; the module splits it from
  transaction fees and does not add it twice.
- [NSE/FATAX/73524](https://nsearchives.nseindia.com/content/circulars/FATAX73524.pdf),
  dated 31 March 2026, effective 1 April 2026: futures sale STT is 0.05% and
  option-premium sale STT is 0.15%. Equity delivery remains 0.1% both sides and
  intraday 0.025% sell side.
- [NSE statutory levies](https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies):
  SEBI fee is INR10 per crore; buy-side stamp rates are 0.015% delivery,
  0.003% intraday/options and 0.002% futures.
- [Zerodha tariff](https://zerodha.com/charges): resident retail delivery
  brokerage is zero; intraday/futures use the lower of INR20 and 0.03% per
  executed order; options use INR20. GST is 18% of brokerage, transaction fees
  and SEBI fees; the IPFT contribution also attracts GST.
- [Zerodha STT explanation](https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/how-is-the-securities-transaction-tax-stt-calculated):
  STT rounds half-up to whole rupees; its INR3000 option-premium example gives
  INR4.50 raw STT and INR5 after rounding.

Version `zerodha-nse-retail-2026-04-01-v1` covers 1 April through the source
verification date, 22 November 2026. Earlier and later as-of dates fail closed
until an explicitly reviewed version is supplied. This conservative verification
window is a project control, not an assertion that official rates expire then.

## Arithmetic and acceptance evidence

Thirteen focused tests passed. The independent published INR-per-crore figures
are checked against raw Decimal components. For an INR100000 intraday buy, the
modeled rows include brokerage 20, combined NSE/IPFT 3.07, SEBI 0.10, stamp 3 and
GST 4.1706; presented total is 30.34. Tests separately cover sell-side STT,
delivery DP input without double GST, the official option rounding example,
futures rates, brokerage caps, malformed/nonfinite/boolean financial values,
unsupported profiles/settlements/dates, explicit assumptions and input immutability.

The result provides exact raw components, rounded presentation and an upward
rounded per-line planning reserve. The reserve covers the modeled rows only; it
does not guarantee a maximum broker bill or trading loss. Amounts remain Decimal.

## Remaining acceptance and integration limits

All results have `estimateOnly=True`, `liveEligible=False` and
`executionAllowed=False`. `require_live_eligible` always rejects promotion
pending broker settlement reconciliation and an independently reviewed integration.
No current account or strategy is promoted by this module.

BSE needs group/instrument-specific tariff validation; currency, commodity/CTT,
NRI/corporate accounts, MTF, exercise/assignment and physical settlement remain
unsupported and fail closed. Broker auto-square-off/dealer, debit balance,
contract-note, delivery minimum and other account-specific charges must be
explicitly allocated in the caller's other-charge input. DP charges vary by
account profile and scrip/day debit history, so none is silently assumed.

STT and other line presentation here use per-order planning rounding. Exact
broker contract-note aggregation, daily/category STT rounding, minimum charge
allocation, actual DP billing and calculator/contract-note end-to-end matching
remain UNVERIFIED. No calculator parity or live-production readiness is claimed.
