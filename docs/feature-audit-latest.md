# News Agent V2 audit — 20 November 2026

Baseline was frozen against the dirty working tree at commit `abc28e7` before implementation evidence was assessed. Scores express engineering judgment from source inspection and isolated tests. A 0 means no demonstrated implementation, 5 means bounded local capability, 8 requires repeatable end-to-end evidence and 10 requires sustained operational verification. Each applicable category has equal weight. Overall baseline **41.0/100** across 29 rated categories. LLM reasoning is inapplicable to the deterministic default.

| Category | Before /10 | After /10 | Baseline evidence and assessment boundary |
|---|---:|---:|---|
| Architecture | 6 | 7 | Collector, dashboard cache and context adapter exist; fetch under the dashboard lock couples request latency to providers. |
| Source quality | 6 | 6 | NSE filings are attributable; ET and Google items are editorial or aggregated. Measure publisher coverage and distinguish primary evidence. |
| Source coverage | 4 | 4 | Three RSS endpoints including one fixed Google query; BSE, regulator and licensed syndication delivery unverified. |
| Retrieval speed | 3 | 3 | Independent sequential fetches allow 15 seconds per endpoint; baseline provider timings unmeasured. |
| Freshness | 5 | 7 | Receipt and publication times are available; failed sources lose prior success visibility. Measure newest eligible item per source. |
| Data accuracy | 4 | 4 | Parser validates time and links; no independently labeled issuer or factual accuracy benchmark. |
| Duplicate detection | 5 | 6 | Stable source-plus-URL hash and content revision tracking; cross-source repeated coverage ungrouped. |
| Misinformation resistance | 3 | 3 | Allowlisted endpoints and publisher attribution; no demonstrated corroboration or contradiction checks. |
| Indian market understanding | 4 | 4 | Indian market keyword groups and NSE attribution; event-specific coverage incomplete. |
| Entity recognition | 4 | 4 | Exact unique NSE company-name title match; ambiguous issuers withheld. Measure recall against labeled filings. |
| Sentiment | 0 | 0 | No validated sentiment output. Use uncertain when evidence is insufficient. |
| Fundamental events | 3 | 3 | Keyword categories detect result and corporate-action terms; materiality unvalidated. |
| Market impact | 0 | 0 | No validated numerical impact model or test against subsequent price changes. |
| News-to-signal conversion | 3 | 3 | Eligible records join paper research context; incremental trading utility unmeasured. |
| Agent coordination | 4 | 6 | Modules share an adapter; request path owns collection, CLI is separate. |
| LLM reasoning | N/A | N/A | Deterministic implementation. No configured model evaluation or budget spend. |
| API integration | 5 | 5 | RSS parsers, fixed URLs, bounded fetch; authenticated Moneycontrol transport unprovisioned. |
| Database | 6 | 6 | SQLite identity cache and transactional licensed revisions; production retention operations unverified. |
| Scheduling | 3 | 6 | CLI watch loop exists; dashboard reads trigger refresh. Independent long-running service unverified. |
| Recovery | 4 | 6 | Parser failures isolated per source; failed-source cache discarded; persistent scheduler recovery unverified. |
| Security | 6 | 6 | NoRedirect, HTTPS host validation, bounded XML, no order authority; no complete production security assessment. |
| Trading risk controls | 7 | 7 | Context uses cutoff checks and executionAllowed=false; broker locks verified separately. |
| Backtesting | 4 | 5 | Revision availability recorded; identity-only RSS history cannot reconstruct past article text. |
| Observability | 3 | 6 | Per-source status and current response receipt available; outage erases visible last success. |
| Scalability | 3 | 3 | Bounded parsing and one local store; no measured concurrent provider or multi-process load. |
| Latency | 3 | 5 | Five-minute local cache; status can block on slow provider. Measure reader and processing time separately. |
| API cost efficiency | 7 | 8 | Zero model calls; five-minute dashboard cache. Independent pollers could repeat downloads. |
| Frontend integration | 5 | 6 | Portal requests news and displays freshness; stale versus unavailable distinctions limited. |
| Test coverage | 6 | 7 | Sixteen focused baseline tests pass; no dashboard-closed collector lifecycle proof. |
| Production readiness | 3 | 3 | Local bounded components; sustained delivery, provider rights and unattended deployment unverified. |

Primary evidence: `news_agent.py`, `dashboard_news.py`, `research_context.py`, `worker_runtime.py`, `syndication.py`, `web/portal.js` and their corresponding tests. The functional baseline was 16 passing news-related tests; source checks alone provide low confidence about deployed performance. See the feature gap matrix for the platform inventory and priority.

## After implementation

**47.9/100** (139 of 290 applicable points), up from **41.0/100** (119 of 290). The improvement is concentrated in scheduling, freshness, failure recovery and reader latency. The collector now runs while the local app is open even when nobody views its dashboard. Fifty successive dashboard reads and timer checks produced one fixture poll. Readers obtained a snapshot while a fake provider was blocked. The dashboard exposes stale exclusions and per-source retry times. Exact matching headline groups retain separate source identities. Historical import tests distinguish observation time from publication time and remove superseded symbol matches. The underlying keyword classifier is unchanged. No score increase was assigned for sentiment, price impact or production readiness. Full results are in the [verification record](feature-test-results.md).

## Operational observations

An existing backend answered a read-only GET of `/api/portal`. At approximately 14:36 IST its cached news summary reported a partial poll. ET had 50 parsed items and 14 age/watchlist-eligible items; Google had 38 and 7. NSE reported unavailable. These are provider poll timestamps. Publication-to-receipt freshness and research delivery of these particular items were not supplied by the cached endpoint. No user broker credentials or article text were requested. One successful observation cannot establish unattended availability across days.

| Operational claim | Baseline evidence |
|---|---|
| Source and backend start | Source inspected; main local backend responds and isolated HTTP fixture starts |
| Connected dependencies | Two RSS source successes observed in cached production status; NSE unavailable |
| Scheduled jobs and successful executions | CLI watch loop exists; recurring production news task ownership unverified |
| Fresh news processed | Feed reported 21 eligible item observations across two sources; uniqueness across sources unknown |
| Output reaches research | Controlled tests trace dated exact-symbol context to paper observability; delivery of a specific real filing unverified |
| Sustained operation | Requires deployed, timestamped records across restarts and outages |

### Licensed syndication

Twelve Moneycontrol mock-transport tests passed. They cover corrected text, permanent retraction tombstones, atomic cursor rollback, overdue revision handling, incomplete sweeps and competing syncs. Only tests instantiate the adapter. No provisioned production feed, licensed publisher text or authentication was used. Secure deletion in the adapter database acts on poll/read; a stopped process cannot guarantee a 24-hour purge or erase a separate backup. A future integration must verify scheduling, all content copies and purge recovery before licensed data is retained. RSS metadata and licensed text have separate storage boundaries. The review found no demonstrated P0 live-order path from incoming news.

### Measurement and cost

A synthetic offline timing sample fed the same 12 ET RSS items into a temporary SQLite database twenty times. Median parser-plus-deduplication time was **7.58 ms** per batch, maximum **9.17 ms**. The clock fixed publication-to-receipt age at 60 seconds; that age is a fixture input. The benchmark excludes network, reader rendering and contention. An author-labeled smoke panel gave micro precision **10/13**, recall **10/12** and F1 **0.80**. The 12 intended labels covered dividends, results, SEBI, Nifty, auditor appointment (other), split, factory opening (other), dividend cut, acquisition, resignation, rights issue and inflation. Multi-label predictions were scored as sets. This small convenience panel cannot establish accuracy on market news. Independent adjudication on a representative dated event set is outstanding.

At a five-minute healthy poll interval and 24-hour service, three sources produce up to 864 scheduled HTTP GETs/day per collector. Each interval requests a feed page and can return many articles. Separate CLI instances or processes increase the total. Backoff reduces requests during outages. For an illustrative 20 W incremental load and ₹8/kWh, continuous local electricity costs ₹3.84/day. Substitute measured watts and the operator’s tariff for budgeting.

| Articles/day | Paid LLM requests and fees | Data-provider cost | Illustrative local electricity/day |
|---:|---|---|---:|
| 100 | 0 / ₹0 | RSS contract cost unknown; Moneycontrol inactive | ₹3.84 |
| 500 | 0 / ₹0 | Same assumptions | ₹3.84 |
| 1,000 | 0 / ₹0 | Same assumptions | ₹3.84 |

Storage, internet, hardware depreciation, any hosting contract and existing broker subscription are excluded. No charges or subscriptions were incurred for this review. Simulated fills previously analyzed for TradeLab were price-only; the prior strategy loss cannot be attributed to headlines. No licensed point-in-time matched control/treatment dataset or candidate-specific forward quote evidence was established. Directional accuracy, regime performance, calibrated probabilities and profit improvement remain unverified.



## After implementation

**51.0/100** (148/290 applicable points, up from 119/290). Five collector lifecycle tests passed locally. They exercise collection without readers, duplicate tick suppression, nonblocking reads, stale evidence exclusion, recovery with and without provider retry guidance, and restart deduplication. The parent implementation timestamps successful receipt after download and tracks availability of the current revision. The ratings below credit isolated implementation evidence. Confidence in sustained operation is low until the deployed process has produced a session history.

| Category | After /10 | Evidence for assessment |
|---|---:|---|
| Architecture | 8 | Background collector and cache-only readers exercised together. |
| Source quality | 6 | Provenance distinguishes exchange and editorial coverage. Independent factual validation pending. |
| Source coverage | 4 | Same three configured RSS sources. |
| Retrieval speed | 3 | Background collection improves reader latency. Per-provider network speed remains unmeasured. |
| Freshness | 7 | Successful receipt and per-source staleness isolate old evidence. |
| Data accuracy | 4 | Synthetic classification sample only. |
| Duplicate detection | 6 | Story identity and restart behavior improved. Independently labeled collision and recall rates pending. |
| Misinformation resistance | 3 | Attribution helps inspection. Independent corroboration pending. |
| Indian market understanding | 4 | Existing India-specific deterministic vocabulary. |
| Entity recognition | 4 | Controlled exact-match and ambiguity cases only. |
| Sentiment | 0 | No measured sentiment model. |
| Fundamental events | 3 | Keyword-based labels only. |
| Market impact | 0 | No measured event-return model. |
| News-to-signal conversion | 4 | Fixture links a fetched disclosure to dated research context while stale material is excluded. |
| Agent coordination | 6 | Readers share collector output and simultaneous work is suppressed within a process. |
| LLM reasoning | N/A | Deterministic default. |
| API integration | 5 | Licensed production transport still pending. |
| Database | 7 | Stable identity and revision availability survive restart. |
| Scheduling | 7 | Background lifecycle and per-source retry timing exercised offline. |
| Recovery | 7 | Retry delay, outage exclusion and restart rehydration covered. |
| Security | 6 | Existing bounded transport. Production licensing and deployment still require verification. |
| Trading risk controls | 7 | News remains research-only. Real-money risk controls were outside this repair. |
| Backtesting | 5 | More faithful observation timestamps for corrections. Replayable licensed history is missing. |
| Observability | 6 | Per-source freshness, failure counts and collector-running state. |
| Scalability | 4 | Tests show repeated reads and overlapping polls share one process. No distributed load measurement. |
| Latency | 7 | A dashboard read completed during deliberately blocked provider I/O. No production percentile measured. |
| API cost efficiency | 8 | Repeated reads generate zero requests. Retry respects server delay. |
| Frontend integration | 6 | Portal can read current results from cache with separate stale items. |
| Test coverage | 7 | Five collector lifecycle scenarios plus existing parser, context and worker coverage. |
| Production readiness | 4 | Controlled restart and outage evidence. Sustained operation and financial utility are unverified. |

**Priority follow-up.** P1 operational verification requires running the updated service across market sessions, recording successful polls and outage recovery with the dashboard closed, and confirming one active collector per deployment. P1 licensed-feed activation requires real provisioning details, retention controls across all storage and regular revision sweeps. P2 research evaluation requires independent event labels and dated price observations, a frozen comparison against price-only signals, and net-of-cost results on a held-out period. Engineering scores cannot serve as estimates of trading returns.
