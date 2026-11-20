"""In-memory authenticated transport for the durable PAPER worker; no order methods."""
import datetime as dt
import threading
import time
from market_data import clean_candles
from paper_worker import PaperWorker
from research_context import attach_announcements


class WorkerRuntime:
    def __init__(self,engine,market,announcements=None):
        self.engine=engine;self.market=market;self.announcements=announcements;self.lock=threading.RLock()
        self.session=None;self.session_id=None;self.token=None;self.profile_id=None
        self.worker=PaperWorker(engine,self.fetch)
        self.thread=None;self.wake=threading.Event()
        self.runtime_fault=None

    def valid_session(self):
        s=self.session
        if not s or s.get('access_token')!=self.token or (s.get('profile') or {}).get('user_id')!=self.profile_id:
            raise PermissionError('Broker login changed; worker must be re-armed.')
        if time.monotonic()-s.get('last_seen',0)>1800:
            raise PermissionError('Local broker session idle; reconnect or refresh before re-arming.')

    def fetch(self,instrument,start,end):
        self.valid_session()
        token=self.token
        actual=self.market.resolve(token,instrument['symbol'])
        if actual['exchange']!='NSE' or actual['instrument_token']!=instrument['token']:
            raise ValueError('Provider instrument mapping changed; re-arm after verification.')
        with self.market.rate_lock:
            time.sleep(max(0,0.4-(time.monotonic()-self.market.last_request)))
            self.market.last_request=time.monotonic()
            rows=self.market.client(token).historical_data(instrument['token'],start,end,'5minute',continuous=False,oi=False)
        self.valid_session()
        self.record_news(instrument)
        return [{k:row[k] for k in ('date','open','high','low','close','volume')} for row in clean_candles(rows)]

    def record_news(self,instrument):
        """Record context at receipt; never change signals, exits or risk limits."""
        cutoff=dt.datetime.now(dt.timezone.utc).isoformat()
        context=dict(source='NSE RSS',attached=0,stale=True,checkedAt=cutoff,
                     executionAllowed=False,scope='Context only; no trade authority.')
        try:
            if self.announcements is not None:
                feed=self.announcements.status(getattr(self.market,'master',[]))
                cutoff=dt.datetime.now(dt.timezone.utc).isoformat()
                context['checkedAt']=cutoff
                values,summary=attach_announcements(dict(asOf=cutoff),feed)
                matching=[r for r in values['records'] if instrument['symbol'] in r['symbols']]
                context.update(summary,attached=len(matching),status='matched' if matching else ('unavailable' if summary['stale'] else 'no-eligible-match'))
        except Exception:
            context['status']='unavailable'
        with self.engine.db() as db:
            row=self.worker._assert(db)
            state=self.engine.load(db,self.worker.account)
            self.engine.save(db,state,dict(type='worker-news-context',detail=context))
        self.worker._record(newsContext=context)

    def start(self,session_id,session,values):
        with self.lock:
            if self.worker.status().get('enabled'):
                raise ValueError('Stop the active paper worker before reconfiguration.')
            token=session.get('access_token');profile=(session.get('profile') or {}).get('user_id')
            if not token or not profile: raise PermissionError('Connect the broker first.')
            instrument=values.get('instrument')
            if not isinstance(instrument,dict): raise ValueError('Mapped instrument required.')
            resolved=self.market.resolve(token,instrument.get('symbol',''))
            if resolved['exchange']!='NSE' or resolved['instrument_token']!=instrument.get('token'):
                raise ValueError('Choose the exact NSE equity mapping from broker search.')
            self.session_id=session_id;self.session=session;self.token=token;self.profile_id=profile
            result=self.worker.start(values.get('id'),instrument,values.get('calendar'),retention_approved=values.get('retentionApproved'),calendar_confirmed=values.get('calendarConfirmed'))
            self.runtime_fault=None
            if self.thread is None or not self.thread.is_alive():
                self.thread=threading.Thread(target=self.loop,daemon=True,name='paper-candle-worker');self.thread.start()
            self.wake.set()
            return result

    def loop(self):
        while True:
            self.wake.wait(30);self.wake.clear()
            self.tick_once()

    def tick_once(self):
        # An inactive worker must not create repeated stop events or fetch data.
        try:
            if getattr(self, 'runtime_fault', None):
                return
            if not self.worker.status().get('enabled'):
                return
            self.worker.tick()
        except Exception as exc:
            self.runtime_fault = dict(state="blocked", errorType=type(exc).__name__, detail="Worker fault requires explicit review and re-arming.")
            # Core retains redacted fault details; stop once, preserving exposure.
            try:self.worker.stop()
            except Exception:pass

    def stop(self):
        with self.lock:
            result=self.worker.stop()
            self.token=None;self.session=None;self.profile_id=None;self.session_id=None
            return result

    def stop_owner(self,session_id):
        if self.session_id==session_id:return self.stop()

    def status(self):
        try:
            result=self.worker.status()
        except Exception as exc:
            result=dict(state='unavailable',enabled=False,live=False,errorType=type(exc).__name__,exposureStatus='unverified')
        result['threadAlive']=bool(self.thread and self.thread.is_alive())
        result['runtimeFault']=self.runtime_fault
        if self.worker.account:
            try:
                with self.engine.db() as db:
                    account = self.engine.load(db, self.worker.account)
                result['exposure'] = dict(quantity=account['quantity'], pending=account['pending'],
                                          equity=account['equity'], cash=account['cash'],
                                          strategy=account['config']['strategy'])
            except Exception:
                result['exposureStatus'] = 'unverified'
        return result
