# Indian-market news agent

The main application uses a shared RSS and optional licensed-news service for
its source API, research, paper workers and desk monitoring. See the
[current integration and provisioning guide](integration-2026-11-22.md). App RSS
checks run on a 30-second interval, and an enabled provisioned licensed source
uses a 60-second interval. The CLI defaults described below apply to the
standalone reader.

`news_agent.py` is a local personal RSS reader for Indian stocks and indices. It can run independently and is also connected to the dashboard through /api/news-agent and requires no new packages, broker login or model key. By default it reads the existing official NSE announcements feed, ET's stocks RSS feed and the supplied Google News search for `RELIANCE stock OR NSE` (English, India). Polling defaults to 30 seconds; publisher delays and rolling-feed gaps mean this is not a guaranteed real-time or complete news service.

From the repository root:

```powershell
# Read once; later runs emit only new or changed matching items.
.\.venv\Scripts\python.exe news_agent.py --once

# Keep reading until Ctrl+C; company names help when a headline omits the ticker.
.\.venv\Scripts\python.exe news_agent.py --watch --watchlist "Reliance,TCS,HDFC Bank,Nifty,Sensex" --include-market

# Machine-readable output: one JSON object per poll.
.\.venv\Scripts\python.exe news_agent.py --once --json

# Use only exchange disclosures.
.\.venv\Scripts\python.exe news_agent.py --watch --sources nse

# Use only the supplied Google News search.
.\.venv\Scripts\python.exe news_agent.py --watch --sources google
```

The Google source uses [your exact search URL](https://news.google.com/rss/search?q=RELIANCE+stock+OR+NSE&hl=en-IN&gl=IN&ceid=IN:en). It retains Google article links and the original publisher name from RSS metadata; it does not follow the article redirects or download publisher pages. The search query is fixed independently of `--watchlist`, which filters the returned headlines locally. Google results may include unrelated NSE stories because the query uses `OR`. The same story appearing under different source URLs is kept separately.

Keep the terminal/process running for continuous monitoring. Nothing installs a background service or sends external messages. `--interval` accepts at least 30 seconds. `--max-age-hours` defaults to 24 and accepts 1–168. A one-shot check exits with code 1 if any source fails, while watch mode reports the failure and retries next cycle. A successful feed can have no items; an outage is explicitly marked unavailable. No old content is presented as a fresh fetch.

Each item includes publisher text, its source link, publication and receipt times, persistent first-seen time, new/updated status and simple keyword categories. UTC timestamps include their timezone. Watchlist matching uses case-insensitive phrase boundaries in titles/summaries. These are text matches, not verified exchange-symbol mappings; aliases and ambiguous names require review. An empty watchlist includes all feed items. `--include-market` also includes basic index and macro keyword matches when a watchlist is present. Categories are keyword labels, not AI summaries, sentiment predictions or trading recommendations.

Only matching item identity/content hashes and observation times persist in `data/private/news-agent.sqlite`, which Git ignores. Article text is not stored. Identities expire after 30 days without observation. The same source URL with changed text or publication time is emitted again as an update; different publisher URLs remain separate. First-seen means first observed while matching this agent's filter. It is not historical availability or a guaranteed provider revision/retraction record. Changing filters or sharing a state file between different filters can suppress previously seen items; use `--state data/private/another-news-agent.sqlite` for an independent reader.

Source access: [NSE's RSS directory](https://www.nseindia.in/static/rss-feed) lists official company disclosure feeds. [ET's own RSS page and terms](https://economictimes.indiatimes.com/rss.cms) provides headlines/excerpts for personal access and restricts aggregation, commercial use and redistribution. This reader is for individual local use; do not publish its output or feed it to an external model without appropriate permission. It does not fetch full articles, bypass access controls, invoke an LLM or connect news to orders.

Offline verification:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_news_agent.py -v
```

## Faster collection

The collector targets a 30-second interval per healthy source. The dashboard reads
its local snapshot every five seconds. Network response time, sequential sources,
outage backoff and Retry-After can extend delivery. Publisher publication delays
and rolling RSS windows remain. This covers the three configured RSS sources.
Restart the local server to load a changed backend interval, then reconnect Kite.
Separate CLI instances also default to 30 seconds and accept that minimum.

## Dashboard integration

The local application starts its collector after binding its port. Dashboard refreshes and paper research read the latest snapshot. Each source has its own last success, failure count and retry schedule. Failed or overdue sources have their cached summaries separated from current evidence. Research and paper-worker checks consume eligible exact-mapped NSE context only. The dashboard keeps summary text in memory and stores only identity hashes and timestamps locally. Run one collecting application per installation to avoid duplicate requests from independent processes. See [worker operations](continuous-paper-worker.md) for permissions, setup and remaining evidence.

## Original NSE filings

The shared news snapshot now includes validated links to original NSE PDFs from
the RSS item link, enclosure or description anchor. In Market news, choose
News type -> NSE filings. Document labels classify RSS metadata; they are not
summaries or verification of PDF contents. PDFs are not automatically downloaded
or sent to an AI provider, and this adds no API subscription or PDF requests.

Attachment revisions update availability time. Stale and unmapped items stay
outside eligible research context. Paper journals keep hashes and timestamps,
not document text. This does not provide a complete historical filing archive.


Feed encodings: decoded as UTF-8 first; otherwise only a declared iso-8859-1/latin-1, windows-1252 or ascii encoding is accepted (strict). Everything else (UTF-16/32, UTF-7, unknown or missing declaration with invalid UTF-8, NUL bytes) is rejected, and the source health row reports `error: FeedEncodingError`. The DOCTYPE/ENTITY check runs on the decoded text.
