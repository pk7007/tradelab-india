"""Explicitly armed, fenced completed-candle paper worker. Never submits orders.

The provider fetch callback holds credentials outside this module. Decisions are
made at receipt; prices remain the paper model's assumed historical bar opens.
"""
import datetime as dt
import json
import math
import re
import sqlite3
import threading
import uuid

from market_contract import session_for
from research import IST, timestamp

UTC = dt.timezone.utc

# Only locally defined failure text is classified. Provider messages, payloads,
# and exception class names are never copied into persisted diagnostics.
_FAILURE_CODES = {
    'A processed candle changed. Create a separate account for revised history.': 'REVISED_PROCESSED_CANDLE',
    'Missing five-minute candle; import the missing interval first.': 'MISSING_CANDLE',
    'Missing open session; import its completed candles first.': 'MISSING_SESSION',
    'Session unknown; do not infer market open.': 'UNKNOWN_SESSION',
    'Incomplete session boundary; import the remaining candles first.': 'INCOMPLETE_SESSION_BOUNDARY',
    'Paper ledger mismatch; processing blocked.': 'LEDGER_MISMATCH',
    'Worker lease lost or expired; ingestion fenced.': 'LEASE_LOST',
    'Paper ingestion is paused or stopped.': 'ACCOUNT_PAUSED',
    'Special session unsupported by current paper engine; processing blocked.': 'UNSUPPORTED_SESSION',
    'No completed provider candles; no fill inferred.': 'NO_COMPLETED_CANDLES',
    'Provider completed candles are stale; ingestion blocked.': 'STALE_CANDLES',
    'Provider batch duplicated or unordered.': 'DUPLICATE_OR_UNORDERED_BATCH',
    'Provider returned out-of-range candle.': 'OUT_OF_RANGE_CANDLE',
    'Provider candle conflicts with supplied session calendar.': 'CALENDAR_CONFLICT',
}


class PaperWorker:
    def __init__(self, engine, fetch, clock=lambda: dt.datetime.now(UTC), lease_seconds=90, entry_authorized=None):
        if isinstance(lease_seconds,bool) or not isinstance(lease_seconds,(int,float)) or not math.isfinite(lease_seconds) or not 15<=lease_seconds<=300:
            raise ValueError('Lease must be 15–300 seconds.')
        self.engine=engine;self.fetch=fetch;self.clock=clock;self.lease_seconds=lease_seconds
        self.entry_authorized=entry_authorized
        self.owner=uuid.uuid4().hex;self.account=None;self.epoch=None;self.lock=threading.Lock()
        self.detail=dict(state='disarmed',enabled=False,live=False,mode='observed-candle-paper',lastError=None)
        with engine.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS paper_workers(account TEXT PRIMARY KEY,owner TEXT NOT NULL,epoch INTEGER NOT NULL,enabled INTEGER NOT NULL,expires REAL NOT NULL,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS worker_receipts(account TEXT NOT NULL,stamp TEXT NOT NULL,received TEXT NOT NULL,decision TEXT NOT NULL,mode TEXT NOT NULL,PRIMARY KEY(account,stamp));''')

    def _now(self):
        now=self.clock()
        if not isinstance(now,dt.datetime) or now.tzinfo is None: raise ValueError('Worker clock must be timezone aware.')
        return now.astimezone(UTC)

    def status(self):
        result=dict(self.detail)
        result.pop('calendar',None)
        result['enabled']=False
        if self.account:
            with self.engine.db() as db:
                row=db.execute('SELECT owner,epoch,enabled,expires,body FROM paper_workers WHERE account=?',(self.account,)).fetchone()
            if not row or row['owner']!=self.owner or row['epoch']!=self.epoch:
                result.update(state='disarmed',lastError='Worker ownership lost or stopped. Review before rearming.')
            else:
                result=json.loads(row['body']);result.pop('calendar',None);result['enabled']=False
            if row and row['owner']==self.owner and row['epoch']==self.epoch and not row['enabled']:
                result.update(state='stopped')
            elif row and row['owner']==self.owner and row['epoch']==self.epoch and row['expires']<=self._now().timestamp():
                result.update(state='expired',lastError='Worker heartbeat expired; new processing is blocked.')
            elif row and row['owner']==self.owner and row['epoch']==self.epoch: result['enabled']=True
            result['leaseUntil']=dt.datetime.fromtimestamp(row['expires'],UTC).isoformat() if row else None
        return result

    def start(self, account_id, instrument, calendar, retention_approved=False, calendar_confirmed=False):
        if retention_approved is not True or calendar_confirmed is not True:
            raise ValueError('Confirm permitted candle retention and the supplied session calendar.')
        if not isinstance(instrument,dict) or instrument.get('exchange')!='NSE' or not isinstance(instrument.get('symbol'),str) or not re.fullmatch(r'[A-Z0-9&-]{1,30}',instrument['symbol']) or type(instrument.get('token')) is not int or instrument['token']<=0:
            raise ValueError('Exact verified NSE symbol and positive instrument token required.')
        if not isinstance(calendar,dict) or not isinstance(calendar.get('version'),str) or not calendar['version'].strip():
            raise ValueError('A versioned explicit session calendar is required.')
        now=self._now();local=now.astimezone(IST)
        session_for(calendar,date=local.date().isoformat(),as_of=now.isoformat())
        with self.lock,self.engine.db() as db:
            s=self.engine.load(db,account_id)
            if s['config']['strategy']!='intraday-v1' or s['config']['source']!='imported' or s['config']['symbol']!=instrument['symbol']:
                raise ValueError('Choose a matching imported Intraday v1 paper account.')
            for date in calendar.get('sessions', {}):
                planned = session_for(calendar,date=date,as_of=now.isoformat())
                if planned['open']:
                    close = timestamp(planned['end'])
                    exit_open = dt.datetime.combine(close.date(),dt.time.fromisoformat(s['config']['squareOff']),IST)
                    if exit_open + dt.timedelta(minutes=5) >= close:
                        raise ValueError('Saved square-off candle must complete strictly before each continuous-session close.')
            if not self.engine.reconcile_in(db,s)['matches']: raise ValueError('Paper ledger mismatch; worker cannot arm.')
            db.execute("UPDATE entry_reviews SET state='invalidated' WHERE account=? AND state='eligible'",(account_id,))
            if s.get('pending') and s['pending']['side']=='BUY':
                s['pending']=None
            if db.execute('SELECT 1 FROM paper_workers WHERE account<>? AND enabled=1 AND expires>? LIMIT 1',
                          (account_id,now.timestamp())).fetchone():
                raise ValueError('Another worker owns an active paper account.')
            row=db.execute('SELECT * FROM paper_workers WHERE account=?',(account_id,)).fetchone()
            if row and row['enabled'] and row['expires']>now.timestamp() and row['owner']!=self.owner:
                raise ValueError('Another worker owns this account.')
            if row:
                previous=json.loads(row['body'])
                if previous['instrument']!=instrument: raise ValueError('Worker instrument binding changed; create a separate account.')
            elif s['lastBar'] or s['quantity']:
                raise ValueError('First worker attachment requires a new empty account to separate prior replay.')
            epoch=(row['epoch'] if row else 0)+1
            armed=local.replace(minute=(local.minute//5)*5,second=0,microsecond=0).isoformat()
            body=dict(accountId=account_id,instrument=dict(instrument),strategy='intraday-v1',calendar=calendar,calendarVersion=calendar['version'],armedAt=armed,heartbeat=now.isoformat(),lastAcceptedBar=s['lastBar'],state='armed',lastError=None,live=False,mode='observed-candle-paper')
            db.execute('INSERT OR REPLACE INTO paper_workers VALUES(?,?,?,?,?,?)',(account_id,self.owner,epoch,1,now.timestamp()+self.lease_seconds,json.dumps(body,allow_nan=False)))
            s['status']='running'
            self.engine.save(db,s,dict(type='worker-armed',detail='Explicit paper worker arm. Past observations warm up signals without new entries; no broker order.'))
        self.account=account_id;self.epoch=epoch;self.detail=body
        return self.status()

    def _assert(self,db):
        row=db.execute('SELECT * FROM paper_workers WHERE account=?',(self.account,)).fetchone()
        if not row or row['owner']!=self.owner or row['epoch']!=self.epoch or not row['enabled'] or row['expires']<=self._now().timestamp():
            raise ValueError('Worker lease lost or expired; ingestion fenced.')
        return row

    def _record(self,**changes):
        with self.engine.db() as db:
            row=self._assert(db)
            body=json.loads(row['body']);body.update(changes)
            db.execute('UPDATE paper_workers SET body=? WHERE account=?',(json.dumps(body,allow_nan=False),self.account))
        self.detail=body

    def stop(self):
        if not self.account: return self.status()
        with self.lock,self.engine.db() as db:
            row=db.execute('SELECT owner,epoch FROM paper_workers WHERE account=?',(self.account,)).fetchone()
            if row and row['owner']==self.owner and row['epoch']==self.epoch:
                db.execute('UPDATE paper_workers SET enabled=0 WHERE account=?',(self.account,))
                s=self.engine.load(db,self.account);s['status']='paused'
                self.engine.save(db,s,dict(type='worker-stopped',detail='Processing paused. Shares and pending exits preserved; no broker action.'))
        self.detail.update(state='stopped')
        return self.status()

    def _ingest(self,rows,received,warmup,calendar):
        calls=0;restore=False
        def guard(db):
            nonlocal calls,restore
            row=self._assert(db);now=self._now()
            if calls==0:
                s=self.engine.load(db,self.account)
                if warmup:
                    restore=not s.get('entriesPaused',False) and not s['quantity']
                    s['entriesPaused']=True
                    if s.get('pending') and s['pending']['side']=='BUY': s['pending']=None
                    self.engine.save(db,s,dict(type='worker-warmup',detail='Historical catch-up suppresses new entries. Existing exits remain eligible.'))
            else:
                if warmup and restore:
                    s=self.engine.load(db,self.account);s['entriesPaused']=False
                    self.engine.save(db,s,dict(type='worker-warmup-complete',detail='Historical catch-up complete; original entry pause restored.'))
                for bar in rows:
                    db.execute('INSERT OR IGNORE INTO worker_receipts VALUES(?,?,?,?,?)',(self.account,timestamp(bar['date']).isoformat(),received.isoformat(),now.isoformat(),'warmup' if warmup else 'observed-candle-paper'))
                body=json.loads(row['body']);body.update(heartbeat=now.isoformat(),lastAcceptedBar=rows[-1]['date'],state='running',lastError=None,lastErrorCode=None,failureStage=None)
                db.execute('UPDATE paper_workers SET body=?,expires=? WHERE account=?',(json.dumps(body),now.timestamp()+self.lease_seconds,self.account))
                self.detail=body
            calls+=1
        return self.engine.ingest(self.account,rows,True,transaction_guard=guard,session_calendar=calendar,
            entry_context=dict(owner=self.owner,epoch=self.epoch,instrument=dict(self.detail['instrument']),
                               clock=self._now,receivedAt=received.isoformat(),authorize=self.entry_authorized))

    def tick(self):
        if not self.account: raise ValueError('Explicitly arm a paper worker first.')
        if not self.lock.acquire(blocking=False): return dict(state='busy',live=False)
        stage='lease-check'
        try:
            now=self._now();local=now.astimezone(IST)
            with self.engine.db() as db:
                row=self._assert(db);body=json.loads(row['body']);s=self.engine.load(db,self.account)
                if s['status']!='running': raise ValueError('Paper ingestion is paused or stopped.')
                db.execute('UPDATE paper_workers SET expires=? WHERE account=?',(now.timestamp()+self.lease_seconds,self.account))
            stage='calendar-check'
            session=session_for(body['calendar'],date=local.date().isoformat(),as_of=now.isoformat())
            if not session['open']:
                self._record(state='waiting',heartbeat=now.isoformat(),lastError='Explicit calendar marks this date closed.')
                return self.status()
            opening=timestamp(session['start']);closing=timestamp(session['end'])
            if opening.time()!=dt.time(9,15) or closing.time() not in (dt.time(15,15),dt.time(15,30)):
                raise ValueError('Special session unsupported by current paper engine; processing blocked.')
            end=min(local,closing)
            if end<opening+dt.timedelta(minutes=5):
                self._record(state='waiting',heartbeat=now.isoformat(),lastError='Waiting for first completed session candle.')
                return self.status()
            start=timestamp(s['lastBar']) if s['lastBar'] else opening
            if local-start>dt.timedelta(days=7): raise ValueError('Backfill exceeds seven-day bound; review recovery manually.')
            # Every intervening date must be explicitly known, including holidays.
            date=start.date()
            windows=[]
            while date<=local.date():
                day=session_for(body['calendar'],date=date.isoformat(),as_of=now.isoformat())
                if day['open']:
                    # The historical API includes the end timestamp. Bound every
                    # day's request so a catch-up spanning a weekend also excludes CAS.
                    windows.append((max(start,timestamp(day['start'])),
                                    min(end,timestamp(day['end'])-dt.timedelta(seconds=1))))
                date+=dt.timedelta(days=1)
            raw=[]
            for first,last in windows:
                stage='provider-fetch'
                batch=self.fetch(dict(body['instrument']),first,last)
                stage='provider-validation'
                if not isinstance(batch,list) or len(raw)+len(batch)>1000:
                    raise ValueError('Provider batch must contain at most 1,000 candles.')
                raw.extend(batch)
            received=self._now()
            rows=[]
            for bar in raw:
                if not isinstance(bar,dict): raise ValueError('Malformed provider candle.')
                at=timestamp(bar['date'])
                if at<start or at>=closing: raise ValueError('Provider returned out-of-range candle.')
                bar_session=session_for(body['calendar'],date=at.date().isoformat(),as_of=now.isoformat())
                if not bar_session['open'] or not timestamp(bar_session['start'])<=at<timestamp(bar_session['end']):
                    raise ValueError('Provider candle conflicts with supplied session calendar.')
                if at+dt.timedelta(minutes=5)>end: continue
                rows.append(dict(bar))
            if not rows: raise ValueError('No completed provider candles; no fill inferred.')
            if any(timestamp(b['date'])<=timestamp(a['date']) for a,b in zip(rows,rows[1:])):
                raise ValueError('Provider batch duplicated or unordered.')
            latest=timestamp(rows[-1]['date'])+dt.timedelta(minutes=5)
            if end-latest>dt.timedelta(minutes=10): raise ValueError('Provider completed candles are stale; ingestion blocked.')
            boundary=timestamp(body['armedAt'])
            warmup=[r for r in rows if timestamp(r['date'])<boundary]
            forward=[r for r in rows if timestamp(r['date'])>=boundary]
            processed=duplicates=0
            stage='ingestion'
            for batch,is_warmup in ((warmup,True),(forward,False)):
                if batch:
                    result=self._ingest(batch,received,is_warmup,body['calendar'])
                    processed+=result['processed'];duplicates+=result['duplicates']
            return dict(**self.status(),processed=processed,duplicates=duplicates,receivedAt=received.isoformat(),decisionAt=self._now().isoformat())
        except Exception as exc:
            # No provider text or credentials are copied into diagnostics.
            login_failed = isinstance(exc,PermissionError) or (type(exc).__module__=='kiteconnect.exceptions' and
                                                               type(exc).__name__=='TokenException')
            code = ('BROKER_LOGIN_REQUIRED' if stage=='provider-fetch' and login_failed else
                    'PROVIDER_FETCH_FAILED' if stage=='provider-fetch' else
                    _FAILURE_CODES.get(str(exc), 'VALIDATION_FAILED') if type(exc) is ValueError else 'WORKER_FAILURE')
            failure=dict(state='blocked',lastErrorCode=code,failureStage=stage,
                         lastError='Paper worker blocked ['+code+'] during '+stage+'. Review before resuming.')
            self.detail.update(failure)
            try: self._record(**failure)
            except (ValueError,sqlite3.Error): pass
            raise
        finally:self.lock.release()
