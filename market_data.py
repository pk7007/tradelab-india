"""Private Kite data viewing, bounded downloads, and broker WebSocket transport."""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math
import os
from pathlib import Path
import secrets
import threading
import time

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
INTERVALS = {'minute', '3minute', '5minute', '10minute', '15minute', '30minute', '60minute', 'day'}
STARTER = ['RELIANCE', 'INFY', 'TCS', 'HDFCBANK', 'ICICIBANK']


def date_range(start, end):
    start, end = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if start > end or end > dt.datetime.now(IST).date():
        raise ValueError('Choose an ordered date range ending no later than today in India.')
    if (end-start).days > 20*366:
        raise ValueError('Limit a research request to 20 years.')
    return start, end


def chunks(start, end):
    """Conservative 30-calendar-day windows; inclusive dates never overlap."""
    while start <= end:
        stop = min(end, start+dt.timedelta(days=29))
        yield start, stop
        start = stop+dt.timedelta(days=1)


def clean_candles(rows):
    candles = {}
    for row in rows:
        stamp = row['date']
        if stamp.tzinfo is None:
            raise ValueError('Broker candle timestamp has no timezone.')
        vals = [float(row[k]) for k in ('open', 'high', 'low', 'close', 'volume')]
        if not all(math.isfinite(x) for x in vals) or min(vals[:4])<=0 or vals[2] > min(vals[0], vals[3]) or vals[1] < max(vals[0], vals[3]) or vals[4] < 0:
            raise ValueError('Invalid OHLCV data returned; job stopped without fabricating values.')
        oi=row.get('oi')
        if oi is not None and (not math.isfinite(float(oi)) or float(oi)<0):
            raise ValueError('Invalid open interest returned.')
        key = stamp.astimezone(IST).isoformat()
        candles[key] = {'date': key, **dict(zip(('open','high','low','close','volume'), vals)), 'oi': row.get('oi')}
    return sorted(candles.values(), key=lambda x:x['date'])


class MarketData:
    def __init__(self, api_key, root):
        self.api_key = api_key
        self.root = Path(root)
        self.lock = threading.RLock()
        self.rate_lock = threading.Lock()
        self.last_request = 0.0
        self.master = []
        self.master_day = None
        self.master_lock = threading.Lock()
        self.jobs = {}
        self.stream = None
        self.stream_owner = None
        self.stream_generation = None
        self.stream_state = {'state':'stopped','points':[], 'lastTick':None}
        self.stream_activity = 0.0
        threading.Thread(target=self._reaper, daemon=True).start()

    def client(self, token):
        from kiteconnect import KiteConnect
        return KiteConnect(api_key=self.api_key, access_token=token, timeout=20)

    def instruments(self, token, query=''):
        today = dt.datetime.now(IST).date()
        with self.master_lock:
            if self.master_day != today:
                self.master = self.client(token).instruments('NSE')
                self.master_day = today
            matches = [dict(instrument_token=int(x['instrument_token']), tradingsymbol=x['tradingsymbol'], name=x['name'], exchange=x['exchange'])
                       for x in self.master if x['instrument_type']=='EQ' and (query.upper() in x['tradingsymbol'].upper() or query.upper() in x['name'].upper())]
        return matches[:100]

    def resolve(self, token, symbol):
        matches = self.instruments(token, symbol)
        for item in matches:
            if item['tradingsymbol'] == symbol:
                return item
        raise ValueError('Choose an exact NSE equity symbol from instrument search.')

    def start_history(self, owner, token, values):
        interval = values.get('interval','day')
        if interval not in INTERVALS:
            raise ValueError('Unsupported candle interval.')
        start, end = date_range(values.get('from',''), values.get('to',''))
        symbols = list(dict.fromkeys(str(values.get('symbols','')).upper().replace(' ','').split(',')))
        if not 1 <= len(symbols) <= 25 or any(not s or len(s)>40 for s in symbols):
            raise ValueError('Choose 1–25 NSE equity symbols per request.')
        save = values.get('save') is True
        if save and os.environ.get('KITE_DATA_STORAGE_APPROVED','false').lower() != 'true':
            raise ValueError('Permanent storage is locked pending confirmation of your data-storage rights. You can view history in memory.')
        with self.lock:
            if any(j['owner']==owner and j['state'] in {'queued','running'} for j in self.jobs.values()):
                raise ValueError('Wait for or cancel the current historical request.')
            old = [k for k,j in self.jobs.items() if j['owner']==owner]
            for k in old:
                del self.jobs[k]
            job_id = secrets.token_hex(12)
            job = {'id':job_id,'owner':owner,'state':'queued','completed':0,'total':len(list(chunks(start,end)))*len(symbols),
                   'symbols':symbols,'interval':interval,'from':str(start),'to':str(end),'save':save,'rows':{},'error':None,'cancel':False,
                   'source':'Kite Connect historical API','timezone':'Asia/Kolkata','fetchedAt':None,'emptyWindows':0}
            self.jobs[job_id] = job
        threading.Thread(target=self._history_worker,args=(job,token,start,end),daemon=True).start()
        return self.job(owner,job_id)

    def _history_worker(self, job, token, start, end):
        try:
            client = self.client(token)
            job['state']='running'
            for symbol in job['symbols']:
                instrument = self.resolve(token,symbol)
                rows=[]
                for first,last in chunks(start,end):
                    if job['cancel']:
                        job['state']='cancelled'; return
                    with self.rate_lock:
                        time.sleep(max(0, 0.4-(time.monotonic()-self.last_request)))
                        self.last_request=time.monotonic()
                        batch=client.historical_data(instrument['instrument_token'], str(first)+' 00:00:00', str(last)+' 23:59:59', job['interval'], continuous=False, oi=True)
                    batch=clean_candles(batch)
                    if job['cancel']:
                        job['state']='cancelled'; return
                    rows.extend(batch)
                    if len(rows)>200_000:
                        raise ValueError('200,000-candle viewing limit reached; narrow the dates or use a larger interval.')
                    if len(rows)+sum(len(r) for r in job['rows'].values())>400_000:
                        raise ValueError('400,000-candle request limit reached; narrow the request.')
                    with self.lock:
                        job['completed']+=1
                        job['emptyWindows']+=int(not batch)
                with self.lock:
                    job['rows'][symbol]=rows
                if job['save']:
                    self._save(job, symbol, instrument, rows)
            job['fetchedAt']=dt.datetime.now(dt.timezone.utc).isoformat()
            job['state']='complete'
        except Exception as exc:
            job['state']='failed'
            job['error']='Request failed ('+type(exc).__name__+'). Check login, subscription, instrument, and dates. Completed symbols remain visible.'

    def _save(self,job,symbol,instrument,rows):
        # No user-controlled path components: each job has a generated identifier.
        folder=self.root / job['id']
        folder.mkdir(parents=True,exist_ok=True)
        stem=str(instrument['instrument_token'])
        target=folder/(stem+'.csv')
        buffer=io.StringIO()
        writer=csv.DictWriter(buffer,fieldnames=['date','open','high','low','close','volume','oi'])
        writer.writeheader(); writer.writerows(rows)
        target.write_text(buffer.getvalue(),encoding='utf-8')
        metadata={k:job[k] for k in ('source','timezone','interval','from','to')}
        metadata.update(instrument=instrument,symbol=symbol,rows=len(rows),downloadedAt=dt.datetime.now(dt.timezone.utc).isoformat(),adjustments='As returned by provider; corporate-action handling not independently verified',complete=True)
        (folder/(stem+'.json')).write_text(json.dumps(metadata,indent=2),encoding='utf-8')

    def job(self,owner,job_id,symbol=None):
        with self.lock:
            job=self.jobs.get(job_id)
            if not job or job['owner']!=owner:
                raise ValueError('Historical request not found in this session.')
            result={k:v for k,v in job.items() if k not in {'owner','rows','cancel'}}
            result['counts']={s:len(rows) for s,rows in job['rows'].items()}
            if symbol:
                result['candles']=job['rows'].get(symbol,[])[-500:]
            return result

    def cancel(self,owner,job_id):
        self.job(owner,job_id)
        with self.lock:
            self.jobs[job_id]['cancel']=True

    def rank(self, owner, job_id, horizon, as_of):
        from research import rank_universe, experiment_record
        with self.lock:
            self.job(owner,job_id)
            job=self.jobs[job_id]
            if job['state']!='complete':
                raise ValueError('Finish the historical request before ranking its universe.')
            rows={symbol:list(candles) for symbol,candles in job['rows'].items()}
            interval=job['interval']
        report=rank_universe(rows,horizon,interval,as_of)
        report['source']='Kite historical candles; user-selected current NSE equity universe'
        report['retrievedAt']=job.get('fetchedAt')
        report['experiment']=experiment_record({'horizon':horizon,'asOf':as_of,'interval':interval},rows,report)
        return report

    def cancel_owner(self,owner):
        with self.lock:
            for job in self.jobs.values():
                if job['owner']==owner:
                    job['cancel']=True

    def start_stream(self,owner,token,symbol):
        from kiteconnect import KiteTicker
        instrument=self.resolve(token,symbol)
        with self.lock:
            if self.stream_owner and self.stream_owner != owner:
                raise ValueError('Another local session owns the live stream. Stop that stream or wait for its idle timeout.')
            self.stop_stream(owner)
            generation=secrets.token_hex(8)
            self.stream_generation=generation
            self.stream_owner=owner
            self.stream_activity=time.monotonic()
            self.stream_state={'state':'connecting','symbol':symbol,'points':[],'lastTick':None,'error':None}
            ticker=KiteTicker(self.api_key,token,reconnect=True,reconnect_max_tries=5)
            self.stream=ticker
        def state(value):
            with self.lock:
                if self.stream_generation==generation:
                    self.stream_state['state']=value
        def on_connect(ws,response):
            ws.subscribe([instrument['instrument_token']]); ws.set_mode(ws.MODE_FULL,[instrument['instrument_token']]); state('connected')
        def on_ticks(ws,ticks):
            with self.lock:
                if self.stream_generation!=generation: return
                for tick in ticks:
                    if tick['instrument_token']!=instrument['instrument_token']: continue
                    received=dt.datetime.now(dt.timezone.utc).isoformat()
                    stamp=tick.get('exchange_timestamp')
                    # Kite SDK returns exchange timestamps as naive local datetimes on some versions.
                    self.stream_state['points'].append({'date':received,'close':tick['last_price']})
                    self.stream_state['points']=self.stream_state['points'][-1000:]
                    self.stream_state.update(lastTick=received,exchangeTimestamp=stamp.isoformat() if stamp else None,state='connected')
        ticker.on_connect=on_connect
        ticker.on_ticks=on_ticks
        ticker.on_close=lambda ws,code,reason:state('disconnected')
        ticker.on_error=lambda ws,code,reason:state('connection error')
        ticker.on_reconnect=lambda ws,attempts:state('reconnecting')
        ticker.on_noreconnect=lambda ws:state('disconnected')
        ticker.connect(threaded=True)
        return self.stream_status(owner)

    def stream_status(self,owner):
        with self.lock:
            if self.stream_owner != owner:
                return {'state':'stopped','points':[],'lastTick':None}
            self.stream_activity=time.monotonic()
            return {**self.stream_state,'points':list(self.stream_state['points'])}

    def stop_stream(self,owner):
        with self.lock:
            if self.stream_owner != owner: return
            ticker=self.stream
            self.stream_generation=None
            self.stream_owner=None
            self.stream=None
            if ticker:
                ticker.close()

    def _reaper(self):
        while True:
            time.sleep(15)
            with self.lock:
                owner=self.stream_owner
                if owner and time.monotonic()-self.stream_activity>90:
                    self.stop_stream(owner)


def synthetic_research(values):
    """Illustrative long-only SMA rule, synthetic prices only, next-bar fills."""
    import random
    fast=int(values.get('fast',10)); slow=int(values.get('slow',30))
    cost=float(values.get('costBps',10)); slip=float(values.get('slippageBps',5))
    if not (2<=fast<slow<=100) or not (0<=cost<=100 and 0<=slip<=100):
        raise ValueError('Use 2 <= fast < slow <= 100; costs and slippage must be 0–100 bps.')
    rng=random.Random(42); candles=[]; price=100.0
    for index in range(400):
        opening=price*(1+rng.gauss(0,.003)); price=opening*(1+rng.gauss(.0002,.012))
        candles.append({'date':str(dt.date(2024,1,1)+dt.timedelta(days=index)), 'open':opening,'close':price})
    return simulate_rule(candles,fast,slow,cost,slip)


def simulate_rule(candles,fast,slow,cost,slip):
    cash=100000.0; qty=0; trades=0; fees=0.0; equity=[]; pending=None; peak=cash; drawdown=0.0
    for i,bar in enumerate(candles):
        if pending=='buy' and not qty:
            fill=bar['open']*(1+slip/10000)
            qty=int(cash/(fill*(1+cost/10000)))
            fee=qty*fill*cost/10000; cash-=qty*fill+fee; fees+=fee; trades+=int(qty>0)
        elif pending=='sell' and qty:
            fill=bar['open']*(1-slip/10000); fee=qty*fill*cost/10000
            cash+=qty*fill-fee; fees+=fee; qty=0; trades+=1
        pending=None
        value=cash+qty*bar['close']; peak=max(peak,value); drawdown=max(drawdown,1-value/peak)
        equity.append({'date':bar['date'],'close':value})
        if i>=slow-1:
            recent=[x['close'] for x in candles[i-slow+1:i+1]]
            short=sum(recent[-fast:])/fast; long=sum(recent)/slow
            if short>long and qty==0: pending='buy'
            elif short<=long and qty>0: pending='sell'
    return {'label':'SYNTHETIC EDUCATIONAL DEMO — not market evidence', 'equity':equity,'initialCapital':100000,'finalEquity':equity[-1]['close'],
            'returnPct':(equity[-1]['close']/100000-1)*100,'maxDrawdownPct':drawdown*100,'fills':trades,'modeledFees':fees,
            'openQuantity':qty,'assumptions':'Whole units; long only; signals at close, fills at next open; terminal holdings marked to last close; no tax, liquidity, or corporate-action model. Synthetic seed 42. No live order connection.'}
