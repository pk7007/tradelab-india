"""Durable local incident inbox. No credentials, messaging or trading authority."""
from contextlib import contextmanager
import datetime as dt
from pathlib import Path
import sqlite3
import uuid


class OperationalAlerts:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS incidents(
                id TEXT PRIMARY KEY, key TEXT NOT NULL, severity TEXT NOT NULL,
                message TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                resolved_at TEXT, acknowledged_at TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS incident_active ON incidents(key) WHERE resolved_at IS NULL;
                CREATE TABLE IF NOT EXISTS watcher(id INTEGER PRIMARY KEY CHECK(id=1),owner TEXT,expires REAL);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def observe(self, key, message, failed, *, severity='warning', now=None):
        if not isinstance(key, str) or not 1 <= len(key) <= 150 or severity not in ('warning', 'critical'):
            raise ValueError('Invalid alert identity or severity.')
        if not isinstance(message, str) or not 1 <= len(message) <= 500 or type(failed) is not bool:
            raise ValueError('Invalid alert observation.')
        stamp = (now or dt.datetime.now(dt.timezone.utc)).isoformat()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT id FROM incidents WHERE key=? AND resolved_at IS NULL', (key,)).fetchone()
            if failed and row:
                db.execute('UPDATE incidents SET last_seen=?,message=?,severity=? WHERE id=?', (stamp, message, severity, row['id']))
            elif failed:
                db.execute('INSERT INTO incidents VALUES(?,?,?,?,?,?,NULL,NULL)',
                           (uuid.uuid4().hex, key, severity, message, stamp, stamp))
            elif row:
                db.execute('UPDATE incidents SET resolved_at=?,last_seen=? WHERE id=?', (stamp, stamp, row['id']))

    def acknowledge(self, identity):
        if not isinstance(identity, str) or len(identity) != 32:
            raise ValueError('Choose an alert from the inbox.')
        with self.db() as db:
            row = db.execute('SELECT id FROM incidents WHERE id=?', (identity,)).fetchone()
            if not row:
                raise ValueError('Unknown alert.')
            db.execute('UPDATE incidents SET acknowledged_at=COALESCE(acknowledged_at,?) WHERE id=?',
                       (dt.datetime.now(dt.timezone.utc).isoformat(), identity))

    def status(self):
        with self.db() as db:
            rows = [dict(row) for row in db.execute('SELECT * FROM incidents ORDER BY (resolved_at IS NULL) DESC,first_seen DESC LIMIT 100')]
            watcher = db.execute('SELECT expires FROM watcher WHERE id=1').fetchone()
        return dict(items=rows, active=sum(not row['resolved_at'] for row in rows),
                    unacknowledged=sum(not row['resolved_at'] and not row['acknowledged_at'] for row in rows),
                    watcherExpires=watcher['expires'] if watcher else None,
                    delivery='Persistent local inbox; desktop notifications require an open page and browser permission.')

    def lease(self, owner, now):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT owner,expires FROM watcher WHERE id=1').fetchone()
            if row and row['owner'] != owner and row['expires'] > now:
                return False
            db.execute('INSERT OR REPLACE INTO watcher VALUES(1,?,?)', (owner, now + 90))
        return True


def observe_service(alerts, payload):
    for source in payload.get('sources', []):
        key = source.get('source')
        if key not in ('nse', 'et', 'google', 'moneycontrol'):
            continue
        disabled = source.get('status') == 'disabled'
        alerts.observe('feed:' + key, key.upper() + ' news is unavailable or stale.',
                       bool(source.get('stale')) and not disabled)
    selection = payload.get('selection', {})
    alerts.observe('paper:processing', 'Paper processing needs recovery. Check positions and pending exits.',
                   selection.get('state') in ('blocked', 'expired'), severity='critical')
