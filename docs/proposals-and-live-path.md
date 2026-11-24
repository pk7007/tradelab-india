# Improvement proposals and the mock-only live path (Phase 7)

Nothing in this phase can place, modify or cancel a real order, change a running strategy, or change a limit.

## 1. Broker order paths are confined to reviewed sites (`order_guard.py`)
`tests/test_order_guard.py` parses every tracked Python file (AST) and scans every tracked JavaScript and HTML file.
It fails on any of these outside a counted allowlist:
- a reference to a Kite order-mutation method (`place_order`, `modify_order`, `cancel_order`, `exit_order`, GTT and
  position-conversion calls), called or only referenced (aliases such as `po = kite.place_order`);
- a string naming such a method or an SDK route key (`'order.place'`, `'gtt.delete'`), which covers
  `getattr(kite, 'place_order')` and the SDK's private `_post`;
- a string containing the Kite API host;
- a call carrying a Kite order, GTT or position path (relative or full URL) that writes: a non-GET or variable
  `method=`, a body keyword, a write verb (`post`, `put`, `patch`, `delete`), or a positional body to `Request`/`urlopen`;
- dynamic dispatch on a broker client, `getattr(<x>.client(...), <name>)`.

The allowlist counts occurrences, so a second call in an allowed function also fails. Its five sites:
| Site | Why it is allowed | Protection checked by the test |
|---|---|---|
| `app.py` module `KITE_API` | host constant | none needed |
| `broker_transport.fetch_json` host check | refuses any other host | none needed |
| `Handler.do_POST` route to `place_order` | the existing local order handler | see next row |
| `Handler.place_order` POST `/orders/regular` | the only order submission | `LIVE_ORDERS_ENABLED`, `LIVE_EXECUTION_READY` and the `PLACE LIVE ORDER` confirmation are direct early returns before the call; `LIVE_EXECUTION_READY` is bound once, at top level, to `False`, never rebound or declared `global` |
| `AutoSelector.request` dynamic dispatch | market-data calls for selection | its first statement refuses any method outside `READ_ONLY_METHODS = {historical_data, quote}`; a test proves `place_order` and others are refused before the client is touched |

The test also proves that no project module imports `app` (statically or by name), so no model, news or agent code
can reach the handler. The typed confirmation is a constant phrase a session client sends, not proof that a human is
present; the real lock is `LIVE_EXECUTION_READY = False`, which only a separately reviewed change may alter.

Known limits: a static check cannot follow names built at runtime (`exec`, a method name assembled from pieces), and
client tracking for dynamic dispatch covers only a client created inline or assigned to a local variable in the same
function; a client stored on `self`, passed as a parameter or held at module level is not tracked. Order-method names,
SDK route keys and the broker host are still flagged in every form, and the paths that exist today are covered by the
dispatcher allowlist and the live lock.

## 2. Improvement proposals (`improvement_proposals.py`)
Reads frozen experiment records (`experiment_registry.py`) read-only and applies fixed rules:
holdout reused, too few trades (under 30), costs at least as large as the result, fails doubled costs, trails
buy-and-hold in every window, results change sign between windows, unreadable or non-numeric record.

Run `python scripts/propose_improvements.py`. New proposals are appended to
`%LOCALAPPDATA%\TradeLabIndia\proposals\proposals.jsonl`; an output path inside the repository is refused unless it is
under `data/private`. Each proposal says `status: proposed`, `requiresOwnerReview: true`,
`appliesAutomatically: false`, `claimsProfitability: false`. It deliberately does not use the incident inbox, so a
research notice can never fail the end-of-day paper report.

What makes it unable to change anything: it imports only the standard library (no engine, no inbox), opens the registry
read-only (a test proves a write through that connection is refused), and has no apply or promote function. Acting on
a proposal is a separate, reviewed change. Runs are serialised with a lock file, one unreadable row becomes an
`unreadable-report` proposal instead of stopping the run, and a partial last line is closed before appending.

## 3. Kill with confirmed closure and reconciliation, mocks only (`live_mock.py`)
- `kill_with_confirmation(gate, broker)` kills the risk gate first (entries blocked), cancels working orders, requests
  exits, then takes a new snapshot. It reports CONFIRMED_FLAT only when that snapshot has a strictly newer revision than
  the pre-kill one (or nothing needed doing) and shows no position and no working order. Any state other than
  COMPLETE, CANCELLED or REJECTED counts as working. An exit is held while a same-side order of that symbol failed to
  cancel, so a stuck stop and an exit cannot both fill. Partial or rejected exits, failed cancels, stale or malformed
  snapshots, an unreachable broker, or a rejected position row all give NOT_CONFIRMED with the residual exposure. It
  never raises, and any broker whose `mode` is not `offline-mock` is refused before it is touched.
- `reconcile(ledger, snapshot)` reports position differences, orders missing at the broker, unknown orders at the
  broker (for example manual orders), fill differences, order-detail differences and working-versus-terminal state
  differences. Orders must carry id, symbol, side, quantity, filled and state. Any difference or unreadable input
  blocks new entries only; exits and square-off are never blocked.
- Protective stops are covered separately by `execution_controls.ensure_protection_mock` and its stricter snapshot
  contract (`ExecutionControls.observe`: monotonic revision, receipt within 5 s). A live adapter must satisfy both.
- Rate limits: `api_rate_limits.py` (with its tests) is the limiter. Kill cancel and exit bursts are not yet routed
  through it; a live adapter must do so, because Kite limits the order rate.

## Limits
- All of this is exercised with fixtures and mocks. No live adapter exists, nothing calls `kill_with_confirmation` with
  real positions, and broker-side reconciliation against Zerodha remains a readiness blocker.
- The guard scans git-tracked files: a new module is covered once it is added to Git (CI always sees it).
