# Model-assisted news assessment (`news_intelligence.py`)

Status: offline module with 18 tests. It is **not yet wired into the news agent, app or
paper worker**, and no real model call has been made. Nothing here can place an order.

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

## Not yet done
- Real-provider check: `anthropic_completer` is untested against the live API. It needs a key
  supplied through the secure credential form, never chat or the repo.
- Wiring into the news agent and dashboard, persistence of assessments, and spend reporting.
- Historical evaluation of whether labels predict price behaviour. Until then they are context only.
- Models may wrap JSON in code fences. Such replies are rejected on purpose; measure the rate before relaxing.
