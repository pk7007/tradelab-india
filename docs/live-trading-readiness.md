# Live-trading readiness

Status on 24 November 2026: **NOT READY. Score 41/100 (DEVELOPMENT ONLY), with 11 open hard blockers.**
Real money stays locked: `LIVE_EXECUTION_READY = False` in `app.py`, and nothing in this work changes it.

Regenerate at any time (offline, read-only):

```
python scripts/readiness_report.py --markdown
python scripts/readiness_report.py --trades trades.json --capital 100000 --forward-days N --shadow-days M
```

## How the score works (`live_readiness.py`)
- 100 points across nine domains: quantitative performance 20, backtesting 15, risk 20, execution 15, technical
  reliability 10, AI 5, security 5, regulatory 5, monitoring and recovery 5.
- **Missing evidence earns nothing.** A non-quantitative criterion counts only if `docs/readiness-evidence.json` marks it
  `pass` and cites an existing repository file. A test citation `path::Class::test_name` counts only if each named class
  and test is defined in that file. Paths outside the repository earn nothing. A tool that exists but has not been run
  on a real result (bootstrap, cost stress) or a report that nothing schedules earns nothing.
- **Quantitative criteria are measured, never claimed**, from completed trades with net P&L after all costs: Sharpe,
  Sortino, net profit factor, maximum drawdown, Calmar, expectancy, win rate, a bootstrap 95% interval for expectancy and
  a bootstrap risk of ruin at an 8% loss from starting capital. Returns cover **every elapsed session** between the first
  and last trade (zero on idle sessions; every weekday unless an exchange calendar is supplied), so a strategy that
  trades rarely cannot inflate its ratios. Risk-free rate 0; Sharpe uses the sample deviation, Sortino the downside
  deviation over all sessions; both annualised with the square root of 252. Unmeasurable ratios are `null`.
- Trades, forward days and shadow days are **self-reported** inputs. The report records them as such with hashes
  (`lineage`). Backtest trades are not forward evidence, and day counts must be real elapsed sessions.
- Thresholds are the conservative project defaults from the readiness prompt (300 trades, Sharpe 1.5, Sortino 1.5,
  profit factor 1.5, drawdown 8%, Calmar 1.0, 60 paper days, 10 shadow days). They are project choices, not universal
  standards.

## Hard blockers
Any open blocker caps the decision at PAPER TRADING READY and the classification below the micro-live band, however
high the score. Owner authorisation is the exception: it is given after eligibility, so it does not cap eligibility,
and the state machine checks it again at the real-money step. The classification never reaches the scaling band,
because that needs successful live testing that this report cannot observe.

Open today: forward-testing days (0 of 60), independent trades (0 of 300), net expectancy (unmeasured), maximum
drawdown (unmeasured), shadow days (0 of 10), broker compliance (not verified from official sources), order
reconciliation (no broker-side reconciliation), disaster recovery (no chaos suite), security vulnerabilities (no
independent audit), emergency kill switch (offline latch only, never closed a real position), owner authorisation.

## Deployment state machine (`deployment_state.py`)
DEVELOPMENT, BACKTEST, VALIDATION, PAPER, SHADOW, MICRO_LIVE_PENDING_APPROVAL, MICRO_LIVE, CONTROLLED_LIVE,
SCALING_PENDING_APPROVAL, plus SUSPENDED and EMERGENCY_STOP.
- Ladder stages cannot be skipped, and leaving SUSPENDED goes back to VALIDATION or DEVELOPMENT, so revalidation
  cannot be skipped after a suspension.
- Pending approval needs a complete readiness report no older than 24 hours: micro-live eligible, score at least 90,
  every gate present and clear except owner authorisation. Its digest and summary are stored in the audit trail.
- MICRO_LIVE, CONTROLLED_LIVE (including scaling) and leaving EMERGENCY_STOP need `actor='owner'` and a written approval.
- Suspension and emergency stop are always allowed. `risk_breach` suspends, a critical one stops, and it never raises.
- A material change (strategy, model, execution or risk) is always recorded: PAPER and SHADOW go back to VALIDATION,
  pending and real-money states are suspended.
- A restart never resumes a pending, real-money or scaling state; an unknown stored state fails closed to SUSPENDED.
  A second instance opened on the same file also suspends such a state (safe by design).

**What it cannot do:** authenticate the caller. `actor` and the approval are recorded labels, not proof of identity;
code holding the object could pass them. The real protections are that nothing in the application calls the owner-only
transitions and that orders stay behind `LIVE_EXECUTION_READY = False`. It records decisions and is not wired into the
order path.

## What the readiness prompt asked for that is NOT done yet
- No official SEBI, NSE, BSE or Zerodha source has been checked in this work. Regulatory status is UNRESOLVED and blocks live.
- No shadow mode, no live-data forward test, no 60-day paper record, no real trades. Profitability is NOT VALIDATED.
- No weekly or monthly loss limits, drawdown or consecutive-loss suspension, sector or correlation limits.
- No broker-side order reconciliation, chaos or disaster-recovery suite, crash-mid-write test, or capital-level
  (Rs 1,000 to Rs 5,00,000) cost model.
- No readiness dashboard in the web interface; this report is the command-line version.
- The 15 separate documents the prompt lists are not produced; this document, `docs/reporting.md`,
  `docs/supervision.md` and `docs/strategy-ema-adx.md` hold the verified content so far.

## Next steps in order (none can be skipped by writing code)
1. Owner: run supervised paper sessions from 25 November and keep the end-of-day reports (`scripts/eod_report.py`);
   scheduling them with Task Scheduler is an owner action.
2. Code: weekly, monthly and drawdown suspension plus a consecutive-loss stop in the paper engine (reviewed phase).
3. Done in Phase 7 (`docs/proposals-and-live-path.md`): a no-order-call guard and a mock-only kill and reconciliation path. Broker-side reconciliation against Zerodha is still missing.
4. Owner or adviser: verify SEBI retail-algo rules, NSE requirements and Zerodha API terms from official sources and record the URLs.
5. Elapsed time: 60 paper days and 300 trades, then 10 to 20 shadow days. Only then can the quantitative blockers clear.
6. Owner only: a written decision to request micro-live, recorded through the state machine.
