"""Durable, bounded, research-only agent tasks with explicit human review."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

FAMILIES = ('market-data','instruments-calendars','news-disclosures','fundamentals','sector-benchmark','indicators-features','strategy-research','backtesting','portfolio-risk','paper-execution','reconciliation-recovery','application-operations')
RESPONSIBILITIES = ('intake','normalization','validation','analysis','anomaly-detection','evidence-preparation','scenario-testing','independent-review','reporting')
HANDLERS = {'strategy-research.analysis':'scan','portfolio-risk.validation':'risk','backtesting.analysis':'evaluate'}
STATES = ('candidate','shadow','active','probation','quarantined','retired')


def registry():
    return [dict(id=family+'.'+role,family=family,responsibility=role,
                 task=role+' of '+family+' evidence',permissions=['research-only'],
                 implemented=family+'.'+role in HANDLERS,
                 inputContract='Bounded permitted JSON with evidence cutoff; no credentials',
                 outputContract='Bounded JSON evidence or explicit insufficient evidence',
                 dependencies=['validated input','independent reviewer'],
                 failureBehavior='Abstain and preserve history',
                 acceptance='Domain fixture accepted by independent reviewer')
            for family in FAMILIES for role in RESPONSIBILITIES]


class AgentService:
    def __init__(self,path,concurrency=4):
        if type(concurrency) is not int or not 1<=concurrency<=4:
            raise ValueError('Choose one to four workers.')
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.concurrency=concurrency
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS agents(id TEXT PRIMARY KEY,state TEXT NOT NULL,reason TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,key TEXT UNIQUE NOT NULL,capability TEXT NOT NULL,body TEXT NOT NULL,fingerprint TEXT NOT NULL,priority INTEGER NOT NULL,deadline REAL NOT NULL,budget REAL NOT NULL,state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,lease TEXT,expires REAL,output TEXT,verdict TEXT,created REAL NOT NULL);''')
            for role in registry():
                db.execute('INSERT OR IGNORE INTO agents VALUES(?,?,?)',(role['id'],'shadow' if role['implemented'] else 'candidate','Initial registry'))

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE');yield db;db.commit()
        except BaseException:
            db.rollback();raise
        finally:db.close()

    def enqueue(self,values):
        capability=values.get('capability')
        if capability not in HANDLERS:raise ValueError('Capability has no implemented handler.')
        payload=values.get('input')
        if not isinstance(payload,dict):raise ValueError('Object input required.')
        body=json.dumps(payload,sort_keys=True,allow_nan=False)
        if len(body.encode())>60000:raise ValueError('Task input exceeds 60KB.')
        if any(word in body.lower() for word in ('api_secret','access_token','api_key','password')):
            raise ValueError('Credentials must stay outside tasks.')
        from research import timestamp
        timestamp(values.get('evidenceCutoff',''))
        for field,low,high in [('priority',0,9),('budgetSeconds',1,30),('deadlineSeconds',1,3600)]:
            value=values.get(field)
            if type(value) is not int or not low<=value<=high:raise ValueError('Invalid '+field)
        key=values.get('idempotencyKey')
        if not isinstance(key,str) or not 1<=len(key)<=128:raise ValueError('Idempotency key required.')
        envelope=dict(input=payload,evidenceCutoff=values['evidenceCutoff'],version='agent-service-v1')
        body=json.dumps(envelope,sort_keys=True,allow_nan=False)
        fingerprint=hashlib.sha256(body.encode()).hexdigest()
        with self.db() as db:
            existing=db.execute('SELECT * FROM tasks WHERE key=?',(key,)).fetchone()
            if existing:
                if existing['fingerprint']!=fingerprint or existing['capability']!=capability:
                    raise ValueError('Idempotency key reused with different input.')
                return existing['id']
            identity=uuid.uuid4().hex;now=time.time()
            db.execute('INSERT INTO tasks(id,key,capability,body,fingerprint,priority,deadline,budget,state,created) VALUES(?,?,?,?,?,?,?,?,?,?)',(identity,key,capability,body,fingerprint,values['priority'],now+values['deadlineSeconds'],values['budgetSeconds'],'queued',now))
        return identity

    def run_once(self):
        with self.db() as db:
            now=time.time()
            db.execute("UPDATE tasks SET state=CASE WHEN attempts<3 THEN 'queued' ELSE 'failed' END,lease=NULL WHERE state='running' AND expires<=?",(now,))
            db.execute("UPDATE tasks SET state='expired' WHERE state='queued' AND deadline<=?",(now,))
            if db.execute("SELECT COUNT(*) FROM tasks WHERE state='running'").fetchone()[0]>=self.concurrency:return None
            row=db.execute("SELECT t.* FROM tasks t JOIN agents a ON a.id=t.capability WHERE t.state='queued' AND a.state IN ('shadow','active','probation') ORDER BY t.priority DESC,t.created LIMIT 1").fetchone()
            if row is None:return None
            lease=uuid.uuid4().hex
            db.execute("UPDATE tasks SET state='running',attempts=attempts+1,lease=?,expires=? WHERE id=?",(lease,now+row['budget'],row['id']))
        try:
            envelope=json.loads(row['body']);values=envelope['input']
            if 'asOf' in values and values['asOf']!=envelope['evidenceCutoff']:
                raise ValueError('Task cutoff differs from research cutoff.')
            if HANDLERS[row['capability']]=='scan':
                from trader_suite import scan
                output=scan(values)
            elif HANDLERS[row['capability']]=='risk':
                from trader_suite import risk_check
                output=risk_check(values)
            else:
                from evaluation import evaluate
                output=evaluate(values)
            encoded=json.dumps(output,allow_nan=False)
            if len(encoded.encode())>200000:raise ValueError('Output exceeds bound.')
            state='review'
        except Exception as exc:
            encoded=json.dumps(dict(errorType=type(exc).__name__,reason='Task failed validation or handler execution.'));state='failed'
        with self.db() as db:
            agent=db.execute('SELECT state FROM agents WHERE id=?',(row['capability'],)).fetchone()
            if time.time()>min(row['deadline'],now+row['budget']):state='expired'
            if agent['state'] in ('quarantined','retired'):state='cancelled'
            db.execute("UPDATE tasks SET state=?,output=?,lease=NULL WHERE id=? AND state='running' AND lease=?",(state,encoded,row['id'],lease))
        return row['id']

    def review(self,identity,reviewer,checks,critical=False):
        weights={'correctness':40,'evidence':20,'reproducibility':15,'completeness':15,'budget':10}
        if not isinstance(reviewer,str) or not reviewer.startswith('human:'):raise ValueError('Independent human reviewer identity required.')
        if not isinstance(checks,dict) or set(checks)!=set(weights) or any(type(v) is not bool for v in checks.values()) or type(critical) is not bool:
            raise ValueError('Provide five explicit Boolean review checks.')
        score=sum(weights[k] for k,v in checks.items() if v)
        with self.db() as db:
            row=db.execute('SELECT * FROM tasks WHERE id=?',(identity,)).fetchone()
            if not row or row['state']!='review':raise ValueError('Task is not awaiting review.')
            verdict=dict(reviewer=reviewer,checks=checks,score=score,critical=critical,reviewedAt=time.time())
            db.execute('UPDATE tasks SET verdict=?,state=? WHERE id=?',(json.dumps(verdict),'accepted' if score>=90 and not critical else 'rejected',identity))
            if critical:db.execute("UPDATE agents SET state='quarantined',reason='Critical independent review failure' WHERE id=?",(row['capability'],))
            else:
                records=db.execute('SELECT verdict FROM tasks WHERE capability=? AND verdict IS NOT NULL ORDER BY created DESC LIMIT 30',(row['capability'],)).fetchall()
                if len(records)==30 and sum(json.loads(r['verdict'])['score'] for r in records)/30<70:
                    db.execute("UPDATE agents SET state='probation',reason='Thirty reviewed cases below 70 average' WHERE id=?",(row['capability'],))

    def cancel(self,identity):
        with self.db() as db:
            db.execute("UPDATE tasks SET state='cancelled',lease=NULL WHERE id=? AND state IN ('queued','running','review')",(identity,))

    def lifecycle(self,identity,state,reason):
        if state not in STATES or not isinstance(reason,str) or not reason.strip():
            raise ValueError('Lifecycle state and operator reason required.')
        with self.db() as db:
            row=db.execute('SELECT * FROM agents WHERE id=?',(identity,)).fetchone()
            if not row:raise ValueError('Unknown agent.')
            if state in ('shadow','active','probation') and identity not in HANDLERS:
                raise ValueError('Unimplemented role cannot become eligible.')
            if row['state'] in ('quarantined','retired') and state not in ('quarantined','retired','candidate'):
                raise ValueError('Quarantined roles must return to candidate for independent revalidation.')
            if state=='active':
                reviews=db.execute("SELECT COUNT(*) FROM tasks WHERE capability=? AND state='accepted'",(identity,)).fetchone()[0]
                if reviews<30:raise ValueError('Thirty accepted independent reviews required before active status.')
            db.execute('UPDATE agents SET state=?,reason=? WHERE id=?',(state,reason[:500],identity))
            if state in ('quarantined','retired'):
                db.execute("UPDATE tasks SET state='cancelled',lease=NULL WHERE capability=? AND state IN ('queued','running','review')",(identity,))

    def status(self):
        with self.db() as db:
            roles=[dict(row) for row in db.execute('SELECT * FROM agents ORDER BY id')]
            tasks=[dict(row) for row in db.execute('SELECT id,capability,fingerprint,state,attempts,verdict,output FROM tasks ORDER BY created DESC LIMIT 50')]
        return dict(registered=108,implemented=len(HANDLERS),roles=roles,tasks=tasks,mode='research-shadow',executionAllowed=False)
