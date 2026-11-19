# Moneycontrol syndication adapter — mock contract

`syndication.py` implements the supplied JSON contract with injected transport. No private endpoint, key or client ID was invented. The redacted sandbox hostname is not a verified provider address. No Moneycontrol content is connected to the dashboard, public exports, external AI or trading decisions.

Validated behaviours: one-request-per-second serial limiter; transactional page/cursor processing; version-aware idempotent storage; retraction tombstones prevent stale replay resurrection; updated records are removed until a full corrected version arrives; tickers and summary/body metadata are replaced together. Sentiment remains `None`, not a fabricated neutral score.

The provided revision payload lacks full updated content and the endpoint list does not document `/feeds/news/{id}`. This adapter does not guess that endpoint. Production activation requires the provider to confirm how corrected full records are retrieved and how pagination, equal-timestamp boundaries, exhaustion and cursors work. `fullPage` indicates further paging may be required; it is not an exhaustion guarantee.

Revision failure blocks delivery. Six hours without a successful revision check causes cached article text to be deleted when the adapter is polled/read. Poll revisions before news on every service cycle. A continuously running scheduler, health monitoring and backup/cache retention policy are required before claiming a 24-hour operational purge SLA. Offline machines cannot guarantee detection or disk cleanup on time.

SQLite uses secure_delete and DELETE journaling. This does not certify forensic erasure on SSDs, filesystem snapshots or backups; keep this private cache outside OneDrive, source control and backups unless their purge policy is integrated. Store only minimal revision IDs/times after withdrawal, no withdrawn content. No secondary cache or sentiment store exists.

Public-source discovery was attempted separately: Moneycontrol's public RSS directory returned HTTP 410 through web tooling, and a direct public latest-news RSS read failed with HTTPError in this environment. That does not establish enterprise service availability. No access controls were bypassed and no browser cookies were copied.

Tests: `python -m unittest discover -s tests -p test_syndication.py -v`. Mock input only; no external credentials or real licensed content used. Production transport remains intentionally disconnected until its real endpoint and correction/pagination semantics are configured locally.
