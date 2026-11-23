"""Mock-only durable emergency, protective and clock controls for Coordinator."""
import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from market_contract import session_for
from research import IST, timestamp

WORKING={'OPEN','PARTIAL','TRIGGER PENDING'}
DONE={'COMPLETE','CANCELLED','REJECTED'}
PENDING={'SUBMITTING','UNKNOWN','ACKNOWLEDGED'}


def _account(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',value):
        raise ValueError('Exact offline account identity required.')
    return value


def _price(value):
    if isinstance(value,bool):raise ValueError('Positive decimal price required.')
    try:result=Decimal(str(value))
    except InvalidOperation:raise ValueError('Positive decimal price required.') from None
    if not result.is_finite() or result<=0:raise ValueError('Positive decimal price required.')
    return result


class ExecutionControls:
    def __init__(self,engine):
        self.engine=engine
        with engine.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS emergency_controls(account TEXT PRIMARY KEY,active INTEGER NOT NULL,
                reason TEXT NOT NULL,revision INTEGER NOT NULL,reviewed_by TEXT,updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS control_evidence(account TEXT PRIMARY KEY,revision INTEGER NOT NULL,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS control_actions(id TEXT PRIMARY KEY,account TEXT NOT NULL,instrument TEXT NOT NULL,
                kind TEXT NOT NULL,quantity INTEGER NOT NULL,state TEXT NOT NULL,broker_id TEXT,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS control_sessions(account TEXT NOT NULL,day TEXT NOT NULL,body TEXT NOT NULL,
                PRIMARY KEY(account,day));''')
            rows=db.execute("SELECT DISTINCT account FROM control_actions WHERE state='SUBMITTING'").fetchall()
            db.execute("UPDATE control_actions SET state='UNKNOWN' WHERE state='SUBMITTING'")
            for row in rows:self.kill_in(db,row[0],'Restart with uncertain protective action.')

    @staticmethod
    def kill_in(db,account,reason):
        if not isinstance(reason,str) or not 1<=len(reason)<=250:raise ValueError('Bounded emergency reason required.')
        db.execute('''INSERT INTO emergency_controls VALUES(?,1,?,1,NULL,?)
            ON CONFLICT(account) DO UPDATE SET active=1,reason=excluded.reason,
            revision=emergency_controls.revision+1,reviewed_by=NULL,updated=excluded.updated''',
            (account,reason,dt.datetime.now(dt.timezone.utc).isoformat()))

    def kill(self,account,reason):
        _account(account)
        with self.engine.lock,self.engine.db() as db:
            db.execute('BEGIN IMMEDIATE');self.kill_in(db,account,reason)
            self.engine.event(db,'emergency-latched',account+': '+reason)
        self.engine.state='faulted'
        return self.status()

    @staticmethod
    def guard_in(db,account):
        row=db.execute('SELECT active FROM emergency_controls WHERE account=?',(account,)).fetchone()
        if row and row[0]:raise ValueError('Persistent emergency kill blocks new entries.')
        row=db.execute('SELECT body FROM control_sessions WHERE account=? ORDER BY day DESC LIMIT 1',(account,)).fetchone()
        if row and json.loads(row[0])['phase']!='OPEN':raise ValueError('Clock-driven session cutoff blocks new entries.')

    def status(self):
        with self.engine.db() as db:
            return dict(kills=[dict(row) for row in db.execute('SELECT * FROM emergency_controls')],
                actions=[dict(row) for row in db.execute('SELECT * FROM control_actions ORDER BY rowid DESC LIMIT 100')],
                sessions=[json.loads(row[0]) for row in db.execute('SELECT body FROM control_sessions')],
                liveEnabled=False,mode='offline-mock',
                limitations=['No live adapter or authenticated operator interface.',
                    'Clock ticks require an independent caller; they never manufacture fills.',
                    'Broker acknowledgement is not confirmed protection or liquidation.'])

    def observe(self,account,broker,*,as_of):
        _account(account)
        if getattr(broker,'mode',None)!='offline-mock':raise ValueError('Live protective operations are disabled.')
        payload=broker.snapshot(account)
        if not isinstance(payload,dict) or payload.get('account')!=account:raise ValueError('Mock account mismatch.')
        revision=payload.get('revision')
        if type(revision) is not int or revision<1:raise ValueError('Monotonic snapshot revision required.')
        if not 0<=(timestamp(as_of)-timestamp(payload.get('receivedAt',''))).total_seconds()<=5:
            raise ValueError('Stale or future broker-position evidence.')
        positions,orders=payload.get('positions'),payload.get('orders')
        if not isinstance(positions,dict) or len(positions)>1000 or not isinstance(orders,list) or len(orders)>1000:
            raise ValueError('Bounded complete positions and orders required.')
        for scope,quantity in positions.items():
            if not isinstance(scope,str) or not re.fullmatch(r'NSE:[A-Z0-9&-]{1,30}:MIS',scope):
                raise ValueError('Exact NSE MIS instrument scope required.')
            if type(quantity) is not int or quantity<0:raise ValueError('Unsupported short or invalid position.')
        ids=set()
        for order in orders:
            if not isinstance(order,dict) or not isinstance(order.get('id'),str) or not order['id'] or order['id'] in ids:
                raise ValueError('Unique broker order identity required.')
            ids.add(order['id'])
            if order.get('instrument') not in positions or order.get('side') not in ('BUY','SELL'):
                raise ValueError('Order scope missing from position book.')
            units,filled,state=order.get('quantity'),order.get('filled'),order.get('state')
            if type(units) is not int or type(filled) is not int or not 0<=filled<=units or units<1:
                raise ValueError('Invalid filled quantity.')
            if state not in WORKING|DONE:raise ValueError('Unknown broker order state.')
            if ((state=='COMPLETE' and filled!=units) or (state in ('OPEN','TRIGGER PENDING','REJECTED') and filled)
                or (state=='PARTIAL' and not 0<filled<units)):raise ValueError('Order state conflicts with fills.')
        body=json.dumps(payload,sort_keys=True,allow_nan=False)
        with self.engine.lock,self.engine.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT revision,body FROM control_evidence WHERE account=?',(account,)).fetchone()
            if prior and (revision<prior[0] or (revision==prior[0] and prior[1]!=body) or timestamp(payload['receivedAt'])<timestamp(json.loads(prior[1])['receivedAt'])):
                raise ValueError('Regressive or conflicting broker snapshot.')
            db.execute('INSERT OR REPLACE INTO control_evidence VALUES(?,?,?)',(account,revision,body))
            for action in db.execute("SELECT * FROM control_actions WHERE account=? AND kind IN ('STOP','CANCEL')",(account,)).fetchall():
                expected=json.loads(action['body'])
                matches=[order for order in orders if order.get('clientId')==action['id']
                    or (action['broker_id'] and order['id']==action['broker_id'])]
                if action['kind']=='CANCEL':
                    matches=[order for order in orders if order['id']==expected['targetOrderId']]
                if len(matches)!=1:
                    if action['state'] not in DONE:
                        db.execute("UPDATE control_actions SET state='UNKNOWN' WHERE id=?",(action['id'],))
                        self.kill_in(db,account,'Protective identity missing or ambiguous in broker evidence.')
                    continue
                order=matches[0]
                if order['filled']<expected.get('observedFilled',0):
                    self.kill_in(db,account,'Protective fill evidence regressed.')
                    continue
                if action['kind']=='CANCEL':
                    state=order['state'] if order['state'] in DONE else 'ACKNOWLEDGED'
                elif (order['instrument']!=action['instrument'] or order['side']!='SELL'
                      or order['quantity']!=action['quantity'] or order.get('kind')!='SL'
                      or order.get('triggerPrice')!=expected['triggerPrice']
                      or order.get('limitPrice')!=expected['limitPrice']):
                    db.execute("UPDATE control_actions SET state='UNKNOWN' WHERE id=?",(action['id'],))
                    self.kill_in(db,account,'Protective order differs from persisted intent.');continue
                else:state=order['state']
                if action['state'] in DONE and state!=action['state']:
                    self.kill_in(db,account,'Terminal protective evidence regressed.');continue
                expected['observedFilled']=order['filled']
                db.execute('UPDATE control_actions SET state=?,broker_id=?,body=? WHERE id=?',(state,order['id'],json.dumps(expected),action['id']))
                if action['kind']=='STOP' and state in ('REJECTED','CANCELLED') and positions[order['instrument']]:
                    self.kill_in(db,account,'Confirmed exposure lacks its protective order.')
        return payload

    def ensure_protection_mock(self,account,instrument,broker,*,trigger_price,limit_price,tick_size,as_of):
        trigger,limit,tick=map(_price,(trigger_price,limit_price,tick_size))
        if limit>trigger or trigger%tick or limit%tick:raise ValueError('Valid SELL SL trigger/limit tick multiples required.')
        try:observed=self.observe(account,broker,as_of=as_of)
        except Exception:
            self.kill(account,'Protective evidence unavailable or invalid.');raise
        held=observed['positions'].get(instrument)
        if held is None:raise ValueError('Instrument absent from complete account evidence.')
        exits=[row for row in observed['orders'] if row['instrument']==instrument and row['side']=='SELL' and row['state'] in WORKING]
        remaining=sum(row['quantity']-row['filled'] for row in exits)
        with self.engine.db() as db:
            owned=db.execute('''SELECT COALESCE(SUM(CASE WHEN i.side='BUY' THEN i.filled ELSE -i.filled END),0) FROM intents i JOIN funding_reservations r ON r.id=i.id
                WHERE r.account=? AND r.instrument=? ''',(account,instrument)).fetchone()[0]
            owned-=sum(json.loads(row[0]).get('observedFilled',0) for row in db.execute("SELECT body FROM control_actions WHERE account=? AND instrument=? AND kind='STOP'",(account,instrument)))
            known={row[0] for row in db.execute("SELECT broker_id FROM control_actions WHERE account=? AND kind='STOP' AND state IN ('OPEN','PARTIAL','TRIGGER PENDING')",(account,))}
        if held!=owned or remaining>held:
            self.kill(account,'Unexpected ownership or oversized exit could reverse position.')
            raise ValueError('Unowned exposure or exit exceeds confirmed position.')
        if exits:
            if (len(exits)==1 and exits[0]['id'] in known and exits[0].get('kind')=='SL' and remaining==held
                and _price(exits[0].get('triggerPrice'))==trigger and _price(exits[0].get('limitPrice'))==limit):
                return dict(state='COVERED',quantity=held,brokerOrderId=exits[0]['id'],executionAllowed=False)
            self.kill(account,'Conflicting or incomplete exit coverage requires confirmed cancellation.')
            raise ValueError('Conflicting exit requires cancellation and a new broker observation.')
        if not held:
            with self.engine.db() as db:
                unresolved=db.execute("SELECT 1 FROM control_actions WHERE account=? AND kind IN ('STOP','CANCEL') AND state NOT IN ('COMPLETE','CANCELLED','REJECTED')",(account,)).fetchone()
            return dict(state='UNRESOLVED_ORDERS' if unresolved else 'FLAT_CONFIRMED',quantity=0,executionAllowed=False)
        with self.engine.lock,self.engine.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM control_actions WHERE account=? AND instrument=? AND kind='STOP' AND state IN ('SUBMITTING','UNKNOWN','ACKNOWLEDGED','OPEN','PARTIAL','TRIGGER PENDING')",(account,instrument)).fetchone():
                raise ValueError('Existing protective action requires reconciliation; no resubmission.')
            identity=hashlib.sha256(json.dumps([account,instrument,observed['revision'],str(trigger),str(limit)]).encode()).hexdigest()
            request=dict(clientId=identity,account=account,instrument=instrument,side='SELL',kind='SL',quantity=held,
                         triggerPrice=str(trigger),limitPrice=str(limit))
            db.execute('INSERT INTO control_actions VALUES(?,?,?,?,?,?,?,?)',(identity,account,instrument,'STOP',held,'SUBMITTING',None,json.dumps(request)))
        return self._perform(account,identity,broker,lambda:broker.place_protective(request),quantity=held)

    def _perform(self,account,identity,broker,call,quantity=0):
        if getattr(broker,'mode',None)!='offline-mock':raise ValueError('Live execution disabled.')
        try:
            broker_id=call()
            if not isinstance(broker_id,str) or not broker_id:raise ValueError('Missing acknowledgement.')
        except Exception:
            with self.engine.db() as db:
                db.execute("UPDATE control_actions SET state='UNKNOWN' WHERE id=? AND state='SUBMITTING'",(identity,))
                self.kill_in(db,account,'Protective action outcome unknown; reconcile without retry.')
            return dict(state='UNKNOWN',id=identity,executionAllowed=False)
        with self.engine.db() as db:
            current=db.execute('SELECT broker_id FROM control_actions WHERE id=?',(identity,)).fetchone()
            if current['broker_id'] and current['broker_id']!=broker_id:
                self.kill_in(db,account,'Conflicting late protective acknowledgement.')
            else:
                db.execute("UPDATE control_actions SET state=CASE WHEN state='SUBMITTING' THEN 'ACKNOWLEDGED' ELSE state END,broker_id=COALESCE(broker_id,?) WHERE id=?",(broker_id,identity))
            actual=db.execute('SELECT state FROM control_actions WHERE id=?',(identity,)).fetchone()[0]
        return dict(state=actual,id=identity,quantity=quantity,executionAllowed=False)

    def cancel_protection_mock(self,account,order_id,broker,*,as_of):
        observed=self.observe(account,broker,as_of=as_of)
        with self.engine.lock,self.engine.db() as db:
            db.execute('BEGIN IMMEDIATE')
            known=db.execute("SELECT * FROM control_actions WHERE account=? AND kind='STOP' AND broker_id=?",(account,order_id)).fetchone()
            if not known:raise ValueError('Cannot cancel an unowned protective order.')
            if db.execute("SELECT 1 FROM control_actions WHERE account=? AND kind='CANCEL' AND broker_id=? AND state IN ('SUBMITTING','UNKNOWN','ACKNOWLEDGED')",(account,order_id)).fetchone():
                raise ValueError('Uncertain cancellation cannot be repeated.')
            identity=hashlib.sha256((account+order_id+str(observed['revision'])+'cancel').encode()).hexdigest()
            db.execute('INSERT INTO control_actions VALUES(?,?,?,?,?,?,?,?)',
                (identity,account,known['instrument'],'CANCEL',known['quantity'],'SUBMITTING',order_id,json.dumps(dict(targetOrderId=order_id))))
        return self._perform(account,identity,broker,lambda:broker.cancel(order_id))

    def rearm_mock(self,account,broker,*,operator,as_of):
        if not isinstance(operator,str) or not re.fullmatch(r'(human|operator):[A-Za-z0-9_-]{1,64}',operator):
            raise ValueError('Explicit offline operator review identity required.')
        evidence=self.observe(account,broker,as_of=as_of)
        if any(evidence['positions'].values()) or any(row['state'] in WORKING for row in evidence['orders']):
            raise ValueError('Rearm requires confirmed flat positions and no working orders.')
        with self.engine.lock,self.engine.db() as db:
            db.execute('BEGIN IMMEDIATE')
            uncertain=db.execute("SELECT 1 FROM control_actions WHERE account=? AND kind IN ('STOP','CANCEL') AND state NOT IN ('COMPLETE','CANCELLED','REJECTED')",(account,)).fetchone()
            active=db.execute("""SELECT 1 FROM intents i JOIN funding_reservations r ON r.id=i.id WHERE r.account=?
                AND i.state IN ('PREPARED','SUBMITTING','UNKNOWN','OPEN','PARTIAL')""",(account,)).fetchone()
            if uncertain or active:raise ValueError('Outstanding outcomes require reconciliation before rearm.')
            db.execute('UPDATE emergency_controls SET active=0,reviewed_by=?,revision=revision+1,updated=? WHERE account=?',(operator,timestamp(as_of).isoformat(),account))
        self.engine.state='disabled';self.engine.reconciled=False
        return self.status()

    def configure_session(self,account,calendar,*,day,as_of,entry_cutoff,square_off,escalate):
        _account(account);session=session_for(calendar,date=day,as_of=as_of)
        if not session['open']:raise ValueError('Closed session; no intraday schedule.')
        def bound(value):
            clock=dt.time.fromisoformat(value)
            if clock.tzinfo is not None:raise ValueError('Use local IST clock times.')
            return dt.datetime.combine(dt.date.fromisoformat(day),clock,IST)
        cutoff,exit_at,escalation=map(bound,(entry_cutoff,square_off,escalate))
        if not timestamp(session['start'])<cutoff<exit_at<escalation<=timestamp(session['end']):
            raise ValueError('Operating times must fit the attributed calendar.')
        body=dict(account=account,day=day,entryCutoff=cutoff.isoformat(),squareOff=exit_at.isoformat(),
            escalate=escalation.isoformat(),calendarSource=session['source'],phase='OPEN',lastChecked=None)
        with self.engine.db() as db:db.execute('INSERT INTO control_sessions VALUES(?,?,?)',(account,day,json.dumps(body)))
        return body

    def clock_tick(self,account,*,as_of):
        at=timestamp(as_of)
        with self.engine.lock,self.engine.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT body FROM control_sessions WHERE account=? AND day=?',(account,at.date().isoformat())).fetchone()
            if not row:raise ValueError('Unknown exchange session; clock controller blocked.')
            body=json.loads(row[0])
            if body['lastChecked'] and at<timestamp(body['lastChecked']):raise ValueError('Clock regressed.')
            if at>=timestamp(body['entryCutoff']):body['phase']='ENTRY_BLOCKED'
            if at>=timestamp(body['squareOff']):
                body['phase']='EXIT_REQUIRED'
                identity=hashlib.sha256((account+body['day']+'squareoff').encode()).hexdigest()
                db.execute('INSERT OR IGNORE INTO control_actions VALUES(?,?,?,?,?,?,?,?)',
                    (identity,account,'*','SESSION_EXIT_REQUIRED',0,'NEEDS_EVIDENCE',None,
                     json.dumps(dict(reason='Clock cutoff; actual broker positions and permitted liquidation required.'))))
            if at>=timestamp(body['escalate']):
                body['phase']='ESCALATED'
                self.kill_in(db,account,'Clock square-off exposure is not confirmed closed.')
            body['lastChecked']=at.isoformat()
            db.execute('UPDATE control_sessions SET body=? WHERE account=? AND day=?',(json.dumps(body),account,body['day']))
        return body
