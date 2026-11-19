# Current capability map — 20 November 2026

This map describes current source and evidence. Running servers may use an older backend until restarted. A connected badge, mock test or module on disk does not establish production readiness. See [gap audit](gap-audit-2026-11-20.md) and [external-source plan](external-source-plan.md).

| Route/component | Status | Actual boundary |
|---|---|---|
| `/`, `/intraday` | Verified offline; browser spot checks | Saved ₹1,000/₹25/₹100 planning limits, import-based candidate sizing and automatic eligible NSE context per research request. No continuous market-wide scanner or recommendation service. |
| `/long-term` | Verified offline | Persistent watchlist; fundamentals/valuation/sector evidence missing. Insufficient evidence and no automatic purchases. |
| `/auto-trading` | Verified offline | Durable paper summaries, costs, protection, entry/exit controls and history. Actual account-specific model shown. Explicitly armed completed-candle paper worker with lease fencing and news context; no production service supervisor or broker dispatch. |
| Settings | Verified offline | Editable portal planning limits; old candidate sizing invalidated; existing paper account limits unchanged. |
| `/advanced` | Broker reads previously verified; execution mock-only | Account, positions, holdings, quotes/history and old control room. On 19 November login, account reads, INFY quote and three daily candles succeeded. Current broker session not accessed during audit. |
| `/trader-paper` | Verified offline | New opt-in Intraday v1 and legacy accounts. Stops/partial fills/square-off are modeled on imported candles. Independent account capital; no actual shared broker ownership. |
| `/trader-evaluate` | Verified offline | Fixed daily SMA and matched holding benchmark; local report history and repeated holdout warning. No validated edge. |
| `/api/trader/evaluate-intraday` | Verified offline | Same-engine temporary replay, unresolved exposure retained. No independent holdout/benchmark certification. |
| `/api/announcements` | Public RSS fetch previously verified; parser mock tests | Rolling NSE summaries, five-minute in-memory cache, exact loaded NSE EQ mapping. Stale/failed evidence labelled. No archival/retraction/completeness SLA. |
| `/api/portal/research` | Verified offline | Explicit candles/plans/risk snapshots and eligible point-in-time RSS context. AutoEligible false; no orders. |
| `syndication.py` | Mock-only/disconnected | Revision-safe private cache and bounded response validation. Real Moneycontrol endpoint/credentials and pagination absent; no runtime feed or purge daemon. |
| `evidence.py` | Offline validator only | Citation/symbol/time/schema validation. No model connected, semantic truth not certified. |
| `market_contract.py` | Offline validator only | Quote freshness and explicit session manifest. No calendar importer or production source entitlement. |
| `Coordinator` shared funding | Mock-only | Atomic cash/share/fee reservation and uncertain-order tests. No authoritative broker snapshots or strategy position ownership. |
| Manual execution journal | Mock lifecycle; broker read adapter | Durable intent/order/trade correlation; contradictory identities remain UNKNOWN. Live dispatch locked; positionsReconciled false. |
| Other `/trader-*` tools | Verified offline/import-only | Legacy compatible research/planning pages under Advanced. Their presence is not connected news, live scanner or a second automatic trading system. |

## Required operating distinctions

Paper/live, token configured/authenticated, current data, reconciled ownership and approved strategy are separate states. Entry pause permits exit processing; stop/pause ingestion leaves exposure held. Requested exits remain pending until modeled fills. Daily limits and protective prices are not guaranteed loss caps. Imported historical data is not forward evidence.

No real broker orders, new model connection, private Moneycontrol calls or GitHub publication occurred during this audit. No existing account was migrated or repriced.

## Paper worker and news integration update

See [continuous paper operations](continuous-paper-worker.md). The new multi-source news agent is connected through /api/news-agent to Intraday research and worker context. Read-only broker snapshots are non-atomic and never enable execution. Offline evidence: 238 Python tests and six JavaScript regression scripts pass. Sustained authenticated forward evidence remains missing.
