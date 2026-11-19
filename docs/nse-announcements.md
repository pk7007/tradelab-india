# NSE announcement integration

The Intraday tab reads official announcement RSS summaries from the feed published in [NSE's RSS directory](https://www.nseindia.in/static/rss-feed): `https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml`.

The server caches in memory for five minutes. The page refreshes initially and every five minutes while visible; a manual refresh respects that same server cache. Closing the tab stops polling. This is not a closed-browser daemon or a low-latency trading feed.

Portal intraday research now automatically checks this cache on every request and attaches only mapped announcements whose publication and first-seen timestamps precede the research cutoff and whose publication is no older than 24 hours. Stale feeds and unmapped companies are excluded. The response includes `automaticNewsCheck` diagnostics. User-entered risk observations and explicit trade plans remain mandatory; this does not run a market-wide candle scan or submit an order. The API change requires restarting the app and reconnecting the broker. The combined suite now passes 189 tests, including mock syndication and research-context cutoff checks.

Items show publication and first-seen time, with original document links. First-seen memory resets on restart, so historical availability must not be inferred from this feed. No articles/PDFs are fetched automatically and nothing is stored to disk. No announcement triggers orders or changes risk limits.

Company names are matched exactly against the already-loaded broker instrument master when available. Unmatched or ambiguous names remain unmapped; no ticker is guessed from headlines or attachment filenames. This is a dedicated contextual panel; historical research continues to require explicit point-in-time inputs, avoiding accidental use of current headlines in old backtests.

Failures preserve old summaries but mark them stale, with last successful receipt shown. Network response size and item count are bounded; DTD/entity XML, future publication times and unsafe source links are rejected. No paywalls or access controls are bypassed. NSE's RSS delivery may be delayed; public feed availability does not establish broader redistribution rights.

181 Python tests pass after integration. Reader tests cover the actual NSE date format, duplicate/future items, link allowlist, XML entity rejection, response limits and cached outage states. JavaScript syntax passed. The public-feed read was checked separately without broker calls. Restart is required to load the new endpoint; restarting clears the current broker login, requiring reconnection.
