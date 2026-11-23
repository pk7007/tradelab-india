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
from execution_controls import ExecutionControls

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
        if isinstance(c[k],bool): raise ValueError('Boolean is not a financial or strategy number: '+k)
        value=float(c[k])
        if not math.isfinite(value) or value!=int(value) or value<1:raise ValueError('Positive whole numbers required for '+k)
        c[k]=int(value)
    for k in ('capital','maxExposure','maxPositionValue','dailyLoss'):
        if isinstance(c[k],bool): raise ValueError('Boolean is not a financial or strategy number: '+k)
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
        self.funding = SharedReservations(self.path)
        self.controls = ExecutionControls(self)
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
                    intents=intents,events=events,funding=self.funding.status(),controls=self.controls.status(),blockers=['Exact strategy and limits require your approval.',
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
            account = snapshot.get('fundingAccount', 'offline-default')
            self.controls.guard_in(db, account)
            keys=('ageSeconds','exposure','positionValue','positionCount','loss','available','marginRequired','spreadBps')
            if any(k not in snapshot or isinstance(snapshot[k],bool) or not isinstance(snapshot[k],(int,float)) or not math.isfinite(snapshot[k]) or snapshot[k]<0 for k in keys):raise ValueError('Incomplete risk snapshot.')
            if snapshot['ageSeconds']>5 or snapshot.get('inSession') is not True or snapshot.get('externalMismatch') is not False:raise ValueError('Stale, outside session, or broker mismatch.')
            if isinstance(price,bool) or not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0:raise ValueError('Invalid price.')
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
            account = snapshot.get('fundingAccount', 'offline-default')
            if account == 'offline-default':
                db.execute('INSERT OR IGNORE INTO funding_accounts VALUES(?,?,0)', (account,SharedReservations.paise(snapshot['available'],round_up=False)))
            SharedReservations.reserve_in(db,identity,account,str(snapshot.get('book','intraday')),c['exchange']+':'+symbol+':'+c['product'],'BUY',quantity,max(value,snapshot['marginRequired']),snapshot.get('estimatedFees',0))
            try:db.execute('INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?,?,?)',(identity,version,symbol,'BUY',quantity,price,'PREPARED',None,0,now(),now()))
            except sqlite3.IntegrityError:raise ValueError('Duplicate intent.') from None
            self.event(db,'intent-prepared',identity)
            return identity
    def submit_mock(self,identity,broker):
        if getattr(broker,'mode',None)!='offline-mock':raise ValueError('Production submission is disabled.')
        with self.lock,self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if self.state!='running' or not self.reconciled:raise ValueError('Not running or unreconciled.')
            row=db.execute('SELECT * FROM intents WHERE id=?',(identity,)).fetchone()
            if not row or row['state']!='PREPARED':raise ValueError('Intent not eligible for submission.')
            latest=db.execute('SELECT MAX(version) FROM config').fetchone()[0]
            if row['version']!=latest:raise ValueError('Intent belongs to an obsolete strategy version.')
            # Re-read durable funding under the same write lock as the claim:
            # another process may have detected a mismatch after preparation.
            reservation=db.execute('SELECT r.*,a.blocked AS account_blocked,a.cash AS account_cash FROM funding_reservations r JOIN funding_accounts a ON a.account=r.account WHERE r.id=?',(identity,)).fetchone()
            if (not reservation or reservation['state']!='ACTIVE' or reservation['account_blocked']
                    or reservation['side']!=row['side'] or reservation['units']!=row['quantity'] or reservation['filled']!=0):
                raise ValueError('Active reconciled funding reservation required before submission.')
            self.controls.guard_in(db,reservation['account'])
            held=db.execute("SELECT COALESCE(SUM(cash+fees),0) FROM funding_reservations WHERE account=? AND state='ACTIVE'",(reservation['account'],)).fetchone()[0]
            if held>reservation['account_cash']:
                raise ValueError('Funding changed after preparation; reconcile before submission.')
            if db.execute("SELECT 1 FROM intents WHERE id!=? AND state IN ('UNKNOWN','SUBMITTING')",(identity,)).fetchone():
                raise ValueError('Uncertain order must be reconciled before submission.')
            db.execute("UPDATE intents SET state='SUBMITTING',updated=? WHERE id=?",(now(),identity))
        try:
            broker_id=broker.submit(dict(row))
            if not broker_id:raise ValueError('Missing broker order id')
        except Exception:
            with self.lock,self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                # A delayed transport failure cannot erase broker evidence that
                # arrived via reconciliation while submit was in flight.
                db.execute("UPDATE intents SET state='UNKNOWN',updated=? WHERE id=? AND state='SUBMITTING'",(now(),identity))
                self.controls.kill_in(db,reservation['account'],'Entry submission outcome unknown; reconcile before rearm.')
                self.state='faulted';self.reconciled=False;self.event(db,'submission-unknown',identity)
            return
        with self.lock,self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT * FROM intents WHERE id=?',(identity,)).fetchone()
            if current['broker_id'] and current['broker_id'] != str(broker_id):
                if current['state'] not in TERMINAL:
                    db.execute("UPDATE intents SET state='UNKNOWN',updated=? WHERE id=?",(now(),identity))
                db.execute('UPDATE funding_accounts SET blocked=1')
                self.state='faulted';self.reconciled=False
                self.controls.kill_in(db,reservation['account'],'Entry acknowledgement identity conflicts.')
                self.event(db,'acknowledgement-id-mismatch',identity)
            else:
                # ACK establishes acceptance only; preserve partial, terminal,
                # or previously uncertain reconciliation states and fill counts.
                db.execute("UPDATE intents SET state=CASE WHEN state='SUBMITTING' THEN 'OPEN' ELSE state END,broker_id=COALESCE(broker_id,?),updated=? WHERE id=?",(str(broker_id),now(),identity))
                self.event(db,'mock-submitted',identity)
    def reconcile_mock(self,updates,external_mismatch=False):
        with self.lock,self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if external_mismatch:
                db.execute('UPDATE funding_accounts SET blocked=1')
                for account_row in db.execute('SELECT account FROM funding_accounts').fetchall():
                    self.controls.kill_in(db,account_row['account'],'Broker/local account mismatch requires operator review.')
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
                SharedReservations.settle_in(db,row['id'],state,filled)
                db.execute('UPDATE intents SET state=?,filled=?,broker_id=?,updated=? WHERE id=?',(state,filled,update.get('broker_id',row['broker_id']),now(),row['id']))
            unresolved=db.execute("SELECT 1 FROM intents WHERE state IN ('SUBMITTING','UNKNOWN','PREPARED')").fetchone()
            if external_mismatch:
                db.execute('UPDATE funding_accounts SET blocked=1')
                for account_row in db.execute('SELECT account FROM funding_accounts').fetchall():
                    self.controls.kill_in(db,account_row['account'],'Broker/local account mismatch requires operator review.')
            funding_blocked = db.execute('SELECT 1 FROM funding_accounts WHERE blocked=1').fetchone()
            self.reconciled=not unresolved and not external_mismatch and not funding_blocked
            if not self.reconciled:self.state='faulted'
            self.event(db,'mock-reconciled','Matched' if self.reconciled else 'Uncertainty or external mismatch; disarmed.')
        return self.status()

    def emergency_stop_mock(self,account,reason):
        return self.controls.kill(account,reason)
    def protective_mock(self,account,instrument,broker,**values):
        return self.controls.ensure_protection_mock(account,instrument,broker,**values)
    def session_tick_mock(self,account,*,as_of):
        return self.controls.clock_tick(account,as_of=as_of)

class SharedReservations:
    """Offline shared funding ledger. Monetary amounts are integer paise.

    One database must be shared by all books using the same funding account.
    Snapshot replacement is explicit and blocked while reservations are active.
    This is not a broker adapter or proof of production reconciliation.
    """
    def __init__(self, path):
        self.path = Path(path)
        with self.db() as db:
            self.schema(db)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def schema(db):
        db.executescript('''
        CREATE TABLE IF NOT EXISTS funding_accounts(account TEXT PRIMARY KEY, cash INTEGER NOT NULL, blocked INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS funding_inventory(account TEXT NOT NULL, instrument TEXT NOT NULL, units INTEGER NOT NULL, PRIMARY KEY(account,instrument));
        CREATE TABLE IF NOT EXISTS funding_reservations(id TEXT PRIMARY KEY, account TEXT NOT NULL, book TEXT NOT NULL, instrument TEXT NOT NULL, side TEXT NOT NULL, units INTEGER NOT NULL, cash INTEGER NOT NULL, fees INTEGER NOT NULL, state TEXT NOT NULL, filled INTEGER NOT NULL DEFAULT 0);
        ''')

    @staticmethod
    def paise(value, round_up=True):
        from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise ValueError('Invalid funding amount.')
        return int((amount * 100).to_integral_value(rounding=ROUND_CEILING if round_up else ROUND_FLOOR))

    def reconcile(self, account, cash, inventory, external_mismatch=False):
        """Apply an explicitly supplied mock balance; never infer broker truth."""
        amount = self.paise(cash,round_up=False)
        if not account or any(type(v) is not int or v < 0 for v in inventory.values()):
            raise ValueError('Invalid funding snapshot.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            active = db.execute("SELECT 1 FROM funding_reservations WHERE account=? AND state='ACTIVE'", (account,)).fetchone()
            if external_mismatch or active:
                db.execute('INSERT INTO funding_accounts VALUES(?,?,1) ON CONFLICT(account) DO UPDATE SET blocked=1', (account, amount))
                return False
            db.execute('INSERT INTO funding_accounts VALUES(?,?,0) ON CONFLICT(account) DO UPDATE SET cash=excluded.cash,blocked=0', (account, amount))
            db.execute('DELETE FROM funding_inventory WHERE account=?', (account,))
            db.executemany('INSERT INTO funding_inventory VALUES(?,?,?)', [(account,k,v) for k,v in inventory.items()])
            return True

    @classmethod
    def reserve_in(cls, db, identity, account, book, instrument, side, units, value, fees=0):
        if any(not isinstance(v,str) or not v.strip() for v in (identity,account,book,instrument)):
            raise ValueError('Reservation identity and scope are required.')
        if side not in ('BUY','SELL') or type(units) is not int or units <= 0:
            raise ValueError('Invalid reservation.')
        cash, fee = cls.paise(value), cls.paise(fees)
        row = db.execute('SELECT cash,blocked FROM funding_accounts WHERE account=?', (account,)).fetchone()
        if row is None or row[1]:
            raise ValueError('Shared funding account requires reconciliation.')
        reserved = db.execute("SELECT COALESCE(SUM(cash+fees),0) FROM funding_reservations WHERE account=? AND state='ACTIVE'", (account,)).fetchone()[0]
        required = cash if side == 'BUY' else 0
        if required + fee + reserved > row[0]:
            raise ValueError('Shared cash reservation exceeds available funds including fees.')
        if side == 'SELL':
            stock = db.execute('SELECT units FROM funding_inventory WHERE account=? AND instrument=?', (account,instrument)).fetchone()
            held = db.execute("SELECT COALESCE(SUM(units),0) FROM funding_reservations WHERE account=? AND instrument=? AND side='SELL' AND state='ACTIVE'", (account,instrument)).fetchone()[0]
            if units + held > (stock[0] if stock else 0):
                raise ValueError('Shared inventory already reserved or unavailable.')
        try:
            db.execute('INSERT INTO funding_reservations VALUES(?,?,?,?,?,?,?,?,?,0)', (identity,account,book,instrument,side,units,required,fee,'ACTIVE'))
        except sqlite3.IntegrityError:
            raise ValueError('Duplicate funding reservation.') from None

    def reserve(self, identity, account, book, instrument, side, units, value, fees=0):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.reserve_in(db,identity,account,book,instrument,side,units,value,fees)

    @staticmethod
    def settle_in(db, identity, state, filled):
        row = db.execute('SELECT account,instrument,side,units,cash,fees,state,filled FROM funding_reservations WHERE id=?', (identity,)).fetchone()
        if not row:
            raise ValueError('Missing funding reservation; reconcile ledger before resolving intent.')
        if type(filled) is not int or not row[7] <= filled <= row[3]:
            raise ValueError('Regressive reservation fill.')
        if state not in (*ACTIVE,*TERMINAL):
            raise ValueError('Invalid settlement state.')
        if (state == 'COMPLETE' and filled != row[3]) or (state in ('OPEN','REJECTED','PREPARED') and filled) or (state == 'PARTIAL' and not 0 < filled < row[3]):
            raise ValueError('Settlement state conflicts with fill quantity.')
        if row[6] != 'ACTIVE':
            if state != row[6] or filled != row[7]:
                raise ValueError('Terminal reservation regression.')
            return
        if state not in TERMINAL:
            # Keep the entire reservation through unknown and partial outcomes.
            db.execute('UPDATE funding_reservations SET filled=? WHERE id=?', (filled,identity))
            return
        # Conservative modeled debit. Actual execution price and fees must be
        # reconciled explicitly before another order is admitted after a fill.
        consumed = ((row[4] * filled + row[3] - 1) // row[3]) + (row[5] if filled else 0)
        db.execute('UPDATE funding_accounts SET cash=cash-?,blocked=MAX(blocked,?) WHERE account=?', (consumed,int(filled>0),row[0]))
        if row[2] == 'SELL':
            db.execute('UPDATE funding_inventory SET units=units-? WHERE account=? AND instrument=?', (filled,row[0],row[1]))
        db.execute('UPDATE funding_reservations SET state=?,filled=? WHERE id=?', (state,filled,identity))

    def settle(self, identity, state, filled):
        if state not in (*ACTIVE,*TERMINAL):
            raise ValueError('Invalid settlement state.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.settle_in(db,identity,state,filled)

    def status(self):
        with self.db() as db:
            db.row_factory = sqlite3.Row
            return {'accounts':[dict(r) for r in db.execute('SELECT * FROM funding_accounts')],
                    'reservations':[dict(r) for r in db.execute('SELECT * FROM funding_reservations')]}
