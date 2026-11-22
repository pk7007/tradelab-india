# Unattended paper-session approval inventory

Start authorizes one account, one session and its saved strategy and limits.
The scheduled supervisor sends the same authenticated Start request. Runtime
decisions carry the identities of the services that performed them.

| Authority or decision | Previous behavior | Current automatic path | Verification |
| --- | --- | --- | --- |
| Broker login and provider retention | Broker login and local retention setting, plus a checkbox on every Start | Interactive login supplies market-data access. Start reads the saved retention setting and the server's reviewed calendar. An explicitly supplied custom calendar still needs confirmation. | HTTP saved-permission and CSRF tests |
| Session ownership | Repeated Start returned the current run before checking the caller. Browser inactivity could interrupt market-data access. | Repeated Start checks the owning broker grant. The worker has an in-memory grant for the session date. Disconnect cancels unfilled entries and revokes it. | Selector standing-grant and competing-owner tests |
| Selection and entry | Deterministic selection and sizing. Retrospective role reports arrived after decisions. | Selection, research and risk services review each proposed worker BUY. The review is bound to one pending intent with evidence, quantity and expiry. The fill checks the current limits and evidence again. | Entry-review tests and browser replay |
| Protective orders | Paper engine processes stops, targets, partial exits and square-off | Exits use the deterministic paper engine independently of entry reviewers. An accepted square-off observation triggers automatic end and reconciliation. | Outage test, partial-exit regressions and browser replay |
| Pause, End and restart | Manual controls and worker fencing. Pause before stock selection lived only in memory. | Operator controls retain priority. Preselection pause survives restart. Recovery checks ownership and exposure before new entries. | Selector restart, pause, end and recovery tests |
| Desk health queue | Every completed monitor task waited for a human review, eventually filling the desk backlog | The desk verifies its own monitoring output against the recorded observations. The service records a separate verdict with no strategy or financial authority. | Desk coordinator test |
| Research task certification | Generic task dependencies wait for accepted reviews. Promotion uses its own certification procedure. | The automatic BUY path uses dedicated bounded service reviews. User-submitted research and agent certification retain their own review workflow. | Agent service tests and unattended replay |
| Legacy paper drafts | User types APPROVE PAPER ORDER in the manual planner | The automatic session uses the managed account and paper ledger. The manual planner has its own draft and confirmation. | HTTP session tests and browser request log |
| Live orders and strategy changes | Separate live-order confirmation, hard live readiness lock and strategy-lab controls | A paper review cannot place broker orders, change limits or promote a strategy. | Order, strategy-lab and execution tests |

The existing intraday strategy uses completed prices. News items are advisory.
The review receipt and modeled fill time are distinct. When a review completes
after a bar opens, that open is ineligible for the new approval. A pending BUY
can shrink or expire. Protective exits still require an available price and
modeled liquidity. An unresolved position remains visible.
