"""Evidence-based live-trading readiness: metrics, 100-point score, hard blockers and a deployment decision.

Principles (all enforced by tests):
- Missing or unverifiable evidence earns NO credit. A claim counts only if it cites an existing repository file, and a
  test citation `path::Class::test_name` counts only if every named class or function exists in that file.
- Quantitative criteria are measured from completed trades, never claimed. Returns are built over EVERY elapsed session
  between the first and last trade (zero on sessions without trades), so a strategy that trades rarely cannot inflate
  its Sharpe, Sortino or Calmar. Risk-free rate is taken as zero.
- Trades, forward days and shadow days are supplied by the caller and are recorded as self-reported inputs with hashes.
  They are never inferred from backtests or fixtures.
- An open hard blocker caps both the decision and the classification. 100 points cannot override a blocker. Owner
  authorisation is the one blocker that eligibility does not require: it is what the owner gives AFTER eligibility, and
  the deployment state machine checks it at the real-money transition.
- `liveTradingPermitted` is always False here. Real activation needs the separate `LIVE_EXECUTION_READY` lock in app.py.
- No profitability claim is ever made.
"""
import datetime as dt
import hashlib
import json
import math
import random
import re
from pathlib import Path

TRADING_DAYS = 252
THRESHOLDS = dict(minHistoryYears=2.0, minTrades=300, minSharpe=1.5, minSortino=1.5, minProfitFactor=1.5, maxDrawdown=0.08,
                  minCalmar=1.0, minPaperDays=60, minShadowDays=10, minPaperTrades=300)
OWNER_GATE = 'human_authorisation'
GATE_IDS = ('forward_testing_days', 'independent_trade_sample', 'net_expectancy', 'maximum_drawdown', 'shadow_trading_days',
            'broker_compliance', 'order_reconciliation', 'disaster_recovery', 'security_vulnerabilities',
            'emergency_kill_switch', OWNER_GATE)

DOMAINS = dict(quant=20, backtest=15, risk=20, execution=15, reliability=10, ai=5, security=5, regulatory=5, monitoring=5)


def _c(identifier, domain, points, title):
    return dict(id=identifier, domain=domain, points=points, title=title)


CRITERIA = [
    _c('quant.history', 'quant', 2, 'At least 2 years of elapsed sessions tested'),
    _c('quant.trades', 'quant', 3, 'At least 300 independent out-of-sample trades'),
    _c('quant.sharpe', 'quant', 3, 'Annualised Sharpe at least 1.5 net of costs'),
    _c('quant.sortino', 'quant', 2, 'Sortino at least 1.5 net of costs'),
    _c('quant.profit_factor', 'quant', 2, 'Net profit factor at least 1.5'),
    _c('quant.drawdown', 'quant', 3, 'Maximum drawdown within 8%'),
    _c('quant.calmar', 'quant', 1, 'Calmar ratio at least 1.0'),
    _c('quant.expectancy', 'quant', 2, 'Positive net expectancy'),
    _c('quant.paper_days', 'quant', 2, 'At least 60 elapsed forward paper-trading days'),
    _c('backtest.walk_forward', 'backtest', 3, 'Chronological walk-forward with fixed parameters'),
    _c('backtest.costs', 'backtest', 3, 'Costs, slippage and participation modelled in simulation'),
    _c('backtest.lookahead_guard', 'backtest', 3, 'Look-ahead and leakage guards proven by tests'),
    _c('backtest.corporate_actions', 'backtest', 2, 'Corporate-action adjustment implemented and tested'),
    _c('backtest.cost_stress', 'backtest', 2, 'Results stress-tested at 1.5x, 2x and 3x costs'),
    _c('backtest.bootstrap', 'backtest', 2, 'Bootstrap confidence interval and risk of ruin run on a real strategy result'),
    _c('risk.entry_gate', 'risk', 5, 'Fail-closed deterministic entry gate independent of models'),
    _c('risk.kill_switch', 'risk', 4, 'Emergency kill switch that blocks entries and closes positions'),
    _c('risk.daily_loss', 'risk', 4, 'Daily loss limit enforced in the engine'),
    _c('risk.sizing', 'risk', 3, 'Risk-based position sizing with exposure limits'),
    _c('risk.period_limits', 'risk', 2, 'Weekly and monthly loss and drawdown suspension'),
    _c('risk.concentration', 'risk', 2, 'Sector, correlation and concentration limits'),
    _c('execution.idempotency', 'execution', 4, 'Idempotent order submission with duplicate prevention'),
    _c('execution.reconciliation', 'execution', 4, 'Broker position and trade reconciliation'),
    _c('execution.broker_status', 'execution', 4, 'Broker order-status, partial-fill and rejection handling'),
    _c('execution.restart_recovery', 'execution', 3, 'Safe restart and exposure recovery'),
    _c('reliability.ci', 'reliability', 3, 'Continuous integration runs the offline checks'),
    _c('reliability.crash_recovery', 'reliability', 3, 'Recovery from a crash mid-write verified'),
    _c('reliability.chaos', 'reliability', 4, 'Chaos and disaster-recovery scenarios verified'),
    _c('ai.no_direct_orders', 'ai', 3, 'No model output can become a broker order'),
    _c('ai.drift_calibration', 'ai', 2, 'Model drift and confidence calibration monitored'),
    _c('security.secrets', 'security', 2, 'No secrets in the repository; secret scanning'),
    _c('security.dependency_scan', 'security', 1, 'Dependency vulnerability scanning'),
    _c('security.audit_high', 'security', 2, 'Independent security audit with no open high findings'),
    _c('regulatory.sebi_nse', 'regulatory', 3, 'SEBI and NSE algorithmic-trading requirements verified from official sources'),
    _c('regulatory.zerodha_terms', 'regulatory', 2, 'Zerodha API terms, static-IP and order-tagging rules verified'),
    _c('monitoring.alerts', 'monitoring', 2, 'Durable alerts for exposure, token loss and outage'),
    _c('monitoring.readiness_dashboard', 'monitoring', 1, 'Readiness dashboard fed by real data'),
    _c('monitoring.daily_reports', 'monitoring', 2, 'Automatically scheduled end-of-day and weekly reports'),
]
BY_ID = {c['id']: c for c in CRITERIA}

# Scaling review needs successful LIVE testing, which this report cannot observe, so the classification stops at 94.
BANDS = ((90, 'ELIGIBLE FOR MICRO-LIVE APPROVAL'), (75, 'PAPER AND SHADOW TRADING'), (60, 'BACKTESTING ONLY'), (0, 'DEVELOPMENT ONLY'))
MICRO_LIVE = 'MICRO-LIVE ELIGIBLE — HUMAN APPROVAL REQUIRED'


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validated(trades):
    if not isinstance(trades, (list, tuple)):
        raise ValueError('Trades must be a list.')
    clean = []
    for trade in trades:
        if not isinstance(trade, dict) or not _finite(trade.get('net')):
            raise ValueError('Each trade needs a finite net P&L.')
        try:
            day = dt.date.fromisoformat(str(trade.get('day')))
        except ValueError:
            raise ValueError('Each trade needs an ISO day.') from None
        clean.append((day, float(trade['net'])))
    clean.sort(key=lambda item: item[0])
    return clean


def _sessions(first, last, trade_days, sessions):
    if sessions is not None:
        days = {dt.date.fromisoformat(str(day)) for day in sessions}
        if not trade_days <= days:
            raise ValueError('Every trade day must be one of the supplied sessions.')
        return sorted(day for day in days if first <= day <= last)
    weekdays = {first + dt.timedelta(days=n) for n in range((last - first).days + 1)}
    return sorted({day for day in weekdays if day.weekday() < 5} | trade_days)


def performance(trades, *, capital, sessions=None):
    """Net-of-cost metrics. `sessions` is the exchange calendar (ISO dates); without it every weekday in the span is a
    session, which counts holidays as idle days (conservative: it lowers the ratios). Unmeasurable ratios are None."""
    if not _finite(capital) or capital <= 0:
        raise ValueError('Capital must be positive.')
    clean = _validated(trades)
    nets = [net for _, net in clean]
    result = dict(tradeCount=len(clean), tradingDays=len({day for day, _ in clean}), sessions=0, netPnl=sum(nets),
                  winRate=None, profitFactor=None, expectancy=None, maxDrawdown=None, sharpe=None, sortino=None, calmar=None,
                  basis='daily returns over every elapsed session (zero when flat), risk-free rate 0, annualised with sqrt(252)')
    if not clean:
        return result
    gains = sum(n for n in nets if n > 0)
    losses = -sum(n for n in nets if n < 0)
    result.update(winRate=sum(1 for n in nets if n > 0) / len(nets), expectancy=sum(nets) / len(nets),
                  profitFactor=gains / losses if losses > 0 else None)
    by_day = {}
    for day, net in clean:
        by_day.setdefault(day, []).append(net)
    calendar = _sessions(clean[0][0], clean[-1][0], set(by_day), sessions)
    result['sessions'] = len(calendar)
    equity, peak, worst, daily = float(capital), float(capital), 0.0, []
    for day in calendar:
        start = equity
        for net in by_day.get(day, []):
            equity += net
            peak = max(peak, equity)
            worst = max(worst, (peak - equity) / peak)
        daily.append((equity - start) / start)
    result['maxDrawdown'] = worst
    if len(daily) >= 2:
        mean = sum(daily) / len(daily)
        deviation = math.sqrt(sum((r - mean) ** 2 for r in daily) / (len(daily) - 1))      # sample deviation
        if deviation > 0:
            result['sharpe'] = mean / deviation * math.sqrt(TRADING_DAYS)
        downside = math.sqrt(sum(min(r, 0.0) ** 2 for r in daily) / len(daily))           # target 0, all sessions
        if downside > 0:
            result['sortino'] = mean / downside * math.sqrt(TRADING_DAYS)
    if worst > 0:
        result['calmar'] = (result['netPnl'] / capital) * (TRADING_DAYS / len(calendar)) / worst
    return result


def bootstrap_expectancy(trades, *, seed=0, samples=2000, minimum=10):
    """95% percentile bootstrap interval for mean net P&L per trade; (None, None) when the sample is too small.
    Assumes trades are independent; serially correlated trades make the interval too narrow."""
    nets = [net for _, net in _validated(trades)]
    if len(nets) < minimum:
        return None, None
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(nets, k=len(nets))) / len(nets) for _ in range(samples))
    return means[int(0.025 * samples)], means[int(0.975 * samples) - 1]


def risk_of_ruin(trades, *, capital, ruin_fraction, seed=0, paths=1000, minimum=10):
    """Share of bootstrapped paths (as long as the sample) whose equity falls to capital * (1 - ruin_fraction), measured
    from STARTING capital, not from a later peak. A simulation of the observed sample, not a forecast."""
    nets = [net for _, net in _validated(trades)]
    if len(nets) < minimum or not _finite(capital) or capital <= 0 or not 0 < ruin_fraction < 1:
        return None
    rng = random.Random(seed)
    floor = capital * (1 - ruin_fraction)
    ruined = 0
    for _ in range(paths):
        equity = float(capital)
        for net in rng.choices(nets, k=len(nets)):
            equity += net
            if equity <= floor:
                ruined += 1
                break
    return ruined / paths


def _status(value, ok):
    return 'unverified' if value is None else 'pass' if ok else 'fail'


def quant_criteria(perf, forward_days, thresholds=THRESHOLDS):
    perf = perf or {}
    t = thresholds
    sessions = perf.get('sessions') if perf else None
    drawdown = perf.get('maxDrawdown')
    items = [
        ('quant.history', _status(sessions or None, (sessions or 0) / TRADING_DAYS >= t['minHistoryYears'])),
        ('quant.trades', _status(perf.get('tradeCount'), (perf.get('tradeCount') or 0) >= t['minTrades'])),
        ('quant.sharpe', _status(perf.get('sharpe'), (perf.get('sharpe') or 0) >= t['minSharpe'])),
        ('quant.sortino', _status(perf.get('sortino'), (perf.get('sortino') or 0) >= t['minSortino'])),
        ('quant.profit_factor', _status(perf.get('profitFactor'), (perf.get('profitFactor') or 0) >= t['minProfitFactor'])),
        ('quant.drawdown', _status(drawdown, drawdown is not None and drawdown <= t['maxDrawdown'])),
        ('quant.calmar', _status(perf.get('calmar'), (perf.get('calmar') or 0) >= t['minCalmar'])),
        ('quant.expectancy', _status(perf.get('expectancy'), (perf.get('expectancy') or 0) > 0)),
        ('quant.paper_days', 'pass' if forward_days >= t['minPaperDays'] else 'fail' if forward_days else 'unverified'),
    ]
    return [dict(id=i, status=s, detail='measured' if s != 'unverified' else 'no measurement available') for i, s in items]


def source_ok(source, root):
    """A repository file, optionally with `::Name` parts that must each be defined in that file."""
    if not isinstance(source, str) or not source:
        return False
    path, *names = source.split('::')
    if not path or path.startswith(('/', '\\')) or ':' in path or '..' in Path(path).parts:
        return False
    try:
        target = (Path(root) / path).resolve()
        target.relative_to(Path(root).resolve())
    except (ValueError, OSError):
        return False
    if not target.is_file():
        return False
    if names:
        text = target.read_text(encoding='utf-8', errors='replace')
        return all(re.fullmatch(r'\w+', n) and re.search(r'^\s*(?:def|class)\s+%s\b' % n, text, re.M) for n in names)
    return True


def _open(blockers, *, ignore_owner):
    return [b for b in blockers if b.get('status') != 'clear' and not (ignore_owner and b.get('id') == OWNER_GATE)]


def decide(score, blockers):
    """Eligibility. Owner authorisation is not required for eligibility; every other blocker is."""
    if not _open(blockers, ignore_owner=True) and score >= 90:
        return MICRO_LIVE
    if score >= 75:
        return 'PAPER TRADING READY'
    if score >= 60:
        return 'BACKTEST READY'
    return 'NOT READY'


def classify(score, blockers=()):
    capped = score if not _open(blockers, ignore_owner=True) else min(score, 89)
    return next(name for floor, name in BANDS if capped >= floor)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode('utf-8')).hexdigest()


def assess(evidence, performance, forward_days, shadow_days, *, root, human_authorisation=None, now=None,
           thresholds=THRESHOLDS, trades_digest=None):
    evidence = evidence if isinstance(evidence, dict) else {}
    results = {item['id']: item for item in quant_criteria(performance, forward_days, thresholds)}
    for criterion in CRITERIA:
        if criterion['id'] in results:
            continue
        claim = evidence.get(criterion['id'])
        claim = claim if isinstance(claim, dict) else {}
        if claim.get('status') == 'pass' and source_ok(claim.get('source'), root):
            results[criterion['id']] = dict(id=criterion['id'], status='pass', source=claim['source'], detail=str(claim.get('detail', '')))
        elif claim.get('status') == 'fail':
            results[criterion['id']] = dict(id=criterion['id'], status='fail', source=claim.get('source'), detail=str(claim.get('detail', '')))
        else:
            reason = 'cited source missing or invalid' if claim.get('status') == 'pass' else str(claim.get('detail', 'no verified evidence'))
            results[criterion['id']] = dict(id=criterion['id'], status='unverified', source=None, detail=reason)
    criteria = []
    domain_scores = {name: 0 for name in DOMAINS}
    for criterion in CRITERIA:
        item = dict(results[criterion['id']], domain=criterion['domain'], points=criterion['points'], title=criterion['title'])
        item['awarded'] = criterion['points'] if item['status'] == 'pass' else 0
        domain_scores[criterion['domain']] += item['awarded']
        criteria.append(item)
    score = sum(domain_scores.values())
    perf = performance or {}
    passed = lambda *ids: all(results[i]['status'] == 'pass' for i in ids)  # noqa: E731
    gates = [
        ('forward_testing_days', forward_days >= thresholds['minPaperDays'], 'Elapsed forward paper days: %s of %s.' % (forward_days, thresholds['minPaperDays'])),
        ('independent_trade_sample', (perf.get('tradeCount') or 0) >= thresholds['minTrades'], 'Independent trades: %s of %s.' % (perf.get('tradeCount') or 0, thresholds['minTrades'])),
        ('net_expectancy', (perf.get('expectancy') or 0) > 0, 'Net expectancy must be measured and positive.'),
        ('maximum_drawdown', perf.get('maxDrawdown') is not None and perf['maxDrawdown'] <= thresholds['maxDrawdown'], 'Drawdown must be measured and within the limit.'),
        ('shadow_trading_days', shadow_days >= thresholds['minShadowDays'], 'Shadow days: %s of %s.' % (shadow_days, thresholds['minShadowDays'])),
        ('broker_compliance', passed('regulatory.sebi_nse', 'regulatory.zerodha_terms'), 'SEBI/NSE and Zerodha requirements are not verified from official sources.'),
        ('order_reconciliation', passed('execution.reconciliation', 'execution.broker_status'), 'No verified broker-side order and position reconciliation.'),
        ('disaster_recovery', passed('reliability.chaos'), 'Disaster-recovery scenarios are not verified.'),
        ('security_vulnerabilities', passed('security.audit_high'), 'No independent security audit with zero open high findings.'),
        ('emergency_kill_switch', passed('risk.kill_switch'), 'Emergency kill switch is not verified against real positions.'),
        (OWNER_GATE, isinstance(human_authorisation, dict) and human_authorisation.get('by') == 'owner'
         and isinstance(human_authorisation.get('text'), str) and bool(human_authorisation['text'].strip()),
         'No explicit owner authorisation for real-money activation is recorded (checked again by the state machine).'),
    ]
    blockers = [dict(id=i, status='clear' if ok else 'blocked', detail=detail) for i, ok, detail in gates]
    return dict(generatedAt=(now or dt.datetime.now(dt.timezone.utc)).isoformat(), score=score,
                classification=classify(score, blockers),
                domains=dict((n, dict(score=domain_scores[n], max=DOMAINS[n])) for n in DOMAINS), criteria=criteria,
                blockers=blockers, decision=decide(score, blockers), liveTradingPermitted=False,
                forwardTesting=dict(forwardDays=forward_days, requiredDays=thresholds['minPaperDays'], shadowDays=shadow_days,
                                    requiredShadowDays=thresholds['minShadowDays']),
                performance=performance, thresholds=dict(thresholds),
                missingEvidence=[c['id'] for c in criteria if c['status'] == 'unverified'],
                lineage=dict(evidenceSha256=_digest(evidence), tradesSha256=trades_digest,
                             selfReported=['trades', 'forwardDays', 'shadowDays'],
                             note='Trades and day counts are supplied by the caller. Backtest trades are not forward evidence.'),
                requiredHumanApprovals=['Real-money activation', 'Any capital scaling', 'Promotion of any strategy or model'],
                claimsProfitability=False,
                note='Eligibility report only. It cannot place orders, promote a strategy, change limits or enable live trading.')
