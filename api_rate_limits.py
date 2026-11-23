"""Atomic local account budgets; not broker compliance or order authorization."""
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from types import MappingProxyType
import uuid

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
KEYS = frozenset(('perSecond', 'perMinute', 'perDay', 'modificationsPerOrder',
                  'reserveSecond', 'reserveMinute', 'reserveDay'))
CEILINGS = dict(perSecond=10, perMinute=400, perDay=5000, modificationsPerOrder=25)
SOURCES = ('https://kite.trade/docs/connect/v3/exceptions/',
           'https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs')


def validated_policy(policy):
    if not isinstance(policy, dict) or set(policy) != KEYS:
        raise ValueError('Provide every explicit account rate and emergency reserve field.')
    if any(type(value) is not int for value in policy.values()):
        raise ValueError('Rate policies require whole integers, not booleans.')
    for key, ceiling in CEILINGS.items():
        if not 1 <= policy[key] <= ceiling:
            raise ValueError(key + ' exceeds the verified broker ceiling or is not positive.')
    for reserve, limit in [('reserveSecond', 'perSecond'),
                            ('reserveMinute', 'perMinute'), ('reserveDay', 'perDay')]:
        if not 0 <= policy[reserve] < policy[limit]:
            raise ValueError(reserve + ' must leave at least one non-emergency slot.')
    return dict(policy)


def identity(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', value))


class AtomicRateLimiter:
    def __init__(self, path, policy, *, clock=time.time):
        self.path = Path(path).resolve()
        self.policy = MappingProxyType(validated_policy(policy))
        self.body = json.dumps(dict(self.policy), sort_keys=True, separators=(',', ':'))
        self.fingerprint = hashlib.sha256(self.body.encode()).hexdigest()
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS api_rate_policy(
                    account TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS api_rate_clock(
                    account TEXT PRIMARY KEY, last_seen REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS api_rate_requests(
                    account TEXT NOT NULL, request_id TEXT NOT NULL, kind TEXT NOT NULL,
                    order_id TEXT, emergency INTEGER NOT NULL, observed REAL NOT NULL,
                    ist_day TEXT NOT NULL, allowed INTEGER NOT NULL, reason TEXT NOT NULL,
                    outcome TEXT, PRIMARY KEY(account,request_id));
                CREATE INDEX IF NOT EXISTS api_rate_observation
                    ON api_rate_requests(account,allowed,observed);
                CREATE INDEX IF NOT EXISTS api_rate_modifications
                    ON api_rate_requests(account,order_id,kind,allowed);
            ''')
        self.configured = True

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def denied(reason, wait=None, counts=None):
        return dict(allowed=False, reason=reason, waitSeconds=wait, counts=counts or {},
                    complianceApproved=False, executionAllowed=False)

    def _counts(self, db, account, now, day, order_id):
        rows = [row[0] for row in db.execute(
            'SELECT observed FROM api_rate_requests WHERE account=? AND allowed=1 AND observed>? AND observed<=? ORDER BY observed',
            (account, now-60, now))]
        return dict(
            fixedSecond=sum(stamp >= math.floor(now) for stamp in rows),
            rollingSecond=sum(stamp > now-1 for stamp in rows),
            fixedMinute=sum(stamp >= math.floor(now/60)*60 for stamp in rows),
            rollingMinute=len(rows),
            day=db.execute('SELECT COUNT(*) FROM api_rate_requests WHERE account=? AND allowed=1 AND ist_day=?',
                           (account, day)).fetchone()[0],
            modifications=db.execute("SELECT COUNT(*) FROM api_rate_requests WHERE account=? AND allowed=1 AND kind='modify' AND order_id=?",
                                     (account, order_id)).fetchone()[0] if order_id else 0), rows

    def admit(self, account, request_id, kind, emergency=False, order_id=None):
        """Consume one permit immediately before one actual request; never refund.

        The caller must use a fresh UUID for every new transport attempt and
        must never retry an unknown order submission merely with another UUID.
        Emergency classification does not prove risk reduction: the OMS owns
        that check. All operations still obey every hard broker budget.
        """
        if not identity(account):
            return self.denied('missing-or-invalid-account')
        try:
            request_id = uuid.UUID(request_id).hex if isinstance(request_id, str) else None
        except (ValueError, AttributeError):
            request_id = None
        if not request_id:
            return self.denied('invalid-request-id')
        if kind not in ('place', 'modify', 'cancel') or type(emergency) is not bool:
            return self.denied('invalid-operation')
        if kind in ('modify', 'cancel') and not identity(order_id):
            return self.denied('missing-or-invalid-order-id')
        if order_id is not None and not identity(order_id):
            return self.denied('invalid-order-id')
        try:
            now = self.clock()
            if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now) or now < 0:
                return self.denied('invalid-clock')
            current = dt.datetime.fromtimestamp(now, IST)
            day = current.date().isoformat()
            midnight = dt.datetime.combine(current.date()+dt.timedelta(days=1), dt.time(), IST).timestamp()
        except (ValueError, OverflowError, OSError):
            return self.denied('invalid-clock')
        try:
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                old = db.execute('SELECT fingerprint FROM api_rate_policy WHERE account=?', (account,)).fetchone()
                if old and old['fingerprint'] != self.fingerprint:
                    return self.denied('account-policy-mismatch')
                if not old:
                    db.execute('INSERT INTO api_rate_policy VALUES(?,?,?)', (account, self.fingerprint, self.body))
                previous = db.execute('SELECT last_seen FROM api_rate_clock WHERE account=?', (account,)).fetchone()
                if previous and now < previous['last_seen']:
                    return self.denied('clock-rollback', previous['last_seen']-now)
                db.execute('INSERT OR REPLACE INTO api_rate_clock VALUES(?,?)', (account, now))
                counts, rows = self._counts(db, account, now, day, order_id)
                duplicate = db.execute('SELECT allowed FROM api_rate_requests WHERE account=? AND request_id=?',
                                       (account, request_id)).fetchone()
                if duplicate:
                    return self.denied('duplicate-request-id', counts=counts)
                waits = []
                reason = None
                if kind == 'modify' and counts['modifications'] >= self.policy['modificationsPerOrder']:
                    reason = 'order-modification-limit'
                for fixed, rolling, maximum, reserved, window in [
                        ('fixedSecond', 'rollingSecond', 'perSecond', 'reserveSecond', 1),
                        ('fixedMinute', 'rollingMinute', 'perMinute', 'reserveMinute', 60)]:
                    limit = self.policy[maximum] - (0 if emergency else self.policy[reserved])
                    if counts[fixed] >= limit:
                        waits.append((math.floor(now/window)+1)*window-now)
                    if counts[rolling] >= limit:
                        relevant = [stamp for stamp in rows if stamp > now-window]
                        waits.append(relevant[len(relevant)-limit] + window-now)
                daily = self.policy['perDay'] - (0 if emergency else self.policy['reserveDay'])
                if counts['day'] >= daily:
                    waits.append(midnight-now)
                if waits and reason is None:
                    reason = 'rate-budget-exhausted'
                allowed = reason is None
                db.execute('INSERT INTO api_rate_requests VALUES(?,?,?,?,?,?,?,?,?,NULL)',
                    (account, request_id, kind, order_id, int(emergency), now, day,
                     int(allowed), reason or 'admitted'))
                if not allowed:
                    return self.denied(reason,
                        math.ceil(max(waits)*1000)/1000 if waits and reason != 'order-modification-limit' else None,
                        counts)
                counts['fixedSecond'] += 1
                counts['rollingSecond'] += 1
                counts['fixedMinute'] += 1
                counts['rollingMinute'] += 1
                counts['day'] += 1
                if kind == 'modify':
                    counts['modifications'] += 1
                return dict(allowed=True, reason='admitted', waitSeconds=0, counts=counts,
                            requestId=request_id, complianceApproved=False,
                            executionAllowed=False)
        except (sqlite3.Error, OSError):
            return self.denied('limiter-storage-unavailable')

    def note_outcome(self, account, request_id, outcome):
        """Record bounded transport outcomes; no operation returns capacity."""
        if not identity(account) or outcome not in ('ACK', 'REJECTED', 'HTTP_429', 'ERROR', 'UNKNOWN'):
            raise ValueError('Invalid rate-permit outcome.')
        try:
            request_id = uuid.UUID(request_id).hex
        except (ValueError, AttributeError, TypeError):
            raise ValueError('Invalid request ID.') from None
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT allowed FROM api_rate_requests WHERE account=? AND request_id=?',
                             (account, request_id)).fetchone()
            if not row or not row['allowed']:
                raise ValueError('No admitted permit exists.')
            db.execute('UPDATE api_rate_requests SET outcome=? WHERE account=? AND request_id=?',
                       (outcome, account, request_id))

    def policy_status(self):
        return dict(configured=self.configured, policy=dict(self.policy),
                    sources=list(SOURCES), complianceApproved=False,
                    executionAllowed=False,
                    scope='Shared local SQLite admission only; all client API users must share this authority.')
