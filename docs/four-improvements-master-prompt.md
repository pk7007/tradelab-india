# TradeLab four-improvement execution prompt

Implement these four improvements in the existing working tree. Read AGENTS.md,
use the local graph for orientation, validate its findings against source, and
preserve saved accounts, limits and current user changes.

1. Connect the implemented intraday roles into durable reviewed handoffs for
   mapped instruments, completed observations, strategy research, position size
   and risk. Persist task IDs, input hashes, availability times, dependencies and
   verdicts with the entry decision. A failed required review blocks downstream
   entry tasks. Link consumed approvals and fills to that decision. Preserve
   protective exits and reconciliation during research failure. Distinguish this
   implemented intraday workflow from deferred long-term and news-driven models.
2. Add guided setup for an intraday paper profile using labeled fields and the
   user's saved limits, with a review before creating a paused account. Give
   recovery and health actions readable summaries. Keep advanced JSON tools
   available behind disclosures for workflows needing them.
3. Add durable operational alerts, acknowledgement and recovery history. Observe
   source/worker failures and stalled application heartbeats, deduplicate ongoing
   incidents, and make browser notification delivery explicit and optional.
   Verify current backup coverage and provide a safe isolated restore drill that
   never overwrites source ledgers. An independent local watcher may record app
   outages while the app is stopped. State delivery and host-availability limits.
4. Add local source and stock/keyword news filters, related-story grouping with
   attribution, relevance explanations and progressive loading. Preserve IST
   times, correction/staleness handling, keyboard focus and current source-health
   access. Distinguish verified ticker mapping from a keyword match.

Use bounded operations and existing APIs. Do not place broker orders, activate
trading, change existing financial limits, promote strategies, configure paid
services or send messages externally. Interactive login remains with the user.

Run focused regressions, the appropriate full offline suites and browser fixtures.
Use isolated databases for failure, restore and trading scenarios. Require one
independent reviewer, repair findings, and reuse that reviewer for rechecks.
Report each acceptance condition, changed files, verification, actual review score,
remaining dependencies and user actions. Do not turn a review target into an
unverified application or profitability claim.
