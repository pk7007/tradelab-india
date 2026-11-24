"""Persistent, audited deployment state machine (development to controlled live).

What it enforces (tests/test_deployment_state.py):
- Live trading is disabled by default; ladder stages cannot be skipped, and leaving SUSPENDED goes back through
  VALIDATION (or DEVELOPMENT), so revalidation cannot be skipped after a suspension or a material change.
- Entering MICRO_LIVE_PENDING_APPROVAL needs a complete, fresh (24 h) live_readiness report: decision micro-live
  eligible, score at least 90, every gate present, and every gate clear except owner authorisation. A digest and summary
  of that report are stored in the audit trail.
- MICRO_LIVE, CONTROLLED_LIVE (including scaling) and leaving EMERGENCY_STOP need actor='owner' plus a written approval.
- Suspension and emergency stop are always allowed; `risk_breach` is idempotent and never raises in EMERGENCY_STOP.
- A material change to a strategy, model, execution logic or risk setting is always recorded and forces revalidation;
  its reason is shortened, never refused.
- The `evidence` audit column is new: a database created by an earlier draft of this module is refused loudly
  (sqlite OperationalError), never resumed.
- A restart never resumes a pending, real-money or scaling state; an unknown stored state fails closed to SUSPENDED.
  Opening a second instance on the same file therefore suspends a running real-money state (safe, by design).

What it does NOT do: authenticate who is calling. `actor` and the approval are labels recorded in the audit trail; any
code holding this object could pass them. The real protections are that nothing in the application calls the owner-only
transitions, and that order placement stays behind `LIVE_EXECUTION_READY = False` in app.py, which only a separately
reviewed change may alter. This module records deployment decisions; it does not place or enable orders.
"""
import datetime as dt
import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import live_readiness

LADDER = ['DEVELOPMENT', 'BACKTEST', 'VALIDATION', 'PAPER', 'SHADOW', 'MICRO_LIVE_PENDING_APPROVAL', 'MICRO_LIVE',
          'CONTROLLED_LIVE', 'SCALING_PENDING_APPROVAL']
STATES = LADDER + ['SUSPENDED', 'EMERGENCY_STOP']
REAL_MONEY = {'MICRO_LIVE', 'CONTROLLED_LIVE'}
NEVER_RESUME = {'MICRO_LIVE_PENDING_APPROVAL', 'MICRO_LIVE', 'CONTROLLED_LIVE', 'SCALING_PENDING_APPROVAL'}
APPROVAL_REQUIRED = {'MICRO_LIVE', 'CONTROLLED_LIVE'}
ALLOWED = {
    'DEVELOPMENT': {'BACKTEST'},
    'BACKTEST': {'VALIDATION', 'DEVELOPMENT'},
    'VALIDATION': {'PAPER', 'BACKTEST'},
    'PAPER': {'SHADOW', 'VALIDATION'},
    'SHADOW': {'MICRO_LIVE_PENDING_APPROVAL', 'PAPER', 'VALIDATION'},
    'MICRO_LIVE_PENDING_APPROVAL': {'MICRO_LIVE', 'SHADOW'},
    'MICRO_LIVE': {'CONTROLLED_LIVE'},
    'CONTROLLED_LIVE': {'SCALING_PENDING_APPROVAL'},
    'SCALING_PENDING_APPROVAL': {'CONTROLLED_LIVE'},
    'SUSPENDED': {'VALIDATION', 'DEVELOPMENT'},
    'EMERGENCY_STOP': {'SUSPENDED'},
}
MATERIAL = {'strategy', 'model', 'execution', 'risk'}
REPORT_MAX_AGE = dt.timedelta(hours=24)


def _owner_approved(actor, approval):
    return (actor == 'owner' and isinstance(approval, dict) and approval.get('by') == 'owner'
            and isinstance(approval.get('text'), str) and bool(approval['text'].strip()))


def _verified_report(report, now):
    if not isinstance(report, dict):
        return None
    blockers = report.get('blockers')
    if not isinstance(blockers, list) or not all(isinstance(b, dict) for b in blockers):
        return None
    ids = [b.get('id') for b in blockers]
    if sorted(ids) != sorted(live_readiness.GATE_IDS):
        return None
    if any(b.get('status') != 'clear' for b in blockers if b.get('id') != live_readiness.OWNER_GATE):
        return None
    score = report.get('score')
    if report.get('decision') != live_readiness.MICRO_LIVE or not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score) or not 90 <= score <= 100:
        return None
    try:
        generated = dt.datetime.fromisoformat(str(report.get('generatedAt')))
    except ValueError:
        return None
    if generated.tzinfo is None or not dt.timedelta(0) <= now - generated <= REPORT_MAX_AGE:
        return None
    digest = hashlib.sha256(json.dumps(report, sort_keys=True, default=str).encode('utf-8')).hexdigest()
    return dict(sha256=digest, score=score, decision=report['decision'], generatedAt=report['generatedAt'])


class DeploymentState:
    def __init__(self, path, *, clock=None):
        self.path = Path(path)
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS deployment(id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS transitions(seq INTEGER PRIMARY KEY, at TEXT NOT NULL, origin TEXT NOT NULL, target TEXT NOT NULL,
                    actor TEXT NOT NULL, reason TEXT NOT NULL, approval TEXT, evidence TEXT);''')
            row = db.execute('SELECT state FROM deployment WHERE id=1').fetchone()
            if row is None:
                db.execute('INSERT INTO deployment VALUES(1,?,?)', ('DEVELOPMENT', self._now()))
            elif row[0] not in STATES:
                self._record(db, str(row[0])[:40], 'SUSPENDED', 'system', 'Unknown stored state; failing closed.')
            elif row[0] in NEVER_RESUME:
                self._record(db, row[0], 'SUSPENDED', 'system', 'Process restart: real-money states never resume automatically.')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _now(self):
        return self.clock().isoformat()

    def _record(self, db, origin, target, actor, reason, approval=None, evidence=None):
        stamp = self._now()
        db.execute('UPDATE deployment SET state=?, updated=? WHERE id=1', (target, stamp))
        db.execute('INSERT INTO transitions(at,origin,target,actor,reason,approval,evidence) VALUES(?,?,?,?,?,?,?)',
                   (stamp, origin, target, actor, reason, json.dumps(approval) if approval else None,
                    json.dumps(evidence) if evidence else None))

    @staticmethod
    def _current(db):
        value = db.execute('SELECT state FROM deployment WHERE id=1').fetchone()[0]
        return value if value in STATES else 'SUSPENDED'

    @property
    def state(self):
        with self._db() as db:
            return self._current(db)

    @property
    def live_enabled(self):
        return self.state in REAL_MONEY

    @staticmethod
    def _reason(reason):
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
            raise ValueError('A bounded reason is required.')
        return reason.strip()

    def transition(self, target, *, reason, actor='system', approval=None, readiness=None):
        if target not in STATES:
            raise ValueError('Unknown deployment state.')
        if actor not in ('owner', 'agent', 'system'):
            raise ValueError('Unknown actor.')
        reason = self._reason(reason)
        with self._db() as db:
            current = self._current(db)
            risk_reducing = target in ('SUSPENDED', 'EMERGENCY_STOP') and current != 'EMERGENCY_STOP'
            if not risk_reducing and target not in ALLOWED.get(current, set()):
                raise ValueError('Transition %s -> %s is not allowed.' % (current, target))
            needs_owner = target in APPROVAL_REQUIRED or current == 'EMERGENCY_STOP'
            if needs_owner and not _owner_approved(actor, approval):
                raise ValueError('This transition needs explicit owner approval; an agent or the system cannot approve it.')
            evidence = None
            if target == 'MICRO_LIVE_PENDING_APPROVAL':
                evidence = _verified_report(readiness, self.clock())
                if evidence is None:
                    raise ValueError('A complete, fresh, micro-live eligible readiness report with no open blocker is required.')
            self._record(db, current, target, actor, reason, approval if needs_owner else None, evidence)
        return target

    def risk_breach(self, reason, *, critical):
        """Always moves toward safety and never raises because of the current state."""
        text = 'Risk breach: ' + (str(reason)[:400] or 'unspecified')
        with self._db() as db:
            current = self._current(db)
            target = 'EMERGENCY_STOP' if critical or current == 'EMERGENCY_STOP' else 'SUSPENDED'
            self._record(db, current, target, 'system', text)
        return target

    def material_change(self, kind, reason):
        if kind not in MATERIAL:
            raise ValueError('Material change kind must be one of: ' + ', '.join(sorted(MATERIAL)))
        text = 'Material %s change requires revalidation: %s' % (kind, str(reason or '').strip()[:300] or 'unspecified')   # a safety path never refuses
        with self._db() as db:
            current = self._current(db)
            target = ('SUSPENDED' if current in NEVER_RESUME else 'VALIDATION' if current in ('PAPER', 'SHADOW') else current)
            self._record(db, current, target, 'system', text)
        return target

    def history(self, limit=200):
        with self._db() as db:
            rows = db.execute('SELECT * FROM transitions ORDER BY seq DESC LIMIT ?', (limit,)).fetchall()
        return [dict(at=r['at'], origin=r['origin'], to=r['target'], actor=r['actor'], reason=r['reason'],
                     approval=json.loads(r['approval']) if r['approval'] else None,
                     evidence=json.loads(r['evidence']) if r['evidence'] else None) for r in reversed(rows)]
