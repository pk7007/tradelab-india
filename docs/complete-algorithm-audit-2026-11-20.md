# TradeLab India — complete algorithm and gap audit

20 November 2026. Local working tree, before this audit's patches. ECC production-audit and verification-loop guidance applied locally; no external scanner, model connection, broker order, configuration change or installation. Inspection confidence moderate to high for named paths; runtime confidence limited to offline tests. Authenticated market sessions and deployed behavior UNVERIFIED. Existing baseline: 238 Python tests pass. Prior HTTP recovery fixture failed with Windows socket permissions; not a passing result. This review cannot prove every possible defect absent.

## A. Executive summary
A Python standard-library HTTP application with vanilla browser JavaScript and pinned kiteconnect 5.2.2. Three tabs expose research, watchlists and paper controls. The implemented trading rule is SMA5>SMA20 on completed closes, with next-bar modeled execution. It is a state condition, not necessarily a fresh crossover. Intraday v1 adds stops/targets, costs, volume participation, entry cutoff and observed-bar square-off. Most algorithms requested in the brief are absent or research heuristics. The system is suitable for bounded experimental paper use after setup; production/live operation remains blocked.

## B. Score and rubric
Scores assess the requested full trading platform, not profit probability. 0–2 absent/broken, 3–4 early/incomplete, 5–6 functional with major gaps, 7–8 strong but incomplete, 9–10 operationally mature. No mature-runtime score is warranted by mock tests.

| Category | Score /10 | Weight | Reason |
|---|---:|---:|---|
| Architecture |6|8|Separate research, paper and broker books; no unified authority|
| Market data |6|8|Kite history/stream and mapping; calendar, archive and entitlement operations incomplete|
| Algorithm coverage |2|4|SMA executable in simulation; requested families largely absent|
| Strategy correctness |5|7|Completed-close contract and cost sizing; bar-fill realism unproven|
| Regime detection |0|3|No integrated classifier or eligibility switching|
| AI/ML |1|2|Evidence schema only; disconnected provider|
| News intelligence |4|5|Real RSS adapters; basic categories, incomplete mapping and historical coverage|
| Risk management |5|15|Paper limits and mock reservations; no broker-wide authority|
| Backtesting |5|10|Chronological fixed baseline and exact paper replay; incomplete market costs/universe|
| Execution reliability |3|15|Durable intent reads and conflicts; live adapter locked|
| Multi-market support |1|3|NSE cash path; no safe derivatives lifecycle|
| Security |6|8|Loopback, CSRF, memory tokens, safe examples; history-secret status not certified|
| Testing |6|8|Offline regressions pass; coverage and authenticated E2E unverified|
| Production readiness |2|4|No sustained forward evidence, supervisor, restore evidence or unified execution|

Weighted score = sum(score × weight)/10 = 53.8/100. Weights total100. No architecture completion percentage is defensible without a finite agreed acceptance inventory; UNVERIFIED. Scores are judgment, not measured reliability or investment returns.

## C–F. Capability and defect matrix

| Component | State | Evidence | Gap / consequence | Severity; priority |
|---|---|---|---|---|
| Local API and UI |PARTIAL|app.py Handler; web/portal.js|Single-user local scope; deployment/auth roles not certified|High P0 for public deployment|
| Historical downloader |PARTIAL|market_data.py start_history/_history_worker/_save|Bounded jobs/storage; corporate adjustments not independently verified; no complete market archive|High P0|
| Streaming |PARTIAL|MarketData.start_stream/stream_status|SDK reconnect and freshness exist; stream is not worker candle-builder or durable gap journal|High P0|
| Instrument master |PARTIAL|MarketData.instruments/resolve|NSE equity resolution; point-in-time universe, lifecycle and price-band verification absent|High P0|
| Session calendar |PARTIAL|market_contract.session_for; PaperWorker.tick|Explicit supplied manifest only, no official importer, special sessions blocked|High P0|
| Paper ledger |PARTIAL|paper.py PaperEngine; intraday_contract.advance|Transactional bars/events and fills; assumed OHLC liquidity, independent balances|High P0|
| Continuous paper |PARTIAL|paper_worker.py; worker_runtime.py|Explicit arm, lease fencing, bounded catch-up; no sustained forward evidence or supervisor|High P0|
| Worker idle loop |BROKEN|WorkerRuntime.loop and PaperWorker.stop|After stop or fault loop repeats stop writes every30s; unnecessary journal growth|Medium P0 fix below|
| Offline risk gate |BROKEN|research.py ResearchRiskGate.check|Boolean amounts and truthy flags can pass; dangerous contract if reused for execution|High P0 fix below|
| Manual execution |PARTIAL, dispatch locked|app.py place_order; ExecutionJournal|Intent/order/trade matching; no certified shared funds, inventory or protective exits|CRITICAL if gate bypassed P0|
| Broker snapshot |PARTIAL|broker_snapshot.build_snapshot; /api/broker/snapshot|Read-only sequential snapshots, executionAllowed=false; no atomic ownership proof|CRITICAL if treated as authority P0|
| Funding reservations |STUB for production|automation.py SharedReservations, Coordinator.submit_mock|Working offline transactions but mock balances/execution only|CRITICAL live blocker P0|
| Order modify/cancel |MISSING integrated lifecycle|app.py route inventory; automation mock lifecycle|No complete real modify/cancel and confirmed emergency handling|CRITICAL live blocker P0|
| Portfolio risk |PARTIAL|trader_suite.risk_check, intraday_contract, ResearchRiskGate|No integrated sector/correlation, global drawdown, margin, consecutive loss or volatility breaker|CRITICAL live blocker P0|
| Evaluation |PARTIAL|evaluation.evaluate; intraday_evaluation.evaluate_intraday|Fixed baseline windows, holdout warnings, hashes; not independent strategy certification|High P0|
| Stress simulation |PARTIAL|validation_lab.simulate/stress_suite; trader_suite.time_machine|Scenario/return simulations; not every possible outcome or calibrated tail model|High P0|
| News reader |PARTIAL|news_agent.NewsAgent.poll_once; DashboardNews.status|NSE/ET/Google RSS, timestamps, hash dedupe, keyword categories; not full event archive or calibrated sentiment|Medium P1|
| News mapping |PARTIAL|DashboardNews.status|Exact NSE company-name mapping only; editorial text is not verified ticker mapping|High before signals P1|
| Moneycontrol |STUB/disconnected|syndication.SyndicationCache|Mock transport; private endpoint, paging, corrected-item retrieval and purge daemon absent|High before activation P1|
| AI guard |PARTIAL|evidence.validate_ai_research|Schema/citation/time checks, disconnected provider; no semantic truth/calibration|High before AI execution P2|
| Database operations |PARTIAL|SQLite schemas in paper/portal/journal/automation/registry/news|Persistence exists; no unified migrations, backup/restore acceptance or complete canonical archive|High P0|
| Monitoring |PARTIAL|worker health, events, stream status|No durable latency/error service metrics, watchdog or incident notification|High P0|
| CI/CD |PARTIAL|.github/workflows/checks.yml|Syntax/offline JS/Python checks; no authenticated acceptance, measured coverage or release evidence|High P0|
| Long-term service |STUB for recommendations|Portal.research long-term branch|Watchlist exists; fundamentals, valuation, governance, sector and dated filings missing|High P1|

No reachable live dispatch is claimed broken: the hard readiness gate deliberately blocks it. CRITICAL findings above are conditions that must block any future unlock, not claims that real orders occurred.

## G. Algorithm-by-algorithm audit

| Requested algorithm | State | Existing evidence and precise missing behavior |
|---|---|---|
| SMA baseline / Intraday v1 |PARTIAL, most mature|strategy_contract.target_long, assumed_fill; intraday_contract.advance; paper/evaluation use it. SMA5>SMA20 is a level condition; long-only; no validated edge. Stops fixed percent, target multiple, no ATR trail.|
| EMA/ADX trend |MISSING|No integrated EMA20/50/200, ADX14, ATR14, timeframe alignment or trailing stop engine. SMA is not an EMA substitute.|
| Momentum |PARTIAL research only|research.rank_universe uses20-bar return, volatility and turnover proxy. Missing benchmark-relative20/60-day ranking, ATR sizing, point-in-time universe and execution integration.|
| VWAP |MISSING|No session VWAP/bands/spread filters or strategy lifecycle found.|
| ORB |PARTIAL scanner only|trader_suite.signals checks09:15/20/25 high crossed by completed close. Fixed15min; lacks configurable5/30min, volume/ATR/false-breakout filters, own exits/backtest/dispatch.|
| Mean reversion |PARTIAL scanner only|Simple14-change RSI bounce heuristic; no Wilder validation, BB20,2, Z-score, range regime or standalone exit/sizing engine.|
| Statistical arbitrage |MISSING|No cointegration, hedge ratio, structural breaks, spread book or paired execution.|
| Supertrend |MISSING|No ATR Supertrend, parameterized timeframe/whipsaw engine.|
| ML |MISSING decision model|No active XGBoost/LightGBM/meta-labeling/calibration/drift pipeline. Chronological split and experiment utilities are not trained models.|
| RL |MISSING|No PPO/DQN; no sufficient case to prioritize RL.|

## H. Architecture and scope

Browser → local Handler → Portal research → scanner/plan/evidence. Broker login → memory token → MarketData history/stream. Explicit paper arm → WorkerRuntime → Kite completed candles → PaperWorker lease/calendar/freshness → PaperEngine → Intraday v1 → SQLite events/receipts. NewsAgent → cached dashboard/context; context never grants order authority. Manual preview → ExecutionJournal → locked place_order. Coordinator → mock broker + reservations remains a separate lane. Experiments → registry.

This supports a small personal research system. Scaling requires one account authority, broker-scoped limits and shared request budget, reconciliation ownership, bounded queues, migrations and service operations before more parallel strategies. Adding more algorithms does not supply those foundations.

Regimes: no integrated bull/bear/range/high-low volatility/news/gap classifier or automatic strategy selection. Price volatility is descriptive only. Cash NSE is the current mapped paper scope; manual NSE/BSE order validation is not safe complete BSE automation. Futures/options/currency/commodities lack contract lifecycle, lot/margin/rollover/MTM/greeks/chains/settlement and multi-leg safeguards. Unsupported segments must stay ineligible.

Risk: per-account capital/exposure, planned trade loss, daily marked-equity threshold, whole-share sizing, entry pause, observed square-off and stop/target modeling exist. There is no unified portfolio/sector/correlation/margin authority or guaranteed stop fill. User-approved ₹1000/₹25/₹100 are2.5% and10% of capital respectively; retained as explicit user limits, not silently replaced with the brief's illustrative defaults. No leverage/derivatives expansion is justified by this audit.

News is an information provider. Keyword earnings/corporate/macro labels are not sentiment probabilities, confidence calibration, verified event impact or AI explanations. Persisted first-seen hashes do not supply historical article text or point-in-time backtesting. Cross-source URL duplicates remain; rolling feeds do not prove completeness or retraction compliance. Treat content as untrusted data, escape UI text, prohibit tool/control instructions from model output, validate claims against an immutable citation registry and require deterministic risk approval if a model is ever connected. Regex alone is not a prompt-injection security boundary.

Backtests: fixed-SMA chronological windows, holdout cost stress, duplicate/gap validation, exact-engine intraday replay and experiment hashes exist. Missing verified corporate actions, survivorship-free universe, benchmark-relative intraday acceptance, complete statutory charge schedule, spread/order queue/circuit/market-impact calibration and paired/derivative simulation. Assumed next-open OHLC fills after a delayed candle receipt are retrospective modeled prices, not evidence of executable forward returns. No CAGR/Sharpe/Sortino/Calmar/profit factor or profit guarantee can be calculated credibly from the audit alone. Existing reports must disclose assumptions; no statistics fabricated.

## I–J. Dependency-aware roadmap: top20 fixes

Each task specifies files, dependency/data, acceptance/tests, risk/effort and blocking scope. S/M/L are relative effort, not delivery promises.

|# / priority|Task and files|Depends / data|Acceptance and tests|Risk / effort / blocks|
|---|---|---|---|---|
|1 P0|Stop repeated idle writes: worker_runtime.py|Existing worker status|Stopped ticks cause zero ledger writes; one failed active tick stops once|Medium S paper operations|
|2 P0|Strict risk types: research.py|Existing gate|Reject booleans/nonnumeric amounts and truthy flags before signal mutation|High S future live|
|3 P0|Recoverable private storage: scripts + DB modules|Actual configured paths; schema inventory|SQLite-consistent backup, restore, migration/version and corruption drill in isolated copy|High M paper/live|
|4 P0|Unify broker ownership: broker_snapshot.py, automation.py, journal|Fresh profile/orders/trades/positions/holdings/margins|One account ledger and unresolved mismatch block; concurrent/partial-fill tests|Critical L live|
|5 P0|Global server risk: automation.py, app.py|Task4; approved limits|Pending+filled exposure, equity loss and liquidation obligations survive restart; concurrency tests|Critical L live|
|6 P0|Confirmed exits/kill: execution_journal.py, app.py|4–5; broker lifecycle|Modify/cancel/reject/partial/protective coverage with uncertain responses; never equate request to flat|Critical L live|
|7 P0|Calendar importer: market_contract.py|Attributed official sessions and holidays|Unknown/special sessions fail closed; version/source freshness tests|High M paper/live|
|8 P0|Forward fill realism: paper.py, intraday_contract.py|Permitted arrival-time quotes/spreads|Separate bar replay from arrival-time execution simulation; no pre-receipt price claims|High L evidence/live|
|9 P0|Data integrity archive: market_data.py|Permitted history; corporate-action data|Versioned checksums, revisions, gaps, source provenance, corporate-action status tests|High M paper/live|
|10 P0|Authentic forward/restart acceptance: scripts/fixture_recovery.py, tests|3,7–9; connected paper only|Missing bars/outages/restart retain exposure and block unsafe entries; zero real orders|High M live|
|11 P0|Shared request budget: market_data.py/app.py|Official account-wide limits|429/backoff, token expiry and timeout tests across concurrent clients; no blind order retry|High M live|
|12 P0|Operations watchdog: worker_runtime.py, health UI|7,10; heartbeat/receipt metrics|Detect dead/stale worker independently, bounded events and restart policy|High M paper/live|
|13 P0|Benchmark and costs: evaluation.py/intraday_evaluation.py|9; dated statutory charges and benchmarks|Frozen unseen evaluation, cost/spread sensitivity, matched capital; no repeated holdout tuning|High L strategy promotion|
|14 P1|One ORB strategy using existing signals|7–13; completed volume/ATR observations|Configurable range and time filters, same paper/backtest contract and leakage tests|Medium M optional research|
|15 P1|Trend/momentum engine: research.py + versioned contract|9,13; NIFTY/sector benchmark|EMA/ADX/ATR and20/60-day relative strength individually verified then holdout tested|Medium L optional research|
|16 P1|VWAP/regime/arbitration: new feature module + existing paper|14–15; permitted intraday volume|Session reset, timezone/zero-volume tests, eligibility effects and capital contention tests|High L multi-strategy|
|17 P1|News health/mapping/revision: news_agent.py/dashboard_news.py|Licensed/allowed source/entity metadata|Per-source health, persistent availability provenance, no stale/retracted signals, source dedupe tests|High M before news signals|
|18 P1|Long-term evidence: portal.py/research.py|Dated filings, actions, fundamentals/valuation|As-of revenue/cashflow/debt/governance/sector comparisons with missing evidence visible|Medium L long-term recommendations|
|19 P2|ML meta-label research only + drift registry|13–18; sufficient chronological labels|Purged walks, calibration, reproducibility and simple baseline improvement on untouched holdout|High L optional; no live authority|
|20 P2/P3|Separate derivatives/portfolio then stat-arb/RL studies|4–13; licensed chains/contracts/margins/settlement|Defined maximum risk and multi-leg recovery before eligibility; independent research acceptance|Critical XL unsupported live segments|

Do not build all strategies simultaneously. Retain an explicit no-trade outcome. None of14–20 is a substitute for1–13.

## K. Verification plan and external requirements
Baseline existing safe Python suite executed:238 passed. Rerun focused regressions after patches then full offline Python/JS gates. Measure coverage only if tooling exists; no coverage percentage claimed. HTTP/browser and authenticated main-app acceptance remain separate; no broker login or worker activation performed by this audit. No CI remote status claim.

Official references checked20 November2026:
- Kite error/rate documentation: https://kite.trade/docs/connect/v3/exceptions/ — historical3req/sec, quotes1req/sec, placement10req/sec; per-minute/day/order-modification caps also apply. Existing0.4-second historical spacing covers only that local lane, not every API consumer.
- Order lifecycle: https://kite.trade/docs/connect/v3/orders/ — placement acknowledgement is not execution proof; orders/trades and lifecycle reconciliation required. Tagging must not be assumed to give broker idempotency.
- NSE FAQ: https://nsearchives.nseindia.com/web/sites/default/files/inline-files/FAQ_Retail%20Algo_03112025_NSE.pdf and SEBI rollout https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1759232056254.pdf. Current broker/exchange classification, static-IP mapping, rate/tagging and any registration obligations must be confirmed before a future live release. This is engineering review, not compliance certification. User's historical retention approval does not itself certify trading operations.

Security: current .env.example now uses placeholders; .env contents were not printed or changed. Prior credential-looking values in the example were observed earlier in the conversation. Whether they were real/published, rotated or remain in repository history is UNVERIFIED. Keep a potential exposure review open. No webhook authentication is certified because no production order-event webhook integration is established. Dependency vulnerability scan and external penetration test not performed.

## L. Final verdict
1. Proposed architecture completion: UNVERIFIED percentage; matrix is the bounded capability inventory.
2. Five biggest weaknesses: separate broker/paper funding authority; no real protective-exit orchestration; retrospective fill assumptions; incomplete calendar/data/cost provenance; missing sustained forward/restore evidence.
3. Most mature: fixed SMA5/20 and opt-in Intraday v1 simulation.
4. Next algorithms: reuse existing ORB heuristic as a separately tested paper contract; then benchmark-relative momentum/trend. VWAP follows data acceptance. No immediate RL.
5. Backtesting trustworthy? Useful for reproducible conditional experiments, insufficient for profit/live promotion.
6. Paper reliable? Offline transactional evidence is encouraging; unattended authenticated reliability remains UNVERIFIED.
7. Live safe to enable? No; readiness gate must remain false.
8. Production blocked by tasks3–13 and unresolved exposure/credential operational evidence.
9. Before more AI: data integrity, costs/benchmarks, account authority, exits, observability, restore/restart acceptance.
10. Build order: defects → storage/data/calendar → unified risk/reconciliation/exits → forward evidence → one additional strategy → regime/arbitration → optional ML/segments.

## Your next steps
Keep historical-retention permission recorded locally; it was supplied in chat and the local setting was enabled earlier. Restart the updated main app and confirm its actual DB paths and saved ₹1000/₹25/₹100 settings. If previously exposed example credentials were real, rotate them privately in Kite and update local configuration yourself. Connect Zerodha, create a fresh imported Intraday v1 paper account, choose explicit stock/cost/stop/target/share/time assumptions, supply a verified session manifest and arm only paper mode. Record full sessions and pause/restart/failure behavior; keep backups. No paid ML/news API is a prerequisite for this narrow paper milestone. Confirm broker compliance requirements only when live implementation is ready for separate review.

## TRADELAB INDIA — WHAT EXISTS, WHAT IS MISSING, WHAT TO FIX FIRST.
Exists: local research, SMA paper engine, completed-candle worker, RSS context, offline checks and locked broker scaffolding. Missing: validated edge, unified live funding/exits, mature data/calendar/operations and advanced strategy families. Fix worker/risk contracts first, then storage and forward evidence. No profit guarantee or live activation.

### app.py

- app.py:32 — def load_dotenv() -> None:
- app.py:74 — class KiteError(Exception):
- app.py:77 — class KiteSessionExpired(KiteError):
- app.py:81 — def kite_request(path: str, token: str, *, method: str = "GET", form: dict[str, Any] | None = None) -> dict[str, Any]:
- app.py:107 — def validate_order(values: dict[str, Any]) -> dict[str, Any]:
- app.py:166 — class Handler(http.server.BaseHTTPRequestHandler):
- app.py:169 — def log_message(self, _format: str, *args: Any) -> None:
- app.py:173 — def session(self) -> tuple[str, dict[str, Any]]:
- app.py:196 — def send_bytes(self, status: int, content: bytes, content_type: str, *, extra_headers: list[tuple[str, str]] | None = None) -> None:
- app.py:210 — def json_response(self, status: int, payload: dict[str, Any], *, cookie: str | None = None) -> None:
- app.py:214 — def error(self, status: int, message: str) -> None:
- app.py:217 — def redirect(self, location: str, cookie: str | None = None) -> None:
- app.py:226 — def body_json(self) -> dict[str, Any]:
- app.py:241 — def authenticated_session(self) -> tuple[str, dict[str, Any]]:
- app.py:252 — def connected_token(self, session: dict[str, Any]) -> str:
- app.py:258 — def valid_host(self):
- app.py:265 — def do_GET(self) -> None:
- app.py:294 — def api_get(self, route: str, query: dict[str, list[str]]) -> None:
- app.py:365 — def do_POST(self) -> None:
- app.py:587 — def begin_kite_login(self, session: dict[str, Any]) -> None:
- app.py:601 — def kite_callback(self, query: dict[str, list[str]]) -> None:
- app.py:637 — def place_order(self, session: dict[str, Any], values: dict[str, Any]) -> None:
- app.py:703 — class LocalServer(http.server.ThreadingHTTPServer):
- app.py:709 — def server_bind(self):
- app.py:715 — def serve() -> None:

### strategy_contract.py

- strategy_contract.py:7 — def target_long(closes):
- strategy_contract.py:12 — def assumed_fill(opening, units, side, fee_bps, slippage_bps):

### intraday_contract.py

- intraday_contract.py:9 — def validate(data):
- intraday_contract.py:28 — def advance(s, bar):
- intraday_contract.py:32 — def event(kind, **extra): events.append(dict(type=kind, bar=bar['date'], **extra))
- intraday_contract.py:43 — def fill(side, requested, raw, reason):

### paper.py

- paper.py:14 — class PaperEngine:
- paper.py:15 — def __init__(self, path):
- paper.py:31 — def db(self):
- paper.py:44 — def save(self, db, state, event):
- paper.py:48 — def load(self, db, identity):
- paper.py:54 — def create(self, data):
- paper.py:88 — def status(self):
- paper.py:95 — def control(self, identity, action):
- paper.py:120 — def fixture_link(self, identity, connected):
- paper.py:130 — def reconcile(self, identity):
- paper.py:134 — def fixture_batch(self, identity, instrument, bars, permitted):
- paper.py:146 — def reconcile_in(self, db, s):
- paper.py:196 — def ingest(self, identity, rows, permitted, *, fixture_instrument=None, transaction_guard=None):

### paper_worker.py

- paper_worker.py:20 — class PaperWorker:
- paper_worker.py:21 — def __init__(self, engine, fetch, clock=lambda: dt.datetime.now(UTC), lease_seconds=90):
- paper_worker.py:31 — def _now(self):
- paper_worker.py:36 — def status(self):
- paper_worker.py:55 — def start(self, account_id, instrument, calendar, retention_approved=False, calendar_confirmed=False):
- paper_worker.py:86 — def _assert(self,db):
- paper_worker.py:92 — def _record(self,**changes):
- paper_worker.py:99 — def stop(self):
- paper_worker.py:110 — def _ingest(self,rows,received,warmup):
- paper_worker.py:134 — def tick(self):

### worker_runtime.py

- worker_runtime.py:10 — class WorkerRuntime:
- worker_runtime.py:11 — def __init__(self,engine,market,announcements=None):
- worker_runtime.py:17 — def valid_session(self):
- worker_runtime.py:24 — def fetch(self,instrument,start,end):
- worker_runtime.py:38 — def record_news(self,instrument):
- worker_runtime.py:59 — def start(self,session_id,session,values):
- worker_runtime.py:77 — def loop(self):
- worker_runtime.py:82 — def tick_once(self):
- worker_runtime.py:93 — def stop(self):
- worker_runtime.py:99 — def stop_owner(self,session_id):
- worker_runtime.py:102 — def status(self):

### market_data.py

- market_data.py:20 — def date_range(start, end):
- market_data.py:29 — def chunks(start, end):
- market_data.py:37 — def clean_candles(rows):
- market_data.py:59 — class MarketData:
- market_data.py:60 — def __init__(self, api_key, root):
- market_data.py:77 — def client(self, token):
- market_data.py:81 — def instruments(self, token, query=''):
- market_data.py:91 — def resolve(self, token, symbol):
- market_data.py:98 — def start_history(self, owner, token, values):
- market_data.py:123 — def _history_worker(self, job, token, start, end):
- market_data.py:158 — def _save(self,job,symbol,instrument,rows):
- market_data.py:172 — def job(self,owner,job_id,symbol=None):
- market_data.py:183 — def cancel(self,owner,job_id):
- market_data.py:188 — def rank(self, owner, job_id, horizon, as_of):
- market_data.py:203 — def cancel_owner(self,owner):
- market_data.py:209 — def start_stream(self,owner,token,symbol):
- market_data.py:254 — def stream_status(self,owner):
- market_data.py:265 — def stop_stream(self,owner):
- market_data.py:275 — def _reaper(self):
- market_data.py:284 — def synthetic_research(values):
- market_data.py:298 — def simulate_rule(candles,fast,slow,cost,slip):

### research.py

- research.py:12 — def timestamp(value):
- research.py:19 — def validate_rows(rows, as_of):
- research.py:38 — def rank_universe(universe, horizon, interval, as_of):
- research.py:102 — def chronological_splits(count, label_horizon, minimum_train=60, test_size=20):
- research.py:110 — def experiment_record(config, dataset, report):
- research.py:120 — class ResearchRiskGate:
- research.py:125 — def __init__(self):
- research.py:131 — def check(self, signal, *, fresh, reconciled, exposure, pending, added,
- research.py:145 — def kill(self, pending_ids):

### trader_suite.py

- trader_suite.py:12 — def number(data,key,minimum=0):
- trader_suite.py:20 — def plan(data):
- trader_suite.py:37 — def risk_check(data):
- trader_suite.py:51 — def series(data):
- trader_suite.py:66 — def signals(rows):
- trader_suite.py:89 — def scan(data):
- trader_suite.py:102 — def time_machine(data):
- trader_suite.py:140 — def records(data):
- trader_suite.py:146 — def news(data):
- trader_suite.py:178 — def earnings(data):
- trader_suite.py:188 — def disclosures(data):
- trader_suite.py:201 — def dispatch(tool,data):

### evaluation.py

- evaluation.py:19 — def csv_candles(raw, symbol):
- evaluation.py:38 — def _number(data, key, default, lower, upper):
- evaluation.py:51 — def _completed(rows, interval, cutoff):
- evaluation.py:93 — def _portfolio(bars, signals, start, end, capital, fee_bps, slip_bps):
- evaluation.py:139 — def _window(bars, signals, start, end, capital, fees, slip):
- evaluation.py:149 — def evaluate(data):
- evaluation.py:186 — def data_hash(rows):
- evaluation.py:212 — def demo_request():

### intraday_evaluation.py

- intraday_evaluation.py:9 — def evaluate_intraday(request):

### broker_snapshot.py

- broker_snapshot.py:17 — def _stamp(value):
- broker_snapshot.py:26 — def _text(value, label, pattern=r'[A-Za-z0-9_-]{1,64}'):
- broker_snapshot.py:32 — def _number(value, label):
- broker_snapshot.py:38 — def _units(value, label, minimum=None):
- broker_snapshot.py:44 — def _data(payloads, name):
- broker_snapshot.py:53 — def _scope(row, *, holding=False):
- broker_snapshot.py:62 — def _list(payload, label):
- broker_snapshot.py:68 — def _position_map(rows, *, holding=False):
- broker_snapshot.py:82 — def _expected_map(value, label):
- broker_snapshot.py:88 — def build_snapshot(account, payloads, *, expected=None, as_of, received_at, max_age_seconds=30):

### dashboard_news.py

- dashboard_news.py:8 — class DashboardNews:
- dashboard_news.py:9 — def __init__(self,path,agent=None):
- dashboard_news.py:13 — def status(self,instruments=()):

### news_agent.py

- news_agent.py:39 — def plain_text(value: str, limit: int) -> str:
- news_agent.py:46 — def mentions(text: str, phrase: str) -> bool:
- news_agent.py:50 — def parse_et(raw: bytes, received: dt.datetime) -> list[dict]:
- news_agent.py:54 — def parse_google(raw: bytes, received: dt.datetime) -> list[dict]:
- news_agent.py:58 — def parse_editorial(raw: bytes, received: dt.datetime, hostname: str,
- news_agent.py:88 — class NoRedirect(urllib.request.HTTPRedirectHandler):
- news_agent.py:89 — def redirect_request(self, req, fp, code, msg, headers, newurl):
- news_agent.py:93 — def fetch_feed(url: str) -> bytes:
- news_agent.py:105 — class NewsAgent:
- news_agent.py:108 — def __init__(self, state: Path, sources=("nse", "et", "google"), watchlist=(), include_market=False,
- news_agent.py:127 — def poll_once(self) -> dict:
- news_agent.py:196 — def main(argv=None) -> int:

### automation.py

- automation.py:17 — def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
- automation.py:19 — def validate_config(raw):
- automation.py:45 — class Coordinator:
- automation.py:46 — def __init__(self,path):
- automation.py:58 — def db(self):
- automation.py:63 — def event(self,db,event,detail):db.execute('INSERT INTO audit(at,event,detail) VALUES(?,?,?)',(now(),event,detail))
- automation.py:64 — def save(self,values):
- automation.py:73 — def status(self):
- automation.py:83 — def control(self,action):
- automation.py:92 — def prepare(self,signal,version,symbol,quantity,price,snapshot):
- automation.py:125 — def submit_mock(self,identity,broker):
- automation.py:171 — def reconcile_mock(self,updates,external_mismatch=False):
- automation.py:205 — class SharedReservations:
- automation.py:212 — def __init__(self, path):
- automation.py:218 — def db(self):
- automation.py:227 — def schema(db):
- automation.py:235 — def paise(value, round_up=True):
- automation.py:242 — def reconcile(self, account, cash, inventory, external_mismatch=False):
- automation.py:259 — def reserve_in(cls, db, identity, account, book, instrument, side, units, value, fees=0):
- automation.py:282 — def reserve(self, identity, account, book, instrument, side, units, value, fees=0):
- automation.py:288 — def settle_in(db, identity, state, filled):
- automation.py:314 — def settle(self, identity, state, filled):
- automation.py:321 — def status(self):

### execution_journal.py

- execution_journal.py:13 — class ExecutionJournal:
- execution_journal.py:14 — def __init__(self, path):
- execution_journal.py:20 — def db(self):
- execution_journal.py:29 — def account(profile):
- execution_journal.py:34 — def list(self, account):
- execution_journal.py:40 — def prepare(self, account, review_id, order, login_digest):
- execution_journal.py:54 — def acknowledgement(self, identity, order_id=None):
- execution_journal.py:76 — def reconcile(self, account, orders, trades):

### evidence.py

- evidence.py:15 — class ProviderUnavailable(RuntimeError):
- evidence.py:20 — class DisconnectedResearchProvider:
- evidence.py:23 — def research(self, *_args, **_kwargs):
- evidence.py:27 — def _text(value, label, limit=2000):
- evidence.py:33 — def _stamp(value):
- evidence.py:40 — def validate_ai_research(output, evidence_registry, symbols, as_of, max_age_seconds):
- evidence.py:67 — def citation(identity):

### experiment_registry.py

- experiment_registry.py:9 — class ExperimentRegistry:
- experiment_registry.py:10 — def __init__(self, path):
- experiment_registry.py:16 — def record(self, report):

### portal.py

- portal.py:12 — class Portal:
- portal.py:13 — def __init__(self, path):
- portal.py:20 — def status(self):
- portal.py:27 — def update(self, values):
- portal.py:45 — def research(self, values):

### syndication.py

- syndication.py:19 — def stamp(value):
- syndication.py:26 — def identity(value):
- syndication.py:32 — class RateLimiter:
- syndication.py:33 — def __init__(self, interval=1.0):
- syndication.py:37 — def wait(self):
- syndication.py:43 — class SyndicationCache:
- syndication.py:44 — def __init__(self,path,transport,clock=lambda:dt.datetime.now(UTC),limiter=None):
- syndication.py:54 — def db(self):
- syndication.py:63 — def state(db,key):
- syndication.py:68 — def save_state(db,key,value):
- syndication.py:71 — def get(self,endpoint,since):
- syndication.py:77 — def poll(self,endpoint):
- syndication.py:122 — def revise(self,db,art,status,at):
- syndication.py:139 — def store(self,db,row,now):
- syndication.py:159 — def expire_if_unobserved(self,now=None):
- syndication.py:168 — def articles(self):
- syndication.py:174 — def sync_once(self):

## Repair and verification outcome

After recording the audit, patched WorkerRuntime.tick_once to skip inactive workers and prevent repeated stop writes; patched ResearchRiskGate.check to reject Boolean amounts and require literal True freshness/reconciliation flags. Added three targeted regression tests in tests/test_audit_regressions.py. Existing source configuration and broker keys were not changed.

Python:241/241 pass. JavaScript:six existing regression scripts pass. git diff --check:pass. HTTP restart fixture rerun:FAILED to execute its local HTTP check with WinError10013; target acceptance NOT VERIFIED. No type-check/lint/coverage or remote CI certification claimed. Main authenticated application, forward sessions and actual DB storage paths remain UNVERIFIED. The score is a pre-patch engineering assessment; two narrow fixes do not establish a validated trading edge or justify a maturity upgrade.

## TRADELAB INDIA — WHAT EXISTS, WHAT IS MISSING, WHAT TO FIX FIRST.

Exists: SMA5/20 Intraday v1 paper engine, Kite candle worker, RSS context, durable local ledgers and locked broker execution scaffolding. Missing: validated profitable strategy, unified broker risk/ownership/exits, complete market calendar/data provenance and authenticated forward/recovery evidence. Fixed now: repeated stopped-worker journal writes and permissive offline risk types. Next: storage recovery and calendar/data acceptance, then unified broker controls and forward paper evaluation.
