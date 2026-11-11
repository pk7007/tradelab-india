"""Durable execution coordinator. HTTP control surface never submits broker orders.
The broker protocol is exercised by offline tests; production activation is gated.
"""
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading

ACTIVE=('PREPARED','SUBMITTING','UNKNOWN','OPEN','PARTIAL')
TERMINAL=('COMPLETE','CANCELLED','REJECTED')

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()

def validate_config(raw):
    fields=('symbols','units','capital','maxExposure','maxPositionValue','maxPositions','dailyLoss','ordersPerMinute','fast','slow','start','end','exitPolicy')
    if any(k not in raw or raw[k] in ('',None) for k in fields):
        raise ValueError('Complete every strategy and financial-limit field.')
    c={k:raw[k] for k in fields}
    symbols=list(dict.fromkeys(str(c['symbols']).upper().replace(' ','').split(',')))
    if not 1<=len(symbols)<=25 or any(not re.fullmatch(r'[A-Z0-9&-]{1,30}',s) for s in symbols):raise ValueError('Use 1–25 exact NSE symbols.')
    c['symbols']=symbols
    for k in ('units','maxPositions','ordersPerMinute','fast','slow'):
        value=float(c[k])
        if not math.isfinite(value) or value!=int(value) or value<1:raise ValueError('Positive whole numbers required for '+k)
        c[k]=int(value)
    for k in ('capital','maxExposure','maxPositionValue','dailyLoss'):
        c[k]=float(c[k])
        if not math.isfinite(c[k]) or c[k]<=0:raise ValueError('Positive finite amount required for '+k)
    if not 2<=c['fast']<c['slow']<=200:raise ValueError('Use 2 <= fast < slow <= 200.')
    if c['maxPositionValue']>c['maxExposure'] or c['maxExposure']>c['capital']:raise ValueError('Position limit <= exposure limit <= allocated capital required.')
    if c['dailyLoss']>c['capital'] or c['ordersPerMinute']>30:raise ValueError('Daily loss cannot exceed capital; application caps orders at 30/minute.')
    start=dt.time.fromisoformat(c['start']);end=dt.time.fromisoformat(c['end'])
    if not dt.time(9,15)<=start<end<=dt.time(15,15):raise ValueError('Use an IST entry window within 09:15–15:15.')
    if c['exitPolicy']!='manual-review':raise ValueError('Only explicit manual recovery of unfilled exits is currently supported.')
    c.update(exchange='NSE',product='MIS',timeframe='5minute',overnight=False,strategy='sma-cross-long-only',approved=False)
    return c

class Coordinator:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.state='disabled';self.reconciled=False
        with self.db() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS config(version INTEGER PRIMARY KEY,body TEXT NOT NULL,created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS intents(id TEXT PRIMARY KEY,version INTEGER NOT NULL,symbol TEXT NOT NULL,side TEXT NOT NULL,quantity INTEGER NOT NULL,price REAL NOT NULL,state TEXT NOT NULL,broker_id TEXT,filled INTEGER DEFAULT 0,created TEXT NOT NULL,updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT NOT NULL,event TEXT NOT NULL,detail TEXT NOT NULL);
            PRAGMA user_version=1;""")
            db.execute("UPDATE intents SET state='UNKNOWN',updated=? WHERE state='SUBMITTING'",(now(),))
            self.event(db,'startup','Disarmed. Reconcile before any execution; no automatic resume.')
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()
    def event(self,db,event,detail):db.execute('INSERT INTO audit(at,event,detail) VALUES(?,?,?)',(now(),event,detail))
    def save(self,values):
        c=validate_config(values)
        with self.lock,self.db() as db:
            if self.state=='running':raise ValueError('Stop before editing configuration.')
            version=db.execute('SELECT COALESCE(MAX(version),0)+1 FROM config').fetchone()[0]
            db.execute('INSERT INTO config VALUES(?,?,?)',(version,json.dumps(c),now()))
            self.event(db,'config-saved','Version '+str(version)+'; not approved for live use.')
            self.state='disabled';self.reconciled=False
        return self.status()
    def status(self):
        with self.lock,self.db() as db:
            cfg=db.execute('SELECT * FROM config ORDER BY version DESC LIMIT 1').fetchone()
            intents=[dict(r) for r in db.execute('SELECT * FROM intents ORDER BY created DESC LIMIT 100')]
            events=[dict(r) for r in db.execute('SELECT * FROM audit ORDER BY seq DESC LIMIT 60')]
        return dict(state=self.state,reconciled=self.reconciled,liveEnabled=False,
                    config=json.loads(cfg['body']) if cfg else None,version=cfg['version'] if cfg else None,
                    intents=intents,events=events,blockers=['Exact strategy and limits require your approval.',
                    'Production broker execution adapter and supervised readiness validation remain incomplete.',
                    'Registered static IP and broker requirements must be verified.'])
    def control(self,action):
        with self.lock,self.db() as db:
            if action=='start':
                self.event(db,'start-blocked','Live activation unavailable; approval and production readiness pending.')
            elif action in ('pause','stop'):
                self.state='paused' if action=='pause' else 'disabled'
                self.event(db,action,'New entries disabled. Existing positions and broker orders are unchanged.')
            else:raise ValueError('Unknown control action.')
        return self.status()
    def prepare(self,signal,version,symbol,quantity,price,snapshot):
        """Durable duplicate and risk checks, mock execution protocol only."""
        with self.lock,self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM config ORDER BY version DESC LIMIT 1').fetchone()
            if not row or row['version']!=version:raise ValueError('Configuration version mismatch.')
            c=json.loads(row['body'])
            if self.state!='running' or not self.reconciled:raise ValueError('Disarmed or unreconciled.')
            if symbol not in c['symbols'] or quantity!=c['units']:raise ValueError('Instrument or size not approved.')
            keys=('ageSeconds','exposure','positionValue','positionCount','loss','available','marginRequired','spreadBps')
            if any(k not in snapshot or not isinstance(snapshot[k],(int,float)) or not math.isfinite(snapshot[k]) or snapshot[k]<0 for k in keys):raise ValueError('Incomplete risk snapshot.')
            if snapshot['ageSeconds']>5 or not snapshot.get('inSession') or snapshot.get('externalMismatch'):raise ValueError('Stale, outside session, or broker mismatch.')
            if not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0:raise ValueError('Invalid price.')
            if db.execute("SELECT 1 FROM intents WHERE state IN ('UNKNOWN','SUBMITTING')").fetchone():raise ValueError('Uncertain order must be reconciled.')
            pending=db.execute("SELECT COALESCE(SUM((quantity-filled)*price),0) FROM intents WHERE state IN ('PREPARED','OPEN','PARTIAL')").fetchone()[0]
            symbol_pending=db.execute("SELECT COALESCE(SUM((quantity-filled)*price),0) FROM intents WHERE symbol=? AND state IN ('PREPARED','OPEN','PARTIAL')",(symbol,)).fetchone()[0]
            pending_symbols=db.execute("SELECT COUNT(DISTINCT symbol) FROM intents WHERE state IN ('PREPARED','OPEN','PARTIAL')").fetchone()[0]
            value=quantity*price
            if snapshot['exposure']+pending+value>c['maxExposure'] or snapshot['positionValue']+symbol_pending+value>c['maxPositionValue']:raise ValueError('Exposure limit.')
            if snapshot['positionCount']+pending_symbols>=c['maxPositions'] or snapshot['loss']>=c['dailyLoss']:raise ValueError('Position or daily loss limit.')
            if snapshot['available']<snapshot['marginRequired']+pending or snapshot['available']<value+pending:raise ValueError('Insufficient available funds.')
            if snapshot['spreadBps']>20:raise ValueError('Spread exceeds conservative prototype limit.')
            cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=1)).isoformat()
            if db.execute('SELECT COUNT(*) FROM intents WHERE created>=?',(cutoff,)).fetchone()[0]>=c['ordersPerMinute']:raise ValueError('Order frequency limit.')
            identity=hashlib.sha256((str(version)+':'+signal).encode()).hexdigest()[:20]
            try:db.execute('INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?,?,?)',(identity,version,symbol,'BUY',quantity,price,'PREPARED',None,0,now(),now()))
            except sqlite3.IntegrityError:raise ValueError('Duplicate intent.') from None
            self.event(db,'intent-prepared',identity)
            return identity
    def submit_mock(self,identity,broker):
        if getattr(broker,'mode',None)!='offline-mock':raise ValueError('Production submission is disabled.')
        with self.lock,self.db() as db:
            if self.state!='running' or not self.reconciled:raise ValueError('Not running or unreconciled.')
            row=db.execute('SELECT * FROM intents WHERE id=?',(identity,)).fetchone()
            if not row or row['state']!='PREPARED':raise ValueError('Intent not eligible for submission.')
            latest=db.execute('SELECT MAX(version) FROM config').fetchone()[0]
            if row['version']!=latest:raise ValueError('Intent belongs to an obsolete strategy version.')
            db.execute("UPDATE intents SET state='SUBMITTING',updated=? WHERE id=?",(now(),identity))
        try:
            broker_id=broker.submit(dict(row))
            if not broker_id:raise ValueError('Missing broker order id')
        except Exception:
            with self.lock,self.db() as db:
                db.execute("UPDATE intents SET state='UNKNOWN',updated=? WHERE id=?",(now(),identity))
                self.state='faulted';self.reconciled=False;self.event(db,'submission-unknown',identity)
            return
        with self.lock,self.db() as db:
            db.execute("UPDATE intents SET state='OPEN',broker_id=?,updated=? WHERE id=?",(str(broker_id),now(),identity))
            self.event(db,'mock-submitted',identity)
    def reconcile_mock(self,updates,external_mismatch=False):
        with self.lock,self.db() as db:
            for update in updates:
                row=db.execute('SELECT * FROM intents WHERE id=?',(update['id'],)).fetchone()
                if not row:external_mismatch=True;continue
                state=update['state'];filled=update['filled']
                if row['broker_id'] and update.get('broker_id',row['broker_id']) != row['broker_id']:
                    external_mismatch=True
                    if row['state'] not in TERMINAL:
                        db.execute("UPDATE intents SET state='UNKNOWN',updated=? WHERE id=?", (now(),row['id']))
                    self.event(db,'reconciliation-id-mismatch',row['id'])
                    continue
                if row['state']=='UNKNOWN' and not update.get('broker_id'):
                    external_mismatch=True
                    continue
                if state not in (*TERMINAL,'OPEN','PARTIAL') or type(filled) is not int or not row['filled']<=filled<=row['quantity']:raise ValueError('Invalid or regressive broker update.')
                if (state=='PARTIAL' and not 0<filled<row['quantity']) or (state in ('OPEN','REJECTED') and filled):
                    raise ValueError('Fill quantity conflicts with order state.')
                if state=='COMPLETE' and filled!=row['quantity']:raise ValueError('Incomplete fill cannot be complete.')
                if row['state'] in TERMINAL and (state!=row['state'] or filled!=row['filled']):raise ValueError('Terminal state regression.')
                db.execute('UPDATE intents SET state=?,filled=?,broker_id=?,updated=? WHERE id=?',(state,filled,update.get('broker_id',row['broker_id']),now(),row['id']))
            unresolved=db.execute("SELECT 1 FROM intents WHERE state IN ('SUBMITTING','UNKNOWN','PREPARED')").fetchone()
            self.reconciled=not unresolved and not external_mismatch
            if not self.reconciled:self.state='faulted'
            self.event(db,'mock-reconciled','Matched' if self.reconciled else 'Uncertainty or external mismatch; disarmed.')
        return self.status()
