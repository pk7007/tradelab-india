# Independent broker safety and compliance evidence

Checked on 22 November 2026 (Asia/Kolkata). Baseline: `9b6d3697595e3fb03304e88fadd1d720b0879394`.

This records primary-source requirements and source inspection. It does not
certify the account, strategy, deployment, static IP or exchange approval. Live
execution must remain locked. No real broker order or account mutation was used
for this review. BSE and derivative-specific operating approval remain
UNVERIFIED; the immediate implementation scope prioritizes NSE cash equities.

## Effective framework and deployment classification

- SEBI circular 2025/132, dated 30 September 2025, paragraph 8 makes the retail
  algo framework and exchange implementation modalities applicable to all brokers
  from 1 April 2026. Earlier August/October 2025 dates are not the final general
  applicability date. [SEBI original PDF](https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1759232056254.pdf).
- NSE/INSP/77559, dated 20 November 2026, applies immediately. It distinguishes
  genuine tech-savvy clients developing their own algorithms using programming
  knowledge from other retail users. Brokers must obtain the specified client
  undertaking. The client-hosted static-IP exception must not be assumed from
  installing this application or passing tests. Broker confirmation of the
  applicable category, undertaking and permitted hosting arrangement remains
  UNVERIFIED. [NSE current circular](https://archives.nseindia.com/content/circulars/INSP77559.pdf).

## Identifiers, authentication and order budgets

NSE/INVG/67858, dated 5 May 2025, specifies static-IP mapping, daily API-session
logout, and the order threshold measured by the broker's calendar-clock second.
The threshold is 10 OPS per exchange/segment, with brokers permitted to impose
lower client limits. Below-threshold orders still require the exchange tagging
mechanism; they do not become exempt from baseline controls. Above-threshold
algorithms require registration through the broker. Exchange-issued algo
identification is different from the application's optional order correlation
tag. [NSE implementation standards, sections A, B, C, F and G](https://nsearchives.nseindia.com/content/circulars/INVG67858.pdf).

Zerodha's current FAQ specifies 10 OPS per client trading account, across apps;
the application must not allocate a fresh order budget to each worker or API
key. It also describes static-IP whitelisting at developer-account level and
counts blocked invalid requests toward request limits. Read-only endpoints do
not establish order-endpoint IP readiness. The retrieved FAQ says 1 April 2025
in its static-IP introduction, conflicting with the dated 2026 framework sources
above. Record that discrepancy; do not copy it as the framework commencement
date. [Zerodha API FAQ](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs).

The API reference additionally lists quote requests at 1/second, historical
requests at 3/second, placement at 10/second, 400 orders/minute, 5,000/day, and
25 modifications per order. Conservatively coordinate mutation budgets across
placement, modification and cancellation workers and verify operation-specific
counting with the broker before live use. Reserved emergency capacity cannot
override broker limits. [Kite rate-limit reference](https://kite.trade/docs/connect/v3/exceptions/).

## Order types and protective exits

Kite documents `market_protection` for MARKET and SL-M orders, using a configured
percentage or `-1` for automatic protection. Its optional `tag` is an application
identifier, at most 20 alphanumeric characters; it is not evidence of exchange
registration. An acknowledged request still needs order/trade reconciliation.
[Kite order API](https://kite.trade/docs/connect/v3/orders/).

Zerodha explains that market protection may leave remaining quantity pending as
a limit order. Protective placement or a square-off request therefore does not
prove closure, and a price protection band is not a guaranteed loss cap.
[Zerodha market protection explanation](https://support.zerodha.com/category/trading-and-markets/charts-and-orders/order/articles/market-price-protection-on-the-order-window).

## Verified baseline code observations

- `app.py` has one real order-placement call: `Handler.place_order` invokes
  `kite_request('/orders/regular', ..., method='POST')`. Both the environment flag
  and the hard-coded `LIVE_EXECUTION_READY = False` guard it. No real order
  modification or cancellation caller was found in the inspected baseline.
- `validate_order` already supplies automatic market protection for MARKET and
  SL-M. Its presence does not verify instrument eligibility, broker-side coverage,
  static-IP readiness or an approved trading strategy.
- Host-header validation confines HTTP access to configured loopback hosts;
  mutation routes require the session CSRF token and reject mismatched Origin.
  OAuth state has a ten-minute bound. Broker credentials remain in memory.
- `ExecutionJournal` persists manual submissions before transport and preserves
  ambiguous acknowledgements as unresolved. It is not a broker-wide automated
  OMS, authoritative inventory allocator or completed liquidation controller.
- `broker_snapshot.py` explicitly marks sequential evidence as read-only and
  not authoritative allocation proof. Passing caller-provided book comparisons
  must not change that claim.

## Confirmed transport finding and reproducer

**P1: baseline broker transport follows redirects with Authorization attached.**
`app.py:kite_request` used the default `urllib.request.urlopen`. The independent
reproducer extracted that exact function from the AST, substituted two local fake
HTTP servers and dummy key/token values, then returned a 302 from `127.0.0.1`
to a `localhost` receiver on another port. Result:

```json
{"crossHostRedirectForwardedAuthorization":true,"realCredentialsUsed":false,"realBrokerRequests":0}
```

This demonstrates credential-forwarding behavior when a redirect occurs; it does
not demonstrate a current broker compromise or an active live-order bypass.
Required repair: reject broker redirects before forwarding credentials, validate
the fixed HTTPS broker origin, and bound/validate responses. Apply equivalent
transport restrictions to OAuth token exchange. Regression tests must prove the
redirect destination receives no request and valid broker responses still work.
Root implementation and post-fix verification are recorded in the repair report.

## Evidence that must remain false or unverified

Broker/exchange classification and undertaking; static-egress IP ownership and
whitelisting; correct generic/registered algo-ID assignment and broker mapping;
authenticated account permissions; real protective-order lifecycle; current
margin/instrument restrictions; cross-app account-wide rate acceptance;
broker-confirmed cancellation/liquidation; sustained forward-paper results; and
live deployment approval are UNVERIFIED unless separately evidenced. Offline
tests may validate enforcement while these approval states remain false.

No granular evidence supports converting the attachment's historical 31/100
claim into a newly measured score. Economic performance and profitability are
N/A. Monday market-dependent verification remains deferred under AGENTS.md.
