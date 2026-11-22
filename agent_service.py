"""Durable research tasks with fenced leases, process deadlines and operator review."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
import uuid

from agent_catalog import VERSION, registry
from agent_handlers import LEGACY, supported, execute

HANDLERS = LEGACY
STATES = ('candidate', 'shadow', 'active', 'probation', 'quarantined', 'retired')
WEIGHTS = {'correctness': 40, 'evidence': 20, 'reproducibility': 15, 'completeness': 15, 'budget': 10}


class AgentService:
    def __init__(self, path, concurrency=4):
        if type(concurrency) is not int or not 1 <= concurrency <= 4:
            raise ValueError('Choose one to four workers.')
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.concurrency = concurrency
        self._shutdown = threading.Event()
        self._workers = []
        self._worker_lock = threading.Lock()
        self._last_worker_error = None
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS agents(id TEXT PRIMARY KEY,state TEXT NOT NULL,reason TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,key TEXT UNIQUE NOT NULL,capability TEXT NOT NULL,body TEXT NOT NULL,fingerprint TEXT NOT NULL,priority INTEGER NOT NULL,deadline REAL NOT NULL,budget REAL NOT NULL,state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,lease TEXT,expires REAL,output TEXT,verdict TEXT,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_audit(seq INTEGER PRIMARY KEY,at REAL NOT NULL,event TEXT NOT NULL,identity TEXT NOT NULL,body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_attempts(task TEXT NOT NULL,attempt INTEGER NOT NULL,lease TEXT NOT NULL,version TEXT NOT NULL,started REAL NOT NULL,finished REAL,state TEXT,PRIMARY KEY(task,attempt));
                CREATE TABLE IF NOT EXISTS agent_reviews(seq INTEGER PRIMARY KEY,task TEXT NOT NULL,agent TEXT NOT NULL,version TEXT NOT NULL,reviewer TEXT NOT NULL,body TEXT NOT NULL,at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_dependencies(task TEXT NOT NULL,dependency TEXT NOT NULL,PRIMARY KEY(task,dependency));''')
            for role in registry():
                db.execute('INSERT OR IGNORE INTO agents VALUES(?,?,?)',
                           (role['id'], 'shadow' if role['implemented'] else 'candidate', 'Initial registry'))
            for identity in LEGACY:
                db.execute('INSERT OR IGNORE INTO agents VALUES(?,?,?)', (identity, 'shadow', 'Legacy compatibility handler'))
            db.execute('PRAGMA user_version=2')

    @contextmanager
    def db(self):
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

    @staticmethod
    def _audit(db, event, identity, body):
        db.execute('INSERT INTO agent_audit(at,event,identity,body) VALUES(?,?,?,?)',
                   (time.time(), event, identity, json.dumps(body, allow_nan=False)))

    def review_desk_observations(self):
        """Check completed local health reports without granting trading or promotion authority."""
        with self.db() as db:
            rows = db.execute("""SELECT id,body,output FROM tasks
                WHERE capability='operations-security.monitoring' AND state='review'
                AND key GLOB 'desk-v1-[0-9]*' ORDER BY created LIMIT 24""").fetchall()
            for row in rows:
                envelope = json.loads(row['body'])
                records = envelope['input'].get('records', [])
                if len(records) != 1 or records[0].get('source') != 'local:desk-observation':
                    continue
                try:
                    expected = execute('operations-security.monitoring', envelope)
                    matches = expected == json.loads(row['output'])
                except (ValueError, KeyError, TypeError):
                    matches = False
                verdict = dict(reviewer='service:desk-observation-review-v1',
                               reproducible=matches, executionAllowed=False)
                db.execute('UPDATE tasks SET state=?,verdict=? WHERE id=? AND state=?',
                           ('desk-reviewed' if matches else 'rejected', json.dumps(verdict),
                            row['id'], 'review'))
                self._audit(db, 'desk-review', row['id'], verdict)

    def enqueue(self, values):
        capability = values.get('capability')
        if not supported(capability or ''):
            raise ValueError('Capability has no implemented handler.')
        payload = values.get('input')
        if not isinstance(payload, dict):
            raise ValueError('Object input required.')
        body = json.dumps(payload, sort_keys=True, allow_nan=False)
        if len(body.encode()) > 60000:
            raise ValueError('Task input exceeds 60KB.')
        if any(word in body.lower() for word in ('api_secret', 'access_token', 'api_key', 'password')):
            raise ValueError('Credentials must stay outside tasks.')
        from research import timestamp
        timestamp(values.get('evidenceCutoff', ''))
        for field, low, high in [('priority', 0, 9), ('budgetSeconds', 1, 30), ('deadlineSeconds', 1, 3600)]:
            value = values.get(field)
            if type(value) is not int or not low <= value <= high:
                raise ValueError('Invalid '+field)
        key = values.get('idempotencyKey')
        if not isinstance(key, str) or not 1 <= len(key) <= 128:
            raise ValueError('Idempotency key required.')
        dependencies = values.get('dependencies', [])
        if not isinstance(dependencies, list) or len(dependencies) > 32 or any(not isinstance(v, str) for v in dependencies):
            raise ValueError('Supply at most32 dependency task IDs.')
        envelope = dict(input=payload, evidenceCutoff=values['evidenceCutoff'], version=VERSION,
                        dependencies=sorted(set(dependencies)))
        body = json.dumps(envelope, sort_keys=True, allow_nan=False)
        if len(body.encode()) > 64000:
            raise ValueError('Task envelope exceeds64KB.')
        fingerprint = hashlib.sha256(body.encode()).hexdigest()
        with self.db() as db:
            existing = db.execute('SELECT * FROM tasks WHERE key=?', (key,)).fetchone()
            if existing:
                if existing['fingerprint'] != fingerprint or existing['capability'] != capability:
                    raise ValueError('Idempotency key reused with different input.')
                return existing['id']
            for dependency in dependencies:
                if not db.execute('SELECT 1 FROM tasks WHERE id=?', (dependency,)).fetchone():
                    raise ValueError('Dependency task does not exist.')
            identity = uuid.uuid4().hex
            now = time.time()
            db.execute('INSERT INTO tasks(id,key,capability,body,fingerprint,priority,deadline,budget,state,created) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (identity, key, capability, body, fingerprint, values['priority'], now+values['deadlineSeconds'], values['budgetSeconds'], 'queued', now))
            db.executemany('INSERT INTO agent_dependencies VALUES(?,?)', [(identity, d) for d in dependencies])
            self._audit(db, 'enqueued', identity, dict(capability=capability, version=VERSION))
        return identity

    def _claim(self):
        with self.db() as db:
            now = time.time()
            expired = db.execute("SELECT id,attempts FROM tasks WHERE state='running' AND expires<=?", (now,)).fetchall()
            for task in expired:
                state = 'queued' if task['attempts'] < 3 else 'failed'
                db.execute('UPDATE tasks SET state=?,lease=NULL WHERE id=?', (state, task['id']))
                db.execute("UPDATE agent_attempts SET state='lease-expired',finished=? WHERE task=? AND finished IS NULL", (now, task['id']))
                self._audit(db, 'lease-expired', task['id'], dict(nextState=state))
            db.execute("UPDATE tasks SET state='expired' WHERE state='queued' AND deadline<=?", (now,))
            db.execute("UPDATE tasks SET state='blocked' WHERE state='queued' AND EXISTS(SELECT 1 FROM agent_dependencies d JOIN tasks p ON p.id=d.dependency WHERE d.task=tasks.id AND p.state IN ('cancelled','rejected','expired','failed','blocked'))")
            if db.execute("SELECT COUNT(*) FROM tasks WHERE state='running'").fetchone()[0] >= self.concurrency:
                return None
            row = db.execute("""SELECT t.* FROM tasks t JOIN agents a ON a.id=t.capability
                WHERE t.state='queued' AND a.state IN ('shadow','active','probation')
                AND NOT EXISTS(SELECT 1 FROM agent_dependencies d JOIN tasks p ON p.id=d.dependency WHERE d.task=t.id AND p.state!='accepted')
                ORDER BY t.priority DESC,t.created LIMIT 1""").fetchone()
            if row is None:
                return None
            lease = uuid.uuid4().hex
            expires = min(row['deadline'], now+row['budget'])
            db.execute("UPDATE tasks SET state='running',attempts=attempts+1,lease=?,expires=? WHERE id=?", (lease, expires, row['id']))
            db.execute('INSERT INTO agent_attempts VALUES(?,?,?,?,?,?,?)',
                       (row['id'], row['attempts']+1, lease, VERSION, now, None, 'running'))
            self._audit(db, 'claimed', row['id'], dict(version=VERSION, attempt=row['attempts']+1))
        return dict(row), lease, expires

    def _eligible(self, identity, lease):
        if self._shutdown.is_set():
            return False
        with self.db() as db:
            row = db.execute('SELECT t.state,t.lease,a.state AS agentState FROM tasks t JOIN agents a ON a.id=t.capability WHERE t.id=?', (identity,)).fetchone()
            return bool(row and row['state'] == 'running' and row['lease'] == lease and row['agentState'] in ('shadow', 'active', 'probation'))

    def run_once(self):
        claimed = self._claim()
        if claimed is None:
            return None
        row, lease, expires = claimed
        request = json.dumps(dict(capability=row['capability'], envelope=json.loads(row['body'])), allow_nan=False)
        env = {key: value for key, value in os.environ.items() if key.upper() in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PATH')}
        env['PYTHONIOENCODING'] = 'utf-8'
        process = None
        state = 'failed'
        output = dict(errorType='WorkerFailure')
        try:
            process = subprocess.Popen([sys.executable, '-B', str(Path(__file__).with_name('agent_handlers.py'))],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding='utf-8', env=env,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            first = True
            while True:
                if time.time() >= expires:
                    state = 'expired'
                    output = dict(errorType='DeadlineExceeded')
                    break
                if not self._eligible(row['id'], lease):
                    state = 'cancelled'
                    output = dict(errorType='EligibilityLost')
                    break
                try:
                    stdout, _stderr = process.communicate(input=request if first else None, timeout=min(.1, max(.001, expires-time.time())))
                    result = json.loads(stdout)
                    if len(stdout.encode()) > 200000:
                        raise ValueError('Output bound exceeded.')
                    if result.get('ok'):
                        state = 'review'
                        output = result['output']
                    else:
                        output = dict(errorType=result.get('errorType', 'HandlerFailure'))
                    break
                except subprocess.TimeoutExpired:
                    first = False
        except Exception as exc:
            output = dict(errorType=type(exc).__name__)
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.communicate()
        with self.db() as db:
            current = db.execute('SELECT state,lease FROM tasks WHERE id=?', (row['id'],)).fetchone()
            eligible = db.execute('SELECT state FROM agents WHERE id=?', (row['capability'],)).fetchone()
            if eligible['state'] not in ('shadow', 'active', 'probation'):
                state = 'cancelled'
            if time.time() > expires:
                state = 'expired'
            if current['state'] == 'running' and current['lease'] == lease:
                db.execute('UPDATE tasks SET state=?,output=?,lease=NULL WHERE id=?', (state, json.dumps(output, allow_nan=False), row['id']))
            else:
                state = 'discarded'
            db.execute('UPDATE agent_attempts SET state=?,finished=? WHERE task=? AND lease=?', (state, time.time(), row['id'], lease))
            self._audit(db, 'attempt-finished', row['id'], dict(state=state, version=VERSION))
        return row['id']

    def start(self):
        """Lazily start bounded consumers after the app accepts a task."""
        with self._worker_lock:
            self._workers = [worker for worker in self._workers if worker.is_alive()]
            if self._workers:
                return
            self._shutdown.clear()
            for number in range(self.concurrency):
                worker = threading.Thread(target=self._consume, daemon=True, name=f'research-agent-{number}')
                self._workers.append(worker)
                worker.start()

    def _consume(self):
        while not self._shutdown.is_set():
            try:
                identity = self.run_once()
                self._last_worker_error = None
            except Exception as exc:
                identity = None
                self._last_worker_error = type(exc).__name__
            if identity is None:
                self._shutdown.wait(1)

    def stop(self):
        self._shutdown.set()
        for worker in self._workers:
            worker.join(timeout=1)

    def review(self, identity, reviewer, checks, critical=False):
        if not isinstance(reviewer, str) or not reviewer.startswith('human:') or not reviewer[6:].strip():
            raise ValueError('Independent human reviewer identity required.')
        if not isinstance(checks, dict) or set(checks) != set(WEIGHTS) or any(type(v) is not bool for v in checks.values()) or type(critical) is not bool:
            raise ValueError('Provide five explicit Boolean review checks.')
        score = sum(WEIGHTS[key] for key, valid in checks.items() if valid)
        critical = critical or not checks['correctness'] or not checks['evidence']
        with self.db() as db:
            row = db.execute('SELECT * FROM tasks WHERE id=?', (identity,)).fetchone()
            if not row or row['state'] != 'review':
                raise ValueError('Task is not awaiting review.')
            verdict = dict(reviewer=reviewer, checks=checks, score=score, critical=critical, reviewedAt=time.time(), version=VERSION)
            verdict_json = json.dumps(verdict)
            db.execute('UPDATE tasks SET verdict=?,state=? WHERE id=?', (verdict_json, 'accepted' if score >= 90 and not critical else 'rejected', identity))
            db.execute('INSERT INTO agent_reviews(task,agent,version,reviewer,body,at) VALUES(?,?,?,?,?,?)',
                       (identity, row['capability'], VERSION, reviewer, verdict_json, time.time()))
            if critical:
                self._lifecycle(db, row['capability'], 'quarantined', 'Critical independent review failure')
            else:
                records = db.execute('SELECT body FROM agent_reviews WHERE agent=? AND version=? ORDER BY seq DESC LIMIT 30', (row['capability'], VERSION)).fetchall()
                if len(records) == 30 and sum(json.loads(r['body'])['score'] for r in records)/30 < 70:
                    self._lifecycle(db, row['capability'], 'probation', 'Thirty reviewed comparable cases below70 average')
            self._audit(db, 'reviewed', identity, verdict)

    def cancel(self, identity):
        with self.db() as db:
            db.execute("UPDATE tasks SET state='cancelled',lease=NULL WHERE id=? AND state IN ('queued','running','review')", (identity,))
            self._audit(db, 'cancelled', str(identity), dict(actor='local-operator'))

    def _lifecycle(self, db, identity, state, reason):
        db.execute('UPDATE agents SET state=?,reason=? WHERE id=?', (state, reason[:500], identity))
        if state in ('quarantined', 'retired'):
            db.execute("UPDATE tasks SET state='cancelled',lease=NULL WHERE capability=? AND state IN ('queued','running','review')", (identity,))
        self._audit(db, 'lifecycle', identity, dict(state=state, reason=reason[:500], version=VERSION))

    def lifecycle(self, identity, state, reason):
        if state not in STATES or not isinstance(reason, str) or not reason.strip():
            raise ValueError('Lifecycle state and operator reason required.')
        with self.db() as db:
            row = db.execute('SELECT * FROM agents WHERE id=?', (identity,)).fetchone()
            if not row:
                raise ValueError('Unknown agent.')
            if state in ('shadow', 'active', 'probation') and not supported(identity):
                raise ValueError('Unimplemented role cannot become eligible.')
            if row['state'] in ('quarantined', 'retired') and state not in ('quarantined', 'retired', 'candidate'):
                raise ValueError('Quarantined roles must return to candidate for independent revalidation.')
            if state in ('shadow', 'active') and row['state'] == 'candidate':
                raise ValueError('Candidate activation requires a versioned fixture certification.')
            if state == 'active':
                reviews = db.execute("SELECT COUNT(*) FROM agent_reviews WHERE agent=? AND version=? AND json_extract(body,'$.score')>=90 AND json_extract(body,'$.critical')=0", (identity, VERSION)).fetchone()[0]
                if reviews < 30:
                    raise ValueError('Thirty accepted independent reviews required before active status.')
            self._lifecycle(db, identity, state, reason)

    def status(self):
        catalog = registry()
        canonical = {role['id'] for role in catalog}
        with self.db() as db:
            roles = [dict(row) for row in db.execute('SELECT * FROM agents ORDER BY id')]
            tasks = [dict(row) for row in db.execute('SELECT id,capability,fingerprint,state,attempts,verdict,output FROM tasks ORDER BY created DESC LIMIT 50')]
            demonstrated = {row[0] for row in db.execute("SELECT DISTINCT capability FROM tasks WHERE state='accepted'")}
            history = [dict(row) for row in db.execute('SELECT * FROM agent_audit ORDER BY seq DESC LIMIT 50')]
            queue = {row['state']: row['count'] for row in db.execute('SELECT state,COUNT(*) AS count FROM tasks GROUP BY state')}
        return dict(registered=len(catalog), implemented=sum(role['implemented'] for role in catalog),
                    legacyHandlers=len(LEGACY), enabled=sum(r['id'] in canonical and r['state'] in ('shadow', 'active', 'probation') for r in roles),
                    demonstrated=len(canonical & demonstrated), fixtureTested=0,
                    roles=roles, catalog=catalog, tasks=tasks, audit=history, rubric=WEIGHTS,
                    mode='research-shadow', concurrency=self.concurrency, executionAllowed=False,
                    workerThreadsAlive=sum(worker.is_alive() for worker in self._workers),
                    lastWorkerError=self._last_worker_error, queue=queue,
                    limitations=['Evidence-processing roles do not imply market access, strategy engines or order authority.', 'Fixture certification count is supplied by the offline acceptance report.'])
