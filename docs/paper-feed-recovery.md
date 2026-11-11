# Paper feed recovery — fixture replay, 11 November 2026

Run `python scripts/fixture_recovery.py` from the project root. The command creates its own temporary database and local HTTP sessions; the two server processes use ephemeral ports, blank broker credentials and disabled live submission. It terminates both and removes the fixture database. It does not restart your existing app. Use `python -m unittest discover -s tests -q` for offline regressions.

## Observed

One explicitly synthetic instrument, fixed SMA(5/20), five-minute bars. Generated prices and demo-only capital/limits. After 20 bars the ledger contained a BUY intent but no shares. The adapter disconnected, the server process terminated, and a new app process reopened the ledger paused. The intent survived. After explicit reconnection and resume, a missing interval produced an error visible in the account feed state. Supplying the missing interval and two overlapping bars produced exactly one simulated fill. Retransmitting five bars produced zero new updates.

Starting with ₹10,000, the engine modeled a purchase of ten shares at ₹120.06 and a fee of ₹1.2006. The full fill journal independently reconstructed cash ₹8,798.1994, ten shares and fees ₹1.2006, matching the account. At the final invented close of ₹122, marked equity was ₹10,018.1994. Realized P&L was zero; the position remained open. This is an accounting test, not performance evidence.

## Portal and boundaries

On an updated server open `/trader-paper`. Create a new **Synthetic fixture** account, connect fixture replay, start ingestion, then submit completed bars. The panel shows the fixture instrument, connection state, exchange bar start, actual adapter receipt time, historical age at receipt, and last rejection. Disconnect does not cancel the intent or close shares. Verify balances from fills reads all journal entries, including those outside the recent-events display. A mismatch blocks new fixture ingestion.

The project has no verified provider entitlement covering continuous paper execution **and retention of incoming candles**. A Kite account or a chart subscription alone is not evidence of that permission. This adapter accepts historical fixture observations only. It is not a live scheduler, a market freshness monitor or broker reconciliation. The example account may hold overnight and is not an approved intraday mandate.

Still pending: a permitted real provider with exchange/receipt timestamps and session calendar; explicit separate intraday and long-term allocations, broker-wide reservation checks, external/manual reconciliation and live promotion gates. No account limits or live permissions were changed.
