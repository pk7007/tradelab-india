"""Improvement proposals from frozen research experiments. Proposals only: nothing is ever applied.

Reads the experiment registry through a read-only SQLite connection (rows there are append-only records of past
evaluations), attributes each result with fixed, documented rules, and appends new proposals to a JSON-lines file in
the private folder (`scripts/propose_improvements.py`). It does not use the incident inbox: research notices are not
operational failures and must not fail the end-of-day paper report.

It cannot change a running strategy, a loss limit, a paper account or any configuration: it imports no engine, opens
no writable database, has no "apply" function, refuses an output path inside the repository (except data/private),
and every proposal says `appliesAutomatically: false` and `requiresOwnerReview: true`. Acting on a proposal is a
separate, reviewed change. No profitability claim is made.

Runs are serialised with a lock file; one bad registry row becomes an `unreadable-report` proposal instead of stopping
the run; a partial last line in the output (for example after a crash) is closed before new lines are appended.
"""
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
import time
from pathlib import Path

MIN_TRADES = 30
ROOT = Path(__file__).resolve().parent
LOCK_WAIT_SECONDS = 10
STALE_LOCK_SECONDS = 600
NUMERIC_FIELDS = ('returnPct', 'completedTrades', 'fees', 'slippage')


def _readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5)


def experiments(registry_path):
    """Frozen experiment rows. Missing registry -> []. An unreadable registry raises ValueError."""
    if not Path(registry_path).exists():
        return []
    try:
        with contextlib.closing(_readonly(registry_path)) as db:
            rows = db.execute('SELECT id, created, holdout, report FROM experiments ORDER BY id').fetchall()
    except sqlite3.Error as error:
        raise ValueError('Experiment registry could not be read (%s).' % type(error).__name__) from None
    views, result = {}, []
    for identity, created, holdout, body in rows:
        views[holdout] = views.get(holdout, 0) + 1
        try:
            report = json.loads(body)
        except (TypeError, ValueError):
            report = None
        result.append(dict(id=identity, created=created, holdoutViews=views[holdout], report=report))
    return result


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _malformed(strategy):
    return [k for k in NUMERIC_FIELDS if k in strategy and _num(strategy[k]) is None]


def attribute(experiment):
    """Fixed rules for one experiment -> list of findings (rule, evidence, suggestion). Never raises."""
    try:
        return _attribute(experiment)
    except Exception as error:  # one bad row must not stop the run
        return [dict(rule='unreadable-report', evidence=dict(error=type(error).__name__),
                     suggestion='The stored experiment could not be interpreted; re-run it.')]


def _attribute(experiment):
    report = experiment.get('report')
    if not isinstance(report, dict):
        return [dict(rule='unreadable-report', evidence={}, suggestion='The stored experiment could not be read; re-run it.')]
    holdout = report.get('holdout') if isinstance(report.get('holdout'), dict) else {}
    strategy = holdout.get('strategy') if isinstance(holdout.get('strategy'), dict) else {}
    stress = report.get('stressHoldout') if isinstance(report.get('stressHoldout'), dict) else {}
    stress = stress.get('strategy') if isinstance(stress.get('strategy'), dict) else {}
    bad = _malformed(strategy)
    if bad:
        return [dict(rule='unreadable-report', evidence=dict(nonNumericFields=bad),
                     suggestion='The stored experiment has non-numeric results; re-run it.')]
    capital = _num(report.get('capital'))
    ret, trades = _num(strategy.get('returnPct')), _num(strategy.get('completedTrades'))
    costs = (_num(strategy.get('fees')) or 0) + (_num(strategy.get('slippage')) or 0)
    findings = []
    if experiment.get('holdoutViews', 1) > 1:
        findings.append(dict(rule='holdout-reused', evidence=dict(views=experiment['holdoutViews']),
                             suggestion='This holdout has been viewed before; treat the result as in-sample and test on new, unseen data.'))
    if trades is not None and trades < MIN_TRADES:
        findings.append(dict(rule='too-few-trades', evidence=dict(completedTrades=trades, minimum=MIN_TRADES),
                             suggestion='Too few trades to judge anything; extend the sample before drawing conclusions.'))
    if capital and ret is not None and costs > 0 and 100 * costs / capital >= abs(ret):
        findings.append(dict(rule='costs-dominate', evidence=dict(costPctOfCapital=round(100 * costs / capital, 6), returnPct=ret),
                             suggestion='Fees and slippage are at least as large as the result; review trade frequency and the cost model.'))
    stressed = _num(stress.get('returnPct'))
    if ret is not None and stressed is not None and ret > 0 >= stressed:
        findings.append(dict(rule='fails-doubled-costs', evidence=dict(returnPct=ret, stressedReturnPct=stressed),
                             suggestion='The holdout result does not survive doubled costs and slippage; it is not robust.'))
    validation = report.get('validation') if isinstance(report.get('validation'), list) else []
    windows = [w for w in validation if isinstance(w, dict)] + ([holdout] if holdout else [])
    excess = [_num(w.get('excessReturnPct')) for w in windows]
    if excess and all(e is not None and e < 0 for e in excess):
        findings.append(dict(rule='trails-benchmark', evidence=dict(excessReturnPct=excess),
                             suggestion='The rule trails buy-and-hold in every window; consider retiring or redesigning it.'))
    returns = [_num(w['strategy'].get('returnPct')) for w in windows if isinstance(w.get('strategy'), dict)]
    if len({r > 0 for r in returns if r is not None and r != 0}) > 1:
        findings.append(dict(rule='unstable-across-windows', evidence=dict(returnPct=returns),
                             suggestion='Results change sign between windows; the behaviour is not stable.'))
    return findings


def _proposal_id(experiment, rule):
    report = experiment['report'] if isinstance(experiment.get('report'), dict) else {}
    key = '%s|%s|%s|%s' % (experiment['id'], experiment.get('created'), report.get('fingerprint'), rule)
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]


def _clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def _existing(path):
    ids = set()
    if Path(path).exists():
        for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                ids.add(json.loads(line)['id'])
            except (ValueError, KeyError, TypeError):
                continue
    return ids


def _check_output(path):
    target = Path(path).resolve()
    private = (ROOT / 'data' / 'private').resolve()
    try:
        target.relative_to(ROOT)
    except ValueError:
        return target
    try:
        target.relative_to(private)
    except ValueError:
        raise ValueError('Proposals are private: write them outside the repository or under data/private.') from None
    return target


@contextlib.contextmanager
def _lock(target):
    lock = target.with_name(target.name + '.lock')
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            handle = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except (FileExistsError, PermissionError):   # Windows reports a lock being deleted as PermissionError
            try:
                if time.time() - lock.stat().st_mtime > STALE_LOCK_SECONDS:
                    lock.unlink()
                    continue
            except OSError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError('Another proposal run is in progress.') from None
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(handle)
        with contextlib.suppress(OSError):
            lock.unlink()


def propose(registry_path, out_path, *, now=None):
    """Append proposals not written before and return them. Serialised by a lock file next to the output."""
    target = _check_output(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    stamp = (now or dt.datetime.now(dt.timezone.utc)).isoformat()
    rows = experiments(registry_path)
    with _lock(target):
        known = _existing(target)
        new = []
        for experiment in rows:
            report = experiment['report'] if isinstance(experiment['report'], dict) else {}
            for finding in attribute(experiment):
                identity = _proposal_id(experiment, finding['rule'])
                if identity in known:
                    continue
                known.add(identity)
                new.append(_clean(dict(id=identity, createdAt=stamp, experimentId=experiment['id'],
                                       experimentCreated=experiment['created'], symbol=report.get('symbol'),
                                       fingerprint=report.get('fingerprint'), status='proposed', requiresOwnerReview=True,
                                       appliesAutomatically=False, claimsProfitability=False, **finding)))
        if new:
            needs_newline = target.exists() and target.stat().st_size and not target.read_bytes().endswith(b'\n')
            with target.open('a', encoding='utf-8') as handle:
                if needs_newline:
                    handle.write('\n')
                for proposal in new:
                    handle.write(json.dumps(proposal, sort_keys=True, allow_nan=False, default=str) + '\n')
    return new
