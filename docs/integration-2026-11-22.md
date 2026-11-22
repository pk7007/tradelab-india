# Integration improvement

22 November 2026. Implemented against the existing local working tree, preserving
account history, saved limits and previous changes.

## Delivered connections

The application now constructs one IntegratedNews service. Its RSS and optional
licensed-feed collectors start and stop with the app. The same service supplies
the news API, intraday research context, automatic selector, paper worker and
desk monitor. The original NSE-only endpoint keeps its source filter.

The provisioned licensed path now connects FeedTransport to SyndicationCache
through LicensedNews. It is disabled by default and exposes disabled, blocked
configuration/storage, awaiting verification, fetched, syncing and unavailable
states. A valid configuration alone cannot produce a fetched state.

Polling runs once per minute, with one in-process request flight, bounded
retries and the existing one-request-per-second limiter. Revisions precede news
ingestion. Full revision pages remain uncertified, retractions remove content,
and overdue revisions expire cached content. Source freshness is shown through
the existing source-health interfaces. Reads make no provider requests and use
zero-timeout SQLite access so a writer cannot delay price processing. An indexed
projection limits each licensed snapshot to one hundred recent records.

Licensed article text stays in its dedicated private cache. Shared research
snapshots carry a generic event label, exact validated ticker tags, the provider
feed address and availability timestamps. They do not contain editorial text.
The cache is excluded from the application's configured backup list. Keep its
database path distinct from other ledgers and manage external copies under the
license. The running application cannot purge a stopped process or an external
backup. This integration does not implement sentiment or a news-driven signal.

The selector and worker now journal bounded event hashes and dates alongside
their account events. SessionEvidence hands these references to registered
event-entity-mapping analysis, separate deterministic review and feature roles.
The reviewer output includes the source journal sequence, account and input
hashes. This verifies the linkage of metadata. It does not establish issuer
accuracy, editorial truth or strategy quality.

## Independent review and repair

Review reproduced a high-priority delay where a separate SQLite writer could
hold up optional news reads for ten seconds before price processing continued.
The repair propagates timeout=0 through cache expiry and reads, skips a busy
in-process synchronizer, and excludes unavailable evidence. The external-writer
regression requires a response within half a second. Protective exits keep
using available price observations during optional feed failures.

The implementation batch received 9/10. Applying the original full-platform
integration scope, the reviewer assessed improvement from 1.1/2 to 1.4/2,
equivalent to 7/10. Actual provider operation, the complete agent graph,
long-term coverage and durable alerts still prevent a nine-out-of-ten claim.
The earlier whole-application score remains a dated 6.8/10 assessment.

## Verification

Nine isolated integration tests cover source-to-research delivery, retractions,
failure handling, configuration, lifecycle, concurrent reads, stopped-collector
expiry, bounded output and external SQLite lock contention. A real local HTTP
test traces the same event through the source endpoint, paper context journal,
registered analysis and review. It verifies input-hash lineage, editorial text
exclusion, retraction withdrawal and a protective exit after provider failure.
No broker orders are made. Complete discovery ran 381 tests, of which five HTTP
tests were blocked by Windows local connection permissions. All five passed on
authorized retry. Across discovery and retries all 381 passed. All seven
JavaScript test files, selected Python syntax checks and whitespace checks pass.
This batch did not rerun Chromium. The independent reviewer also repeated
focused integration and syndication tests.

## Activation and remaining acceptance

1. Put the real provisioned URL, exact approved host, key and client identifier
   into local configuration using the commented SYNDICATION fields in
   .env.example. Keep SYNDICATION_ENABLED=false until those values are ready.
2. Set SYNDICATION_ENABLED=true and restart the main application when ready for
   the licensed source. Check the Moneycontrol source's actual successful poll
   and freshness. A placeholder URL cannot activate it.
3. Verify real provider pages, publisher timestamps, cursor completeness,
   correction/retraction delivery and purge recovery. Multiple processes sharing
   a licensed feed are outside the current verified single-app service scope.
4. Complete the remaining durable agent workflow graph, long-term inputs and
   persistent alert delivery under their recorded acceptance requirements.
5. Observe the deferred market paper session from 23 November, with user broker
   login and reconciliation. No authenticated market run was performed here.

The changed backend must be restarted before its new connections and reviewed
build are active. Both market-supervision and closing-review automations now
require build 97ad1507e602c7c9ef5a19c994f66bf9ba308ec36ffbdee1181497256f177145.
A redacted check of local .env found provisioning incomplete and the licensed
collector disabled. No credential values were printed or external requests made.
Live execution and strategy promotion require their separate acceptance and
authorization. Profitability remains unverified. Changes are saved locally.
