# NSE filing integration - 22 November 2026

The news agent now exposes original NSE PDF filing links from announcement RSS
items, enclosures and description anchors. Market news has an NSE filings filter.
Distinct disclosures remain separate, even when issuer names and summaries match.
Document labels classify RSS metadata; PDFs are not downloaded or read.

Only validated HTTPS PDF links on official NSE hosts are exposed. No additional
PDF network requests or paid API are introduced. Revised attachment identities
advance availability time. Current exact-mapped items reach shared research
context; stale, future and unmapped evidence stays excluded. Paper evidence
retains bounded filing IDs and hashes without copying PDF text.

The reviewed-build fingerprint includes the shared RSS and filing dependencies.
Existing paper supervision and closing-review schedules now recognize tested
build 7c08b01c5dd3c3a604224634630a95c92db8d51308df73ab373b3a3490c6231e.
Their timing, financial limits and Monday activation deferral are unchanged.

## Verification

- 393 Python tests passed.
- All nine JavaScript regression files passed.
- Three isolated Chromium scenarios passed: qualifying, no-trade and guided
  setup/news/filings/alerts/restore. No page errors or broker-order calls.
- A real local-app mobile-sized browser showed 20 filing links on the first
  page with no page errors or horizontal overflow.
- A public NSE RSS request returned 41 feed items in 199.9 ms in one observation.
- After restart, the shared source exposed 28 current NSE items with 21 filing
  links. Feed counts vary over time.
- Eight private databases were snapshotted before the disarmed local restart.
  Licensed editorial cache was excluded.
- Independent focused review: 9.2/10. Three P2 findings were repaired and rechecked.

The new integration is loaded locally. Broker login must be completed again
before a later paper session. Live dispatch remains locked; this feature does
not produce news-driven entry signals or change the five-minute price strategy.

## Timing evidence and limits

[All-agent speed report](agent-speed-2026-11-22.md) covers the configured
schedules, all 32 role families and the complete 512-role JSON benchmark.
Handler measurements used one synthetic record and 25 repetitions per role.
Queue measurements used three isolated subprocess tasks. These are not live
delivery guarantees, production tail-latency estimates or profitability evidence.

Remaining limits: no full PDF extraction or historical filings archive, no
sustained publisher revision/outage forward test, and no extended accessibility
audit. Free RSS delivery can be delayed or incomplete.
