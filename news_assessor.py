"""Opt-in background labelling of current news items. Research context only.

Off unless TRADELAB_NEWS_AI=true and an API key are both set. Results are kept in a
private SQLite file that holds identifiers and the model's labels only: no article
text, no quoted phrase (a hash of it) and no free-text rationale. A persistent daily
cap and a per-cycle cap bound spending, and any provider failure leaves the news,
risk and exit paths untouched.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import news_intelligence as ni

UTC = dt.timezone.utc
DEFAULT_MODEL = 'claude-haiku-5-5'


class NewsAssessor:
    interval = 60

    def __init__(self, path, *, complete=None, enabled=False, status=None, cycle_limit=5,
                 daily_limit=100, clock=lambda: dt.datetime.now(UTC)):
        for value in (cycle_limit, daily_limit):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError('Limits must be non-negative integers.')
        self.path, self.complete, self.clock = Path(path), complete, clock
        self.enabled = bool(enabled and complete)
        self.state = status or ('enabled' if self.enabled else 'disabled')
        self.cycle_limit, self.daily_limit = cycle_limit, daily_limit
        self.unavailable = 0
        self.retry = {}  # item key -> (failures, not-before time); in memory only
        self.source = None
        self.lock, self.shutdown, self.thread = threading.Lock(), threading.Event(), None
        # lock guards start/stop only; tick_lock makes tick single-flight; init_lock covers lazy table
        # creation. Reads take only init_lock (briefly) so they never wait for a provider call.
        self.tick_lock, self.init_lock = threading.Lock(), threading.Lock()
        self.timeout = 2.0  # seconds a connection waits on a locked database
        self.ready = False  # storage is created lazily on first use; construction does no I/O

    def _connect(self):
        """Open storage, creating the directory and tables on first use. Raises OSError/sqlite3.Error."""
        with self.init_lock:
            if not self.ready:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(self.path, timeout=self.timeout)) as db, db:
                    db.execute("""CREATE TABLE IF NOT EXISTS assessments (
                        item_id TEXT NOT NULL, item_available_at TEXT NOT NULL, status TEXT NOT NULL,
                        sentiment TEXT, event_type TEXT, confidence REAL, symbols TEXT, quote_sha256 TEXT,
                        assessed_at TEXT NOT NULL, available_at TEXT, PRIMARY KEY (item_id, item_available_at))""")
                    db.execute('CREATE TABLE IF NOT EXISTS usage (day TEXT PRIMARY KEY, used INTEGER NOT NULL)')
                self.ready = True
        return sqlite3.connect(self.path, timeout=self.timeout)

    def _reset(self, exc):
        """A failed query may mean the file was replaced or deleted: recreate tables on next use."""
        if isinstance(exc, sqlite3.OperationalError):
            self.ready = False

    def _day(self):
        return self.clock().astimezone(UTC).date().isoformat()

    def _used(self, db):
        row = db.execute('SELECT used FROM usage WHERE day=?', (self._day(),)).fetchone()
        return row[0] if row else 0

    def tick(self, items):
        """Assess unseen items within the caps. Never raises."""
        if not self.enabled:
            return
        if not self.tick_lock.acquire(blocking=False):
            return  # single flight: a tick is already running
        try:
            self._tick(items)
        except Exception as exc:
            self.unavailable += 1
            self._reset(exc)
        finally:
            self.tick_lock.release()

    def _tick(self, items):
        with closing(self._connect()) as db:
            remaining = max(0, min(self.cycle_limit, self.daily_limit - self._used(db)))
            budget = ni.Budget(remaining)
            for item in items:
                key = (item['id'], item.get('availableAt') or '')
                if db.execute('SELECT 1 FROM assessments WHERE item_id=? AND item_available_at=?', key).fetchone():
                    continue
                failures, not_before = self.retry.get(key, (0, None))
                if not_before and self.clock().astimezone(UTC) < not_before:
                    continue
                result = ni.assess_item(item, self.complete, budget=budget, clock=self.clock,
                                        allowed_symbols=item.get('symbols') or ())
                if result['status'] == 'budget_exhausted':
                    break
                with db:
                    db.execute('INSERT INTO usage(day,used) VALUES (?,1) ON CONFLICT(day) DO UPDATE SET used=used+1',
                               (self._day(),))
                    if result['status'] == 'unavailable':
                        self.unavailable += 1
                        delay = min(3600, 60 * 2 ** failures)
                        self.retry[key] = (failures + 1, self.clock().astimezone(UTC) + dt.timedelta(seconds=delay))
                        continue
                    self.retry.pop(key, None)
                    if result['status'] == 'assessed':
                        a = result['assessment']
                        db.execute('INSERT OR REPLACE INTO assessments VALUES (?,?,?,?,?,?,?,?,?,?)', (
                            *key, 'assessed', a['sentiment'], a['eventType'], a['confidence'],
                            json.dumps(a['symbols']), hashlib.sha256(a['quote'].encode()).hexdigest(),
                            self.clock().astimezone(UTC).isoformat(), result['availableAt']))
                    else:
                        db.execute('INSERT OR REPLACE INTO assessments(item_id,item_available_at,status,assessed_at) VALUES (?,?,?,?)',
                                   (*key, 'rejected', self.clock().astimezone(UTC).isoformat()))

    @staticmethod
    def _label(sentiment, event, confidence, symbols, quote_hash, available):
        return dict(assessment=dict(sentiment=sentiment, eventType=event, confidence=confidence,
                                    symbols=json.loads(symbols), quoteSha256=quote_hash),
                    availableAt=available, version=ni.VERSION, executionAllowed=False)

    def assessments(self):
        """Latest assessed label for each item id (any revision). Empty if storage is unavailable."""
        if not self.enabled:
            return {}
        try:
            with closing(self._connect()) as db:
                rows = db.execute("""SELECT item_id, sentiment, event_type, confidence, symbols, quote_sha256, available_at
                                     FROM assessments WHERE status='assessed' ORDER BY item_available_at""").fetchall()
        except (OSError, sqlite3.Error) as exc:
            self._reset(exc)
            return {}
        return {row[0]: self._label(*row[1:]) for row in rows}

    def assessments_for(self, items):
        """Labels made for exactly each item's current revision; older revisions are never shown."""
        found = {}
        if not self.enabled:
            return found
        try:
            with closing(self._connect()) as db:
                for item in items:
                    row = db.execute("""SELECT sentiment, event_type, confidence, symbols, quote_sha256, available_at
                                         FROM assessments WHERE status='assessed' AND item_id=? AND item_available_at=?""",
                                     (item['id'], item.get('availableAt') or '')).fetchone()
                    if row:
                        found[item['id']] = self._label(*row)
        except (OSError, sqlite3.Error) as exc:
            self._reset(exc)
            return {}
        return found

    def summary(self):
        base = dict(dailyLimit=self.daily_limit, cycleLimit=self.cycle_limit, unavailable=self.unavailable,
                    scope='Model labels are research context only; they cannot authorise orders.')
        if not self.enabled:
            return dict(base, status=self.state, usedToday=0, assessed=0, rejected=0)
        try:
            with closing(self._connect()) as db:
                used = self._used(db)
                rejected = db.execute("SELECT COUNT(*) FROM assessments WHERE status='rejected'").fetchone()[0]
                assessed = db.execute("SELECT COUNT(*) FROM assessments WHERE status='assessed'").fetchone()[0]
        except (OSError, sqlite3.Error) as exc:
            self._reset(exc)
            if 'locked' in str(exc):  # busy, not broken: keep the status, report no counts
                return dict(base, status=self.state, reason='Assessment storage is busy.',
                            usedToday=0, assessed=0, rejected=0)
            return dict(base, status='unavailable', reason='Assessment storage cannot be opened.',
                        usedToday=0, assessed=0, rejected=0)
        return dict(base, status=self.state, usedToday=used, assessed=assessed, rejected=rejected)

    def start(self):
        with self.lock:
            if not self.enabled or self.source is None or (self.thread and self.thread.is_alive()):
                return
            self.shutdown.clear()
            self.thread = threading.Thread(target=self._run, name='tradelab-news-assessor', daemon=True)
            self.thread.start()

    def stop(self):
        self.shutdown.set()
        if self.thread:
            self.thread.join(timeout=25)

    def _run(self):
        while not self.shutdown.is_set():
            try:
                self.tick(self.source())
            except Exception:
                self.unavailable += 1
            self.shutdown.wait(self.interval)


def from_environment(env, path, clock=lambda: dt.datetime.now(UTC)):
    """Build the service from settings. Both the flag and the key must be present."""
    def number(name, default):
        try:
            value = int(env.get(name, default))
        except (TypeError, ValueError):
            return default
        return value if value >= 0 else default
    limits = dict(cycle_limit=number('TRADELAB_NEWS_AI_CYCLE_LIMIT', 5),
                  daily_limit=number('TRADELAB_NEWS_AI_DAILY_LIMIT', 100), clock=clock)
    if str(env.get('TRADELAB_NEWS_AI', '')).strip().lower() != 'true':
        return NewsAssessor(path, **limits)
    key = str(env.get('ANTHROPIC_API_KEY', '')).strip()
    if not key:
        return NewsAssessor(path, status='missing-key', **limits)
    try:
        complete = ni.anthropic_completer(key, env.get('TRADELAB_NEWS_AI_MODEL') or DEFAULT_MODEL)
    except ImportError:
        return NewsAssessor(path, status='missing-package', **limits)
    return NewsAssessor(path, complete=complete, enabled=True, **limits)
