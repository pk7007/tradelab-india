# Model-assisted news assessment (`news_intelligence.py`)

Status: offline module (18 tests) plus an opt-in service (`news_assessor.py`, 12 tests) wired into
the app's news hub. **Off by default.** No real model call has been made. Nothing here can place
an order, and the paper worker and risk gates do not read these labels.

## What it does
Given an item from `news_agent.py`, it asks an injected completion function for a JSON label
(sentiment, event type, confidence, symbols, a verbatim quote, a one-line rationale) and returns
a result with `executionAllowed: false`.

## Guards (each covered by a test)
- Article text is fenced as untrusted data. Any `article` tag in it, in any case or spacing, is neutralised. Fencing reduces prompt-injection risk but does not remove it; the schema, quote and symbol checks still apply to every reply.
- The reply must match a strict schema. Extra keys (for example an `action`) are rejected.
- The quote must appear verbatim in the article, and symbols must be in the allowed set. An 8-character minimum quote is weak grounding, so treat it as a sanity check, not proof the label is right.
- `availableAt` is never earlier than the article's own `availableAt`, so replays do not look ahead.
- A call budget stops spending. Failed calls still count.
- Provider errors return `unavailable` and never raise, so required exit processing is unaffected.

## Wiring (`news_assessor.py`, `integrated_news.py`)
- Enabled only when `TRADELAB_NEWS_AI=true` **and** `ANTHROPIC_API_KEY` are set and `anthropic`
  is installed (`requirements-ai.txt`). Otherwise `/api/news-agent` reports
  `intelligence.status` as `disabled`, `missing-key` or `missing-package` and nothing is called.
- A background thread labels current items every 60 s: at most 5 per cycle and 100 per UTC day
  (both configurable). The daily count is stored, so restarts do not reset it.
- An item is labelled once per revision, and a label is shown only for the revision it was made for.
  Provider failures back off per item (1 min, doubling to 1 h, kept in memory) so one bad item cannot
  starve others or burn the daily cap; rejected replies are recorded and not retried.
- Only RSS items are labelled. Licensed-feed items carry no text and are skipped.
- Invalid or negative limit settings fall back to the defaults instead of stopping the app.
- Only the item's own exact NSE-mapped symbols are allowed in a label; unmapped items get none.
- `/api/news-agent` items gain an `assessment` field (sentiment, eventType, confidence, symbols,
  availableAt, executionAllowed=false) plus an `intelligence` summary.
- The private store `news-assessments.sqlite` holds ids and labels only: no article text, no quote
  (a hash instead) and no free-text rationale.
- Storage is created lazily on first use (never at import or construction), so an unwritable data
  directory cannot stop the app. If storage cannot be opened, `intelligence.status` is `unavailable`
  with a short `reason`, labels are omitted and `tick` never raises; a locked database keeps the
  status and reports `reason` "busy". A deleted database file is recreated on the next call.
- A service that is not enabled (`disabled`, `missing-key`, `missing-package`) never touches disk, so
  it does not show labels stored by an earlier enabled run. Trade-off: no file or directory is created
  for a feature that is off; re-enable the service to see old labels again.
- Reads (`/api/news-agent`) never wait for a provider call; `tick` is single-flight and a second
  concurrent tick is skipped.
- The portal news list shows each label (sentiment, confidence, event type) as an "Automatic research label (not advice)" line, plus a one-line intelligence status (web/portal.js; tests/news-labels.test.js).

## Not yet done
- Real-provider check: `anthropic_completer` is untested against the live API. It needs a key
  supplied through the secure credential form, never chat or the repo.
  Fixed 23 Nov 2026: the completer passed `temperature=0`, which the pinned SDK
  (anthropic>=2.12, API version 2026-10-21) does not accept, so every enabled call raised
  `TypeError` and was recorded as `unavailable`. It now sends no sampling parameters, uses
  `output_config.effort='low'` and `max_tokens=1024`, and reports a `refusal` or `max_tokens`
  stop as `unavailable` (`IncompleteReply`). An offline test binds the request to the installed
  SDK signature. A live call is still unverified.
- Dashboard display, token-level spend reporting (the cap counts calls, not tokens or cost), and a daily cap tied to a currency amount.
- Historical evaluation of whether labels predict price behaviour. Until then they are context only.
- Models may wrap JSON in code fences. Such replies are rejected on purpose; measure the rate before relaxing.
