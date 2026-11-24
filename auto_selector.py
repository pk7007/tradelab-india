"""Authenticated, bounded whole-universe discovery and one funded paper account per session."""
import copy
import datetime as dt
import hashlib
import json
import math
import re
import logging
import threading
import time

import daily_pipeline
from intraday_contract import validate
import lineage_store
import supervision
import trading_calendar
from market_contract import session_for
from market_data import clean_candles
from paper_worker import PaperWorker
from research import IST, timestamp, validate_rows
from research_context import attach_announcements, evidence_references
from strategy_contract import target_long
from trader_suite import plan

LOG=logging.getLogger(__name__)


def rank_candidates(candles, config, calendar, cutoff):
    """Use the same completed-close SMA condition as Intraday v1."""
    now = timestamp(cutoff)
    session = session_for(calendar, date=now.date().isoformat(), as_of=cutoff)
    if not session['open']:
        return [], []
    opening, closing = timestamp(session['start']), timestamp(session['end'])
    candidates, excluded = [], []
    for symbol, raw in candles.items():
        try:
            rows = validate_rows(raw, now)
            rows = [r for r in rows if opening <= timestamp(r['date'])
                    and timestamp(r['date']) + dt.timedelta(minutes=5) <= min(now, closing)]
            if len(rows) < 20:
                raise ValueError('Twenty completed session candles required.')
            if timestamp(rows[0]['date']) != opening:
                raise ValueError('Session opening history missing.')
            stamps = [timestamp(r['date']) for r in rows]
            if any((b-a) != dt.timedelta(minutes=5) for a,b in zip(stamps,stamps[1:])):
                raise ValueError('Candle gap.')
            if now-(stamps[-1]+dt.timedelta(minutes=5)) > dt.timedelta(seconds=90):
                raise ValueError('Latest completed candle is stale.')
            if any(float(r['volume']) <= 0 for r in rows[-20:]):
                raise ValueError(daily_pipeline.REASON_LIQUIDITY)
            closes = [float(r['close']) for r in rows]
            if not target_long(closes):
                raise ValueError(daily_pipeline.REASON_SIGNAL)
            entry = closes[-1]
            stop = entry * (1-config['stopDistancePct']/100)
            sized = plan(dict(entry=entry, stop=stop, target=entry+(entry-stop)*config['targetMultiple'],
                              budget=min(config['capital'],config['maxExposure']), maxLoss=config['maxLoss'],
                              costBps=config['costBps'], slippageBps=config['slippageBps']))
            quantity = min(sized['quantity'], config['units'],
                           math.floor(float(rows[-1]['volume'])*config['participationPct']/100))
            if quantity < 1 or sized['netRewardRisk'] <= 0:
                raise ValueError(daily_pipeline.REASON_NO_SHARE)
            score = 100*(sum(closes[-5:])/5/(sum(closes[-20:])/20)-1)
            candidates.append(dict(symbol=symbol, score=score, bar=rows[-1]['date'],
                                   estimatedQuantity=quantity, plan=sized))
        except (ValueError,KeyError,TypeError,OverflowError) as exc:
            excluded.append(dict(symbol=symbol, reason=str(exc)))
    return sorted(candidates,key=lambda r:(-r['score'],r['symbol'])), excluded


class AutoSelector:
    """A fresh process starts disabled. Existing account exposure survives."""
    def __init__(self, engine, market, clock=lambda:dt.datetime.now(IST), announcements=None, alerts=None):
        self.engine, self.market, self.clock = engine, market, clock
        self.alerts=alerts
        self.announcements=announcements
        self.lock = threading.RLock()
        self.shutdown = threading.Event()
        self.thread = None
        self.session = None
        self.token = None
        self.profile = None
        self.enabled = False
        self.desired = 'stopped'
        self.worker = PaperWorker(engine, self.fetch, clock=clock, entry_authorized=self.check_login)
        self.detail = dict(state='disarmed', candidates=[], excluded=[], live=False)
        with engine.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS auto_selection (day TEXT PRIMARY KEY, account TEXT UNIQUE NOT NULL, body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS auto_scans (day TEXT PRIMARY KEY, body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS auto_sessions (day TEXT PRIMARY KEY, body TEXT NOT NULL)')
            lineage_store.ensure_schema(db)
            daily_pipeline.ensure_schema(db)

    def request(self, method, *args, **kwargs):
        if self.shutdown.is_set() or not self.enabled:
            raise ValueError('Selection stopped.')
        self.check_login()
        # Quote endpoints have a stricter budget than historical candles.
        with self.market.rate_lock:
            time.sleep(max(0,1.1-(time.monotonic()-self.market.last_request)))
            self.market.last_request=time.monotonic()
            result=getattr(self.market.client(self.token),method)(*args,**kwargs)
        self.check_login()
        return result

    def check_login(self):
        # The authorized paper worker owns a market-data grant for this session
        # date. Browser idle expiry only revokes the browser's credentials.
        if not self.token or not self.profile or self.clock().date() != self.grant_day:
            raise PermissionError('Reconnect Zerodha to resume automatic paper selection.')

    def fetch(self, instrument, start, end):
        resolved=self.market.resolve(self.token,instrument['symbol'])
        if resolved['instrument_token'] != instrument['token']:
            raise ValueError('Instrument mapping changed.')
        rows=[{k:r[k] for k in ('date','open','high','low','close','volume')}
                for r in clean_candles(self.request('historical_data',instrument['token'],start,end,
                                                   '5minute',continuous=False,oi=False))]
        self.record_news(instrument)
        return rows

    def record_news(self, instrument):
        """Attach bounded advisory metadata; optional context cannot block exits."""
        cutoff=self.clock().isoformat()
        context=dict(attached=0,stale=True,checkedAt=cutoff,status='disconnected',
                     executionAllowed=False,scope='Advisory context; no signal, risk or order authority.')
        try:
            if self.announcements is not None:
                feed=self.announcements.status(getattr(self.market,'master',[]))
                values,summary=attach_announcements(dict(asOf=cutoff),feed)
                matching=[r for r in values['records'] if instrument['symbol'] in r['symbols']]
                context.update(summary,attached=len(matching), evidence=evidence_references(matching, instrument['symbol']),
                               status='matched' if matching else 'unavailable' if summary['stale'] else 'no-eligible-match')
            self.detail['newsContext']=context
            if self.worker.account and self.detail.get('symbol')==instrument['symbol']:
                with self.engine.db() as db:
                    self.worker._assert(db)
                    state=self.engine.load(db,self.worker.account)
                    self.engine.save(db,state,dict(type='worker-news-context',detail=context))
                self.worker._record(newsContext=context)
        except Exception:
            self.detail['newsContext']=dict(context,status='unavailable',stale=True)

    def start(self, session, config, calendar):
        with self.lock:
            if self.enabled:
                if (session.get('access_token') != self.token or
                        (session.get('profile') or {}).get('user_id') != self.profile):
                    raise PermissionError('A different broker session owns this paper run.')
                return self.status()
            if self.thread and self.thread.is_alive():
                raise ValueError('Previous selection cycle is stopping; wait before restarting.')
            validate(config)
            now=self.clock()
            # A stale or malformed calendar must not arm anything (CalendarError is a ValueError).
            trading_calendar.validate(calendar,now.isoformat(),strict_sessions=False)
            with self.engine.db() as db:
                saved=db.execute('SELECT day,account,body FROM auto_selection WHERE day=?',(now.date().isoformat(),)).fetchone()
                if not saved:
                    previous=db.execute('SELECT day,account,body FROM auto_selection WHERE day<? ORDER BY day DESC LIMIT 1',
                                        (now.date().isoformat(),)).fetchone()
                    if previous:
                        prior=self.engine.load(db,previous['account'])
                        if prior['quantity'] or prior['pending']:
                            saved=previous
                account=self.engine.load(db,saved['account']) if saved and db.execute(
                    'SELECT 1 FROM accounts WHERE id=?',(saved['account'],)).fetchone() else None
                previous_session=bool(saved and saved['day']!=now.date().isoformat())
                allocation=json.loads(saved['body']) if saved else None
                if previous_session:
                    if allocation.get('profile') != (session.get('profile') or {}).get('user_id'):
                        raise ValueError('Broker identity differs from the funded paper experiment.')
                    original=config==allocation['config']
                    managed=config==account['config']
                    if not original and not managed:
                        raise ValueError('Saved recovery assumptions changed.')
                    # Accept only an explicitly supplied calendar covering old
                    # and current dates. The worker checks every missing day.
                    prior_date=account['lastBar'][:10] if account['lastBar'] else saved['day']
                    prior_session=session_for(calendar,date=prior_date,as_of=now.isoformat())
                    if not prior_session['open']:
                        raise ValueError('Recovery calendar must confirm the prior open session.')
                    config=copy.deepcopy(allocation['config'])
                if account and config == account['config']:
                    if (allocation.get('profile') != (session.get('profile') or {}).get('user_id')
                            or (not previous_session and allocation['calendar'] != calendar)
                            or any(account['config'].get(key) != value for key,value in
                                   allocation['accountConfig'].items() if key!='permitted')):
                        raise ValueError('Saved selection assumptions changed.')
                    # The UI selects the current managed account after refresh.
                    # Its chosen symbol and carried capital differ legitimately
                    # from the original scanner template, which remains frozen.
                    config=copy.deepcopy(allocation['config'])
                recovering=bool(account and (account['quantity'] or account['pending']))
                recovery_identity=saved['account'] if saved else None
                if account and not self.engine.reconcile_in(db,account)['matches']:
                    raise ValueError('Paper ledger mismatch; investigate before resuming selection.')
            day=session_for(calendar,date=now.date().isoformat(),as_of=now.isoformat())
            if calendar.get('symbol'):
                raise ValueError('Automatic selection requires a market-wide calendar window, not a single-stock calendar.')
            if not day['open'] or now < timestamp(day['start']) or (now >= timestamp(day['end']) and not recovering):
                raise ValueError('Start during a confirmed continuous session.')
            if now.strftime('%H:%M') >= config['entryEnd'] and not recovering:
                raise ValueError('Entry cutoff passed.')
            if timestamp(day['end']).date()!=now.date() or (timestamp(day['end']).replace(
                    hour=int(config['squareOff'][:2]),minute=int(config['squareOff'][3:]))+
                    dt.timedelta(minutes=5)) >= timestamp(day['end']):
                raise ValueError('Square-off must be observable before the configured window ends.')
            with self.engine.db() as db:
                if db.execute('SELECT 1 FROM paper_workers WHERE enabled=1 AND expires>?',(now.timestamp(),)).fetchone():
                    raise ValueError('Stop the other paper worker before enabling automatic selection.')
                states=[json.loads(r[0]) for r in db.execute('SELECT body FROM accounts')]
                if any((a['quantity'] or a['pending']) and a['id']!=recovery_identity for a in states):
                    raise ValueError('Reconcile existing exposure and intent before selection.')
            self.session=session
            self.token=session.get('access_token')
            self.profile=(session.get('profile') or {}).get('user_id')
            self.grant_day=now.date()
            self.check_login()
            self.config=copy.deepcopy(config)
            self.calendar=copy.deepcopy(calendar)
            paused_before_selection = self.start_unfunded_session(now) if not saved else False
            self.recovery_only=recovering and (previous_session or now.strftime('%H:%M')>=config['entryEnd'])
            self.recovery_allocation=(recovery_identity,allocation) if saved else None
            self.worker=PaperWorker(self.engine,self.fetch,clock=self.clock,entry_authorized=self.check_login)
            self.enabled=True
            self.shutdown.clear()
            self.desired='paused' if paused_before_selection else 'running'
            self.detail=dict(state='waiting-for-scan',candidates=[],excluded=[],live=False)
            if self.recovery_allocation:
                identity,allocation=self.recovery_allocation
                try:
                    self.engine.create(allocation['accountConfig'],identity=identity)
                    self.detail.update(allocation.get('selectionTrace',{}))
                    self.attach(identity,allocation['instrument'])
                    self.recovery_allocation=None
                except Exception:
                    self.enabled=False
                    self.shutdown.set()
                    self.worker.stop()
                    self.detail.update(state='blocked',reason='Existing exposure recovery could not arm. Review saved account and calendar.')
                    raise
            if self.enabled and (not self.thread or not self.thread.is_alive()):
                self.thread=threading.Thread(target=self.loop,name='automatic-paper-selection',daemon=True)
                self.thread.start()
            self._resolve_login_alert()
            return self.status()

    def start_unfunded_session(self, now):
        """Keep no-trade sessions auditable without creating a funded account."""
        day=now.date().isoformat()
        with self.engine.db() as db:
            existing=db.execute('SELECT body FROM auto_sessions WHERE day=?',(day,)).fetchone()
            if existing:
                recorded=json.loads(existing['body'])
                if recorded['profile']!=self.profile or recorded['config']!=self.config:
                    raise ValueError('Saved session profile or assumptions changed.')
                if recorded['final']:
                    raise ValueError('This paper session already ended. Its closing report is preserved.')
                return bool(recorded.get('entriesPaused'))
            opening_cash=self.config['capital']
            previous=db.execute('SELECT account,body FROM auto_selection WHERE day<? ORDER BY day DESC LIMIT 1',(day,)).fetchone()
            if previous:
                allocation=json.loads(previous['body'])
                account=self.engine.load(db,previous['account'])
                if allocation.get('profile')!=self.profile or not self.engine.reconcile_in(db,account)['matches']:
                    raise ValueError('Prior paper funding identity or reconciliation failed.')
                if account['quantity'] or account['pending']:
                    raise ValueError('Prior exposure must recover before an unfunded session starts.')
                opening_cash=min(opening_cash,account['cash'])
            report=dict(day=day,profile=self.profile,config=copy.deepcopy(self.config),
                        startedAt=now.isoformat(),endedAt=None,final=False,accountId=None,
                        symbol=None,openingCash=opening_cash,closingCash=opening_cash,
                        fees=0,realized=0,netResult=0,fills=0,quantity=0,pending=None,
                        reconciled=True,noTrade=True,mode='paper',reason='Waiting for a qualifying stock.')
            db.execute('INSERT INTO auto_sessions VALUES(?,?)',(day,json.dumps(report,allow_nan=False)))

    def end_unfunded_session(self, reason):
        with self.engine.db() as db:
            day=self.clock().date().isoformat()
            row=db.execute('SELECT body FROM auto_sessions WHERE day=?',(day,)).fetchone()
            if row:
                report=json.loads(row['body'])
                report.update(final=True,endedAt=self.clock().isoformat(),reason=reason)
                db.execute('UPDATE auto_sessions SET body=? WHERE day=?',(json.dumps(report,allow_nan=False),day))

    def stop(self):
        with self.lock:
            self.enabled=False
            self.shutdown.set()
            self.token=None
            self.session=None
            self.worker.stop()
            self.detail['state']='stopped'
            self._supervise(False)   # an open position must leave an incident when selection stops
            return self.status()

    def revoke(self):
        """Remove the market-data grant and cancel unfilled entries on explicit logout."""
        with self.lock:
            self.token=None
            if self.enabled:
                try:
                    self.control('pause_entries')
                finally:
                    self.stop()
                    self._supervise(True)

    def control(self, action):
        """Session controls never abandon an active exit to pause new entries."""
        if action not in ('pause_entries', 'resume_entries', 'end_session'):
            raise ValueError('Unknown automatic session control.')
        with self.lock:
            identity=self.worker.account
            if not identity:
                if not self.enabled:
                    raise ValueError('Start an automatic paper session before controlling it.')
                if action == 'end_session':
                    self.desired='ending'
                    self.end_unfunded_session('Session ended before a qualifying stock was funded.')
                    self.stop()
                    self.detail.update(state='reconciled-flat',reason='Session ended before a stock was selected.')
                else:
                    self.desired='paused' if action=='pause_entries' else 'running'
                    day=self.clock().date().isoformat()
                    with self.engine.db() as db:
                        row=db.execute('SELECT body FROM auto_sessions WHERE day=?',(day,)).fetchone()
                        if row:
                            recorded=json.loads(row[0])
                            recorded['entriesPaused']=self.desired=='paused'
                            db.execute('UPDATE auto_sessions SET body=? WHERE day=?',(json.dumps(recorded),day))
                    self.detail['state']='entries-paused' if action=='pause_entries' else 'waiting-for-scan'
                return self.status()
            state=self.engine.control(identity,action,requested_at=self.clock().isoformat())
            self.desired='ending' if state.get('endRequested') else 'paused' if state.get('entriesPaused') else 'running'
            if action == 'end_session':
                self.finish_if_flat()
            return self.status()

    def finish_if_flat(self):
        if not self.worker.account:
            return False
        with self.engine.db() as db:
            state=self.engine.load(db,self.worker.account)
            reconciliation=self.engine.reconcile_in(db,state)
        if not state.get('endRequested'):
            return False
        if reconciliation['matches'] and not state['quantity'] and not state['pending']:
            self.stop()
            self.detail.update(state='reconciled-flat',reason='All paper exposure closed and ledger reconciled.')
            return True
        self.detail.update(state='unresolved-exposure',reason='Session ending; protective processing retained until exits reconcile.')
        return False

    def loop(self):
        while not self.shutdown.is_set():
            if not self.step():
                return
            self.shutdown.wait(30)

    def step(self):
        """One supervised tick. False means the loop must stop (disabled or failed)."""
        try:
            if not self.enabled:
                return False
            self.tick()
            return True
        except Exception as exc:
            self._fail(exc)
            return False

    def _fail(self, exc):
        with self.lock:
            if self.shutdown.is_set():
                return
            self.enabled=False
            self.token=None
            self.session=None
            self.detail.update(state='blocked',reason='BROKER_LOGIN_REQUIRED' if isinstance(exc,PermissionError)
                               else 'Selection or data validation failed. Review before resuming.')
            try:
                if self.worker.account:
                    self.engine.control(self.worker.account,'pause_entries')
            finally:
                self.worker.stop()
            # Open exposure cannot close without accepted candles: keep it visible and tell the owner.
            self._supervise(isinstance(exc,PermissionError))

    def _supervise(self, login_lost):
        """Best effort: an incident-inbox failure must never disturb failure handling or exits."""
        try:
            report=supervision.exposure_report(self.engine)
            self.detail['exposure']=dict(status='EXPOSED' if report else 'FLAT',positions=report)
            if self.alerts is None:
                return
            now=self.clock()
            supervision.observe_exposure(self.alerts,self.engine,now=now)
            if login_lost:
                self.alerts.observe(supervision.LOGIN_KEY,'Broker login lost. New entries are blocked; reconnect Zerodha and '
                                    're-arm recovery.'+(' Open paper exposure remains.' if report else ''),True,
                                    severity='critical' if report else 'warning',now=now)
        except Exception as error:
            LOG.warning('Supervision alert unavailable (%s).',type(error).__name__)

    def _resolve_login_alert(self):
        try:
            if self.alerts is not None:
                self.alerts.observe(supervision.LOGIN_KEY,'Broker login restored.',False,now=self.clock())
                supervision.observe_exposure(self.alerts,self.engine,now=self.clock())
        except Exception as error:
            LOG.warning('Supervision alert unavailable (%s).',type(error).__name__)

    def tick(self):
        if not self.enabled or self.shutdown.is_set():
            return self.status()
        self.check_login()
        now=self.clock()
        session=session_for(self.calendar,date=now.date().isoformat(),as_of=now.isoformat())
        if not session['open']:
            self.detail.update(state='waiting-closed-session')
            return
        if self.worker.account:
            self.worker.tick()
            self.detail.update(state='paper-processing',worker=self.worker.status())
            accepted=self.detail['worker'].get('lastAcceptedBar')
            if accepted and timestamp(accepted).astimezone(IST).date()==now.date() and timestamp(accepted).astimezone(IST).strftime('%H:%M')>=self.config['squareOff'] and self.desired!='ending':
                self.control('end_session')
            if self.finish_if_flat():
                return
            if now >= timestamp(session['end']):
                self.stop()
            return
        if self.recovery_allocation:
            identity,allocation=self.recovery_allocation
            self.detail.update(allocation.get('selectionTrace',{}))
            self.attach(identity,allocation['instrument'])
            self.recovery_allocation=None
            return
        if self.desired == 'paused':
            self.detail.update(state='entries-paused',reason='Selection paused. No funded stock has been selected.')
            return
        with self.engine.db() as db:
            saved=db.execute('SELECT account,body FROM auto_selection WHERE day=?',(now.date().isoformat(),)).fetchone()
        if saved:
            allocation=json.loads(saved['body'])
            if (allocation['config'] != self.config or allocation['calendar'] != self.calendar
                    or allocation.get('profile') != self.profile):
                raise ValueError('Saved selection assumptions changed.')
            self.engine.create(allocation['accountConfig'],identity=saved['account'])
            self.detail.update(allocation.get('selectionTrace',{}))
            self.attach(saved['account'],allocation['instrument'])
            return
        if now < timestamp(session['start'])+dt.timedelta(minutes=100):
            self.detail.update(state='waiting-for-twenty-completed-candles')
            return
        if now.strftime('%H:%M')>=self.config['entryEnd']:
            self.end_unfunded_session('Entry cutoff passed with no qualifying stock selected.')
            self.stop()
            self.detail.update(state='reconciled-flat',reason='No trade. Entry cutoff passed and no account was funded.')
            return
        if self.detail.get('nextScanAt') and now < timestamp(self.detail['nextScanAt']):
            return
        # instruments() refreshes the full broker master once daily.
        self.market.instruments(self.token,'')
        universe={r['tradingsymbol']:r for r in self.market.master if r.get('exchange')=='NSE'
                  and r.get('instrument_type')=='EQ' and r.get('segment')=='NSE'
                  and re.fullmatch(r'[A-Z0-9&-]{1,30}',r['tradingsymbol'])}
        quotes={}
        symbols=sorted(universe)
        for offset in range(0,len(symbols),500):
            quotes.update(self.request('quote',['NSE:'+s for s in symbols[offset:offset+500]]))
        shortlist=[]
        quote_excluded=[]
        observed_times=[]
        for symbol in symbols:
            quote=quotes.get('NSE:'+symbol,{})
            try:
                price=float(quote['last_price']);volume=float(quote['volume'])
                observed=quote['timestamp']
                observed=observed.replace(tzinfo=IST) if observed.tzinfo is None else observed
                if not 0<= (self.clock()-observed).total_seconds() <=90:
                    quote_excluded.append(dict(symbol=symbol,reason='Quote timestamp is stale or future.'))
                    continue
                observed_times.append(observed)
                if not math.isfinite(price*volume) or not 0<price<=self.config['capital'] or volume<=0:
                    quote_excluded.append(dict(symbol=symbol,reason='Quote price, capital or volume excludes this stock.'))
                    continue
                shortlist.append((price*volume,symbol))
            except (KeyError,ValueError,TypeError,AttributeError):
                quote_excluded.append(dict(symbol=symbol,reason='Quote missing or malformed.'))
                continue
        selected=sorted(shortlist,key=lambda x:(-x[0],x[1]))[:20]
        candles={}
        for _,symbol in selected:
            instrument=dict(exchange='NSE',symbol=symbol,token=int(universe[symbol]['instrument_token']))
            candles[symbol]=self.fetch(instrument,timestamp(session['start']),min(self.clock(),timestamp(session['end']))-dt.timedelta(seconds=1))
        at=self.clock()
        ranked,excluded=rank_candidates(candles,self.config,self.calendar,at.isoformat())
        scan=daily_pipeline.assess_scan(day=at.date().isoformat(),now=at.isoformat(),symbols=symbols,
            quote_excluded=quote_excluded,quote_observed_at=max(observed_times).isoformat() if observed_times else None,
            candles=candles,ranked=ranked,excluded=excluded,
            candle_observed_at=(timestamp(max(r['bar'] for r in ranked))+dt.timedelta(minutes=5)).isoformat() if ranked else None,
            optional_events=self.detail.get('newsContext'))
        try:
            with self.engine.db() as db:
                daily_pipeline.record_scan(db,scan)
        except Exception as error:
            # Fail closed: an unrecorded selection cannot be traced, so it is not allowed to fund an account.
            LOG.warning('Daily selection log unavailable (%s); selection blocked for this scan.',type(error).__name__)
            scan.update(decision='blocked',selected=None,reasons=scan['reasons']+['Selection log unavailable (%s).'%type(error).__name__])
        self.detail.update(state='no-qualifying-candidate',universeCount=len(symbols),quoteCount=len(quotes),
                           candleChecks=len(candles),candidates=ranked,excluded=excluded,
                           checkedAt=at.isoformat(),nextScanAt=(at+dt.timedelta(minutes=5)).isoformat(),
                           strategyVersion=self.config['strategy'],
                           examinedSymbols=symbols,quoteExcluded=quote_excluded,
                           ranking='Top 20 affordable turnover-proxy names, then shared SMA spread.',
                           decision=scan['decision'],decisionReasons=scan['reasons'],selectionLineage=scan['finalTaskId'])
        if scan['decision']=='blocked':
            self.detail.update(state='selection-blocked',reason='; '.join(scan['reasons']))
        with self.engine.db() as db:
            db.execute('INSERT OR REPLACE INTO auto_scans VALUES(?,?)',
                       (at.date().isoformat(),json.dumps(self.detail,allow_nan=False)))
        if scan['decision']=='selected' and at.strftime('%H:%M')<self.config['entryEnd']:
            symbol=scan['selected']
            instrument=dict(exchange='NSE',symbol=symbol,token=int(universe[symbol]['instrument_token']))
            self.allocate(at.date().isoformat(),instrument)

    def allocate(self, day, instrument):
        with self.lock:
            return self._allocate(day,instrument)

    def _allocate(self, day, instrument):
        if self.desired=='paused':
            return
        if not self.enabled or self.shutdown.is_set():
            raise ValueError('Selection stopped before allocation.')
        if self.desired != 'running':
            return
        # A deterministic account ID makes crash recovery between reservation and creation idempotent.
        identity=hashlib.sha256(('auto-selection-v1|'+day).encode()).hexdigest()[:32]
        with self.engine.db() as db:
            saved=db.execute('SELECT account,body FROM auto_selection WHERE day=?',(day,)).fetchone()
            if saved:
                allocation=json.loads(saved['body'])
                identity=saved['account']
                instrument=allocation['instrument']
            else:
                previous=db.execute('SELECT account FROM auto_selection ORDER BY day DESC LIMIT 1').fetchone()
                config=dict(self.config,symbol=instrument['symbol'],permitted=True)
                if previous:
                    previous_body=json.loads(db.execute('SELECT body FROM auto_selection WHERE account=?',(previous['account'],)).fetchone()[0])
                    if previous_body.get('profile') != self.profile:
                        raise ValueError('Broker identity differs from the funded paper experiment.')
                    account=self.engine.load(db,previous['account'])
                    if account['quantity'] or account['pending'] or account['status']=='running':
                        raise ValueError('Prior allocation has unresolved exposure or processing.')
                    if not self.engine.reconcile_in(db,account)['matches']:
                        raise ValueError('Prior allocation ledger mismatch.')
                    if account['cash'] <= 0:
                        raise ValueError('No available paper capital remains; a new allocation cannot be funded.')
                    # Carry realized equity forward. This is sequential funding, not a fresh daily balance.
                    config.update(capital=min(account['cash'],self.config['capital']),
                                  maxExposure=min(account['cash'],self.config['maxExposure']))
                    config['dailyLossLimit']=min(config['dailyLossLimit'],config['capital'])
                    config['maxLoss']=min(config['maxLoss'],config['dailyLossLimit'])
                allocation=dict(config=self.config,accountConfig=config,instrument=instrument,
                                calendar=self.calendar,profile=self.profile,
                                selectionTrace={key:copy.deepcopy(self.detail[key]) for key in
                                    ('universeCount','quoteCount','candleChecks','candidates','excluded',
                                     'checkedAt','ranking','strategyVersion','decision','decisionReasons',
                                     'selectionLineage') if key in self.detail})
                allocation['selectionTrace'].update(
                    examinedSymbols=copy.deepcopy(self.detail.get('examinedSymbols',[])),
                    quoteExcluded=copy.deepcopy(self.detail.get('quoteExcluded',[])),
                    selectedSymbol=instrument['symbol'],selectedAt=self.clock().isoformat())
                db.execute('INSERT INTO auto_selection VALUES(?,?,?)',(day,identity,json.dumps(allocation)))
        self.engine.create(allocation['accountConfig'],identity=identity)
        self.attach(identity,instrument)

    def attach(self, identity, instrument):
        if not self.enabled or self.shutdown.is_set():
            raise ValueError('Selection stopped before worker attachment.')
        self.worker.start(identity,instrument,self.calendar,True,True)
        if getattr(self,'recovery_only',False):
            self.engine.control(identity,'end_session',requested_at=self.clock().isoformat())
        with self.engine.db() as db:
            state=self.engine.load(db,identity)
        self.desired='ending' if state.get('endRequested') else 'paused' if state.get('entriesPaused') else 'running'
        self.detail.update(state='selected',accountId=identity,symbol=instrument['symbol'])
        self.finish_if_flat()

    def status(self):
        with self.lock:
            result=copy.deepcopy(self.detail)
            try:
                report=supervision.exposure_report(self.engine)
                result['exposure']=dict(status='EXPOSED' if report else 'FLAT',positions=report)
            except Exception:
                result['exposure']=dict(status='UNKNOWN',positions=[])
            result.update(enabled=self.enabled,live=False,mode='automatic-candle-paper',
                          desiredState=self.desired,threadAlive=bool(self.thread and self.thread.is_alive()))
            with self.engine.db() as db:
                saved=db.execute('SELECT account,body FROM auto_selection ORDER BY day DESC LIMIT 1').fetchone()
                day=self.clock().date().isoformat()
                session=db.execute('SELECT body FROM auto_sessions WHERE day=?',(day,)).fetchone()
                today=db.execute('SELECT 1 FROM auto_selection WHERE day=?',(day,)).fetchone()
                scan=db.execute('SELECT body FROM auto_scans ORDER BY day DESC LIMIT 1').fetchone()
                identity=self.worker.account or (saved['account'] if saved else None)
                existing=db.execute('SELECT body FROM accounts WHERE id=?',(identity,)).fetchone() if identity else None
                account=json.loads(existing['body']) if existing else None
                reconciliation=self.engine.reconcile_in(db,account) if account else None
            if session and not today and not self.worker.account and not (account and (account['quantity'] or account['pending'])):
                if account:
                    result['previousAccountId']=account['id']
                account=None
                result['noTradeReport']=json.loads(session['body'])
                result['closureState']='reconciled-flat' if result['noTradeReport']['final'] else 'unfunded-session'
            if scan:
                result['lastScan']=json.loads(scan['body'])
            if account:
                if self.worker.account:
                    result['worker']=self.worker.status()
                allocation=json.loads(saved['body']) if saved else {}
                result.setdefault('selectionTrace',allocation.get('selectionTrace',{}))
                result.update(accountId=account['id'],symbol=account['config']['symbol'],
                              entriesPaused=bool(account.get('entriesPaused')),
                              endRequested=bool(account.get('endRequested')),
                              reconciliation=reconciliation)
                result['balance']=dict(cash=account['cash'],equity=account['equity'],quantity=account['quantity'],
                                       fees=account['fees'],realized=account['realized'],pending=account['pending'])
                result['closureState']=('unresolved-exposure' if account['quantity'] or account['pending']
                                        else 'reconciled-flat' if reconciliation['matches'] else 'ledger-mismatch')
                if not self.enabled and (account['quantity'] or account['pending']):
                    result['reason']='Exposure or pending intent remains. Processing is stopped; reconnect and resume protective handling.'
            return result
