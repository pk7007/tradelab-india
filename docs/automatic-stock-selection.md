# Automatic paper stock selection

The Auto Trading screen provides automatic selection using a saved imported
Intraday v1 account as the assumptions template. It uses that account's capital,
loss limits, costs, share cap, participation and stop/target distances.
Start requires an authenticated local session and retention confirmation.

The selector obtains the broker's current NSE cash-equity instrument master.
It reads quote snapshots in batches of at most 500 and skips missing, stale,
non-positive-volume or unaffordable quotes. It orders eligible names by
last price multiplied by cumulative volume and fetches five-minute histories for
the top 20. Coverage counts distinguish quotes from histories actually checked.
This is a whole-universe quote screen followed by a bounded candle shortlist.

Completed contiguous candles must begin at session open. The same SMA 5/20
condition as Intraday v1 determines eligibility. Ranking uses the percentage
spread between the two averages. Cost-aware whole-share sizing and modeled volume
participation must permit at least one share. Twenty completed candles are needed,
so the earliest normal 09:15 session selection is 10:55. No result is a valid outcome.
Quotes and history share a conservative request throttle. A scan repeats at
five-minute intervals until a stock qualifies or the entry cutoff passes.

One stock is selected for each session. A durable reservation and deterministic
account identity recover an interrupted account creation without duplicating it.
The existing fenced worker processes its candles, uses warm-up without new
entries and applies existing stop, target, daily loss and exit rules. Re-ranking
does not switch an account with an open position or pending exit.

The next session carries forward the prior selected account's reconciled cash,
capped at the original capital and exposure allocations. Historical accounts
remain as separate records and cannot be manually re-armed through worker APIs.
They are earlier allocations in the same experiment. Do not sum their
historical balances as simultaneous spendable funds. Unresolved exposure,
accounting mismatch or a changed broker identity blocks the next allocation.

The provided calendar uses a conservative 15:15 research-window end for reviewed
regular cash sessions. It is deliberately shorter than some securities' full
continuous hours. Auctions are excluded. The template needs a 15:05 square-off
for observation at 15:10. Unknown days block processing. Suspensions, special
sessions and changes in official hours still require calendar verification.

The selector starts disarmed after restart. It has no broker order methods.
The market quotes and worker data paths require Monday's observed acceptance.
Offline tests cover fresh selection, next-bar paper fills, duplicate suppression,
stale/gapped history, funding carry after loss, restart, interrupted creation,
cutoff and calendar rejection. No live quotes were requested during that testing.

Use GET /api/auto-selection for state. POST /api/auto-selection/preview takes
templateAccount, calendar, permitted, candles and asOf for offline ranking.
POST /api/auto-selection/start takes templateAccount, calendar and permitted.
POST /api/auto-selection/control accepts pause_entries, resume_entries or
end_session. POST /api/auto-selection/stop aliases end_session: it blocks new
entries, requests closure and continues protective processing until flat and
reconciled. Missing observations or authorization leave exposure visibly
unresolved. All writes use the existing local session, Origin and CSRF
protections. Process shutdown preserves holdings and pending exits for recovery.

Ranking is experimental. News remains research context. No profitability or
complete event-coverage claim follows from these tests.
