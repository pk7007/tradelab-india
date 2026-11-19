# Three-tab portal

The main workspace is consolidated into Intraday, Long-term and Auto Trading. The previous control room remains available at `/advanced`; useful existing tool URLs remain compatible for diagnostics and research. No existing accounts or journals are deleted or migrated.

Intraday research uses explicit imported candles and trade plans. Results must disclose their observation cutoff, costs, assumptions and missing liquidity/news evidence. Empty or insufficient evidence is a valid result. Long-term watchlists remain research-only until fundamental and valuation evidence is available.

The user's saved intraday planning settings are ₹1,000 capital, ₹25 planned loss per trade and ₹100 daily loss threshold. They are editable and do not allocate long-term funds or activate trading. Existing paper accounts retain their own settings. Their fixed-SMA model lacks protective per-trade stops, so the portal must not imply that ₹25 is enforced on those legacy accounts.

Auto Trading exposes the durable paper account state and controls. Starting permits imported-candle processing; a continuous data scheduler is not connected. Entry pause preserves exit eligibility; pause/stop ingestion does not close shares. A requested close waits for the next accepted candle. Broker live dispatch remains locked pending the integration described in `system-repair-2026-11-18.md`.

Kite connection, data setup, evaluations, raw imports and diagnostics belong under Settings/Advanced. AI and continuous publisher news are disconnected. No synthetic research result should be presented as a current stock recommendation.

## Setup and verification

Restart the local server to load the new portal backend, then open `/`. The separate isolated preview at `http://127.0.0.1:8773/` uses temporary databases and blank broker credentials. Saved settings/watchlists use `%LOCALAPPDATA%/TradeLabIndia/portal.sqlite` by default, or `TRADELAB_PORTAL_DB`. The portal never modifies an existing paper account's capital. Use Settings to reach broker login and advanced data tools; keep secrets in the local environment file.

Verified on 19 November 2026: 148 Python tests passed, the existing three JavaScript regression scripts passed, and portal JavaScript syntax passed. Eight portal tests cover persisted settings, costs/whole shares, risk boundaries, stale/unaffordable and missing-plan outcomes, symbols, zero volume, future news and long-term watchlist boundaries. The HTTP fixture checked the new primary routes, advanced/evaluation compatibility, default limits and paper restart recovery. Browser checks exercised the three tabs, their empty/disconnected states, saved-limit form and direct route reload. Screenshots of all three views were captured during inspection. Broader device/accessibility tests and authenticated broker operations were not exercised in this pass.

The full product brief remains incomplete where it requires licensed feeds, fundamental/valuation research and unified live execution. This redesign surfaces existing capabilities rather than fabricating recommendations or claiming those integrations are finished. Auto Trading still processes explicit imported candles; account creation/import is available in its expandable setup section. No GitHub publication occurred.
