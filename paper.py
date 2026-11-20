"""Single-symbol, persistent paper execution. No broker or network dependencies."""
from contextlib import contextmanager
import datetime as dt
import json
import math
from pathlib import Path
import sqlite3
import uuid
from research import timestamp, IST, validate_rows
from strategy_contract import target_long, assumed_fill
from market_contract import session_for
import intraday_contract


class PaperEngine:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, account TEXT NOT NULL, at TEXT NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS bars(account TEXT NOT NULL, stamp TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(account,stamp));
            CREATE TABLE IF NOT EXISTS receipts(account TEXT NOT NULL, stamp TEXT NOT NULL, received TEXT NOT NULL, source TEXT NOT NULL, instrument TEXT NOT NULL, PRIMARY KEY(account,stamp));''')
            for row in db.execute('SELECT id,body FROM accounts').fetchall():
                state = json.loads(row['body'])
                if state['status'] == 'running' or state.get('feed',{}).get('status')=='connected (fixture)':
                    if state['status']=='running': state['status'] = 'paused'
                    if 'feed' in state: state['feed']['status']='disconnected'
                    self.save(db, state, {'type': 'restart', 'detail': 'Paused; position and pending intent preserved. Review before resuming.'})

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

    def save(self, db, state, event):
        db.execute('INSERT OR REPLACE INTO accounts VALUES(?,?)', (state['id'], json.dumps(state, allow_nan=False)))
        db.execute('INSERT INTO events(account,at,body) VALUES(?,?,?)', (state['id'], dt.datetime.now(dt.timezone.utc).isoformat(), json.dumps(event, allow_nan=False)))

    def load(self, db, identity):
        row = db.execute('SELECT body FROM accounts WHERE id=?', (identity,)).fetchone()
        if not row:
            raise ValueError('Unknown paper account.')
        return json.loads(row['body'])

    def create(self, data, *, identity=None):
        if data.get('permitted') is not True:
            raise ValueError('Confirm permission to retain these candles for local paper research.')
        config = {}
        for key in ('capital', 'units', 'maxExposure', 'dailyLossLimit', 'costBps', 'slippageBps'):
            raw = data.get(key)
            if isinstance(raw, bool): raise ValueError('Invalid '+key)
            try: value = float(raw)
            except (ValueError, TypeError): raise ValueError('Specify '+key) from None
            if not math.isfinite(value) or value < 0 or value > 1e12: raise ValueError('Invalid '+key)
            config[key] = value
        if not 0 < config['maxExposure'] <= config['capital'] or not 0 < config['dailyLossLimit'] <= config['capital']:
            raise ValueError('Exposure and daily loss limits must be positive and no greater than capital.')
        if not 1 <= config['units'] <= 1000000 or config['units'] != int(config['units']): raise ValueError('Units must be whole shares, 1–1,000,000.')
        if max(config['costBps'], config['slippageBps']) > 500: raise ValueError('Costs and slippage cannot exceed 500 basis points per side.')
        config['units'] = int(config['units'])
        for key in ('symbol', 'provider', 'adjustment'):
            value = data.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > 160: raise ValueError('Specify '+key)
            config[key] = value.strip()
        if data.get('source') not in ('synthetic', 'imported'): raise ValueError('Choose synthetic or imported data.')
        config.update(source=data['source'], strategy='sma5-20-next-open-paper-v1', interval='5minute', overnight=True)
        if data.get('strategy') == intraday_contract.VERSION:
            config.update(intraday_contract.validate(data), strategy=intraday_contract.VERSION, overnight=False)
        elif data.get('strategy') not in (None, 'sma5-20-next-open-paper-v1'):
            raise ValueError('Unknown paper strategy version.')
        state = dict(id=identity or uuid.uuid4().hex, config=config, status='paused', cash=config['capital'], quantity=0, basis=0,
                     fees=0, realized=0, equity=config['capital'], pending=None, lastBar=None, closes=[],
                     day=None, dayStartEquity=config['capital'], dayLoss=0, riskHalted=False, completedTrades=0)
        with self.db() as db:
            existing = db.execute('SELECT body FROM accounts WHERE id=?', (state['id'],)).fetchone()
            if existing:
                saved = json.loads(existing[0])
                if saved['config'] != config:
                    raise ValueError('Account identity already has different assumptions.')
                return saved
            if db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0] >= 100: raise ValueError('Local account limit reached (100).')
            self.save(db, state, {'type': 'created', 'config': config})
        return state

    def status(self):
        with self.db() as db:
            accounts = [json.loads(row[0]) for row in db.execute('SELECT body FROM accounts ORDER BY rowid DESC')]
            events = [dict(seq=r['seq'], account=r['account'], at=r['at'], **json.loads(r['body'])) for r in db.execute('SELECT * FROM events ORDER BY seq DESC LIMIT 100')]
        return dict(accounts=accounts, events=events, live=False, feed='Manual completed-candle ingestion; continuous provider feed disconnected',
                    assumptions='Inspect the selected account strategy. Legacy accounts use fixed units/full next-open fills and permit overnight holding. Opt-in intraday-v1 uses supplied stop/target, cost-aware size, volume participation and observed-open square-off; failed exits retain exposure. Both are imported OHLC models without a verified exchange calendar or continuous feed; losses may exceed thresholds.')

    def control(self, identity, action, *, requested_at=None):
        if action not in ('start', 'pause', 'stop', 'pause_entries', 'resume_entries', 'cancel_entries', 'close_position', 'end_session'):
            raise ValueError('Unknown control.')
        request_stamp=timestamp(requested_at or dt.datetime.now(IST).isoformat()).isoformat() if action=='end_session' else None
        with self.db() as db:
            s = self.load(db, identity)
            detail = 'Positions unchanged. Stop cancels the local unfilled intent; pause preserves it. No broker action.'
            if action in ('start', 'resume_entries', 'close_position', 'end_session') and not self.reconcile_in(db, s)['matches']:
                raise ValueError('Paper ledger mismatch; investigate before resuming or requesting an exit.')
            if action == 'resume_entries' and s.get('endRequested'):
                raise ValueError('This session is ending; new entries cannot resume.')
            if action == 'end_session':
                if s.get('endRequested'):
                    return s
                s['endRequested'] = True
                s['entriesPaused'] = True
                if s['quantity']:
                    if not s.get('pending') or s['pending']['side'] != 'SELL':
                        s['pending'] = dict(side='SELL', signalAt=s['lastBar'], requestedAt=request_stamp,
                                            reason='User ended paper session')
                else:
                    s['pending'] = None
                detail = 'Session ending. New entries blocked; exposure remains until accepted candles confirm all exits.'
            elif action in ('start', 'pause', 'stop'):
                s['status'] = 'running' if action == 'start' else 'paused' if action == 'pause' else 'stopped'
                if action == 'stop': s['pending'] = None
            elif action == 'close_position':
                if s['status'] != 'running' or not s['quantity']:
                    raise ValueError('A running account with open shares is required. Resume ingestion before requesting closure.')
                s['entriesPaused'] = True
                s['pending'] = dict(side='SELL', signalAt=s['lastBar'], reason='User requested paper closure')
                detail = 'Exit requested, not filled. Shares remain exposed until the next accepted candle open. New entries paused.'
            else:
                if action != 'cancel_entries': s['entriesPaused'] = action == 'pause_entries'
                if action != 'resume_entries' and s.get('pending') and s['pending']['side'] == 'BUY':
                    s['pending'] = None
                detail = 'Entry control updated. Existing shares and pending exits preserved; running ingestion continues.'
            event={'type': action, 'detail': detail}
            if request_stamp:
                event['requestedAt']=request_stamp
            self.save(db, s, event)
        return s

    def fixture_link(self, identity, connected):
        with self.db() as db:
            s=self.load(db,identity)
            if s['config']['source']!='synthetic': raise ValueError('Fixture replay requires a synthetic account.')
            if 'feed' not in s and s['lastBar']: raise ValueError('Start a new account for a fixture feed.')
            feed=s.setdefault('feed',dict(mode='fixture replay',source='generated-fixture-v1',instrument='FIXTURE:'+s['config']['symbol'],received=None))
            feed['status']='connected (fixture)' if connected else 'disconnected'
            self.save(db,s,dict(type='feed',detail=feed['status']))
            return feed

    def reconcile(self, identity):
        with self.db() as db:
            return self.reconcile_in(db,self.load(db,identity))

    def fixture_batch(self, identity, instrument, bars, permitted):
        if not isinstance(instrument,str) or not instrument: raise ValueError('Specify the fixture instrument.')
        try:
            return self.ingest(identity,bars,permitted,fixture_instrument=instrument)
        except ValueError as exc:
            with self.db() as db:
                s=self.load(db,identity)
                if s.get('feed',{}).get('instrument')==instrument:
                    s['feed']['lastError']=str(exc)
                    self.save(db,s,dict(type='feed-rejected',detail=str(exc)))
            raise

    def reconcile_in(self, db, s):
        cash = basis = realized = fees = 0.0
        quantity = fills = 0
        last_buy_price = None
        initialized = False
        valid = True
        reconstructed_config = None
        for row in db.execute('SELECT body FROM events WHERE account=? ORDER BY seq', (s['id'],)):
            event = json.loads(row[0])
            if event['type'] == 'created':
                valid = valid and not initialized
                initialized = True
                cash = event['config']['capital']
                reconstructed_config = event['config']
            if event['type'] in ('strategy-promoted', 'strategy-rollback'):
                next_config = event.get('config')
                previous_config = event.get('previousConfig')
                if (not initialized or quantity or previous_config != reconstructed_config
                        or not isinstance(next_config, dict)):
                    valid = False
                    break
                mutable = {'stopDistancePct', 'targetMultiple', 'entryEnd', 'squareOff', 'strategyRevision'}
                previous_fixed = {key: value for key, value in previous_config.items() if key not in mutable}
                next_fixed = {key: value for key, value in next_config.items() if key not in mutable}
                try:
                    intraday_contract.validate(next_config)
                except (ValueError, TypeError, KeyError):
                    valid = False
                    break
                if previous_fixed != next_fixed or next_config.get('strategy') != intraday_contract.VERSION:
                    valid = False
                    break
                reconstructed_config = next_config
            if event['type'] != 'fill':
                continue
            units, fee = event['quantity'], event['fee']
            value = units * event['price']
            if not initialized or units <= 0 or fee < 0 or event['price'] <= 0:
                valid = False
                break
            if event['side'] == 'BUY':
                last_buy_price = event['price']
                basis += value + fee
                cash -= value + fee
                quantity += units
            elif event['side'] == 'SELL' and units <= quantity:
                released = basis * units / quantity
                basis -= released
                realized += value - fee - released
                cash += value - fee
                quantity -= units
            else:
                valid = False
                break
            fills += 1
            fees += fee
        last = db.execute('SELECT stamp,body FROM bars WHERE account=? ORDER BY stamp DESC LIMIT 1', (s['id'],)).fetchone()
        market_value = quantity * json.loads(last['body'])['close'] if last else 0
        rebuilt = dict(cash=cash, basis=basis, realized=realized, fees=fees, equity=cash + market_value)
        mismatches = [key for key,value in rebuilt.items() if not math.isclose(value,s[key],rel_tol=0,abs_tol=.0001)]
        if quantity != s['quantity']: mismatches.append('quantity')
        if s['lastBar'] != (last['stamp'] if last else None): mismatches.append('lastBar')
        if not valid or not initialized or reconstructed_config != s['config']: mismatches.append('ledger')
        if s['config']['strategy'] == intraday_contract.VERSION and quantity:
            c=s['config'];raw=last_buy_price/(1+c['slippageBps']/10000) if last_buy_price else None
            expected=dict(stop=raw*(1-c['stopDistancePct']/100),target=raw+raw*c['stopDistancePct']/100*c['targetMultiple']) if raw else {}
            if any(not isinstance(s.get('protection',{}).get(key),(int,float)) or not math.isclose(value,s['protection'][key],rel_tol=0,abs_tol=.0001) for key,value in expected.items()) or not expected:
                mismatches.append('protection')
        return dict(matches=not mismatches, mismatches=mismatches, quantity=quantity, fills=fills,
                    unrealized=market_value-basis, **rebuilt)

    def ingest(self, identity, rows, permitted, *, fixture_instrument=None, transaction_guard=None, session_calendar=None):
        if permitted is not True: raise ValueError('Confirm permission for local candle retention.')
        if not isinstance(rows, list) or not 1 <= len(rows) <= 1000: raise ValueError('Supply 1–1,000 completed five-minute bars.')
        cutoff = dt.datetime.now(IST)
        sessions = {}
        def bounds(date):
            if date not in sessions:
                session = session_for(session_calendar, date=date, as_of=cutoff.isoformat())
                if not session['open']:
                    raise ValueError('Candle conflicts with closed session calendar date.')
                sessions[date] = (timestamp(session['start']), timestamp(session['end']))
            return sessions[date]
        normalized = []
        for row in rows:
            if not isinstance(row, dict): raise ValueError('Each candle must be an object.')
            try:
                stamp = timestamp(row['date'])
                if any(isinstance(row[k], bool) for k in ('open','high','low','close','volume')): raise ValueError('Boolean candle value.')
                validate_rows([row], cutoff)
                if stamp + dt.timedelta(minutes=5) > cutoff: raise ValueError('Incomplete or future candle.')
                if stamp.second or stamp.microsecond or stamp.minute % 5:
                    raise ValueError('Candle starts must align to five minutes.')
                if session_calendar is not None:
                    start, end = bounds(stamp.date().isoformat())
                    if not start <= stamp or stamp + dt.timedelta(minutes=5) > end:
                        raise ValueError('Candle conflicts with supplied session calendar bounds.')
                elif stamp.weekday() >= 5 or not dt.time(9,15) <= stamp.time() <= dt.time(15,25):
                    raise ValueError('Use weekday NSE session starts, 09:15–15:25 IST, aligned to five minutes.')
                clean = dict(date=stamp.isoformat(), **{k:float(row[k]) for k in ('open','high','low','close','volume')})
                if clean['volume'] < 0 or clean['high'] > 1e9: raise ValueError('Nonnegative volume and prices below 1e9 required.')
                normalized.append(clean)
            except (TypeError, KeyError, OverflowError) as exc: raise ValueError('Malformed candle.') from exc
        processed = duplicates = 0
        with self.db() as db:
            if transaction_guard is None and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_workers'").fetchone() and db.execute('SELECT 1 FROM paper_workers WHERE account=?',(identity,)).fetchone():
                raise ValueError('Worker-bound accounts accept only fenced worker observations.')
            if transaction_guard is not None: transaction_guard(db)
            s = self.load(db, identity)
            if s['status'] != 'running': raise ValueError('Start this paper account before ingesting candles.')
            if s['config']['strategy'] != intraday_contract.VERSION and any(bar['volume'] <= 0 for bar in normalized):
                raise ValueError('Positive volume required for the legacy paper workflow.')
            for row in rows:
                if 'symbol' in row and row['symbol'] != s['config']['symbol']:
                    raise ValueError('Candle symbol differs from the account symbol.')
                if 'exchange' in row and row['exchange'] != 'NSE':
                    raise ValueError('Unsupported candle exchange for the NSE paper workflow.')
                if 'instrument_token' in row or 'isin' in row:
                    raise ValueError('Provider instrument mapping must be verified before importing tagged records.')
            feed=s.get('feed')
            if feed or fixture_instrument is not None:
                if not feed or feed['instrument']!=fixture_instrument or feed['status']!='connected (fixture)':
                    raise ValueError('Fixture instrument or connection mismatch.')
            if not self.reconcile_in(db,s)['matches']:
                raise ValueError('Paper ledger mismatch; processing blocked.')
            for index, bar in enumerate(normalized):
                if s['config']['strategy'] == intraday_contract.VERSION:
                    for flag in ('halted','reject'):
                        value=rows[index].get(flag,False)
                        if type(value) is not bool: raise ValueError('Intraday halt/rejection flags must be Boolean.')
                        bar[flag]=value
                encoded = json.dumps(bar, sort_keys=True)
                old = db.execute('SELECT body FROM bars WHERE account=? AND stamp=?', (identity,bar['date'])).fetchone()
                if old:
                    if old[0] != encoded: raise ValueError('A processed candle changed. Create a separate account for revised history.')
                    duplicates += 1
                    continue
                stamp = timestamp(bar['date'])
                if s['lastBar']:
                    previous = timestamp(s['lastBar'])
                    if stamp <= previous: raise ValueError('Out-of-order candle.')
                    if stamp.date() == previous.date() and stamp-previous != dt.timedelta(minutes=5): raise ValueError('Missing five-minute candle; import the missing interval first.')
                    if stamp.date() != previous.date():
                        if session_calendar is None:
                            complete = previous.time() == dt.time(15,25) and stamp.time() == dt.time(9,15)
                        else:
                            _, previous_end = bounds(previous.date().isoformat())
                            current_start, _ = bounds(stamp.date().isoformat())
                            complete = previous + dt.timedelta(minutes=5) == previous_end and stamp == current_start
                            missing_date = previous.date() + dt.timedelta(days=1)
                            while missing_date < stamp.date():
                                skipped = session_for(session_calendar, date=missing_date.isoformat(), as_of=cutoff.isoformat())
                                if skipped['open']:
                                    raise ValueError('Missing open session; import its completed candles first.')
                                missing_date += dt.timedelta(days=1)
                        if not complete:
                            raise ValueError('Incomplete session boundary; import the remaining candles first.')
                day = stamp.date().isoformat()
                if s['config']['strategy'] == intraday_contract.VERSION:
                    # A manual request made now cannot fill at an earlier
                    # missed candle open during historical recovery. Existing
                    # protective levels can still act on the recovered bar.
                    deferred=s.get('pending')
                    if deferred and deferred.get('requestedAt') and stamp < timestamp(deferred['requestedAt']):
                        s['pending']=None
                    else:
                        deferred=None
                    events=intraday_contract.advance(s,bar)
                    if deferred and s['quantity'] and not s.get('pending'):
                        s['pending']=deferred
                    db.execute('INSERT INTO bars VALUES(?,?,?)',(identity,bar['date'],encoded))
                    if feed:
                        received=dt.datetime.now(IST)
                        feed.pop('lastError',None)
                        db.execute('INSERT INTO receipts VALUES(?,?,?,?,?)',(identity,bar['date'],received.isoformat(),feed['source'],fixture_instrument))
                        feed.update(received=received.isoformat(),exchangeStart=bar['date'],ageAtReceiptSeconds=(received-stamp-dt.timedelta(minutes=5)).total_seconds())
                    for event in events: self.save(db,s,event)
                    self.save(db,s,dict(type='bar',bar=bar['date'],equity=s['equity'],pending=s['pending'],riskHalted=s['riskHalted']))
                    processed += 1
                    continue
                if day != s['day']:
                    s.update(day=day, dayStartEquity=s['equity'], dayLoss=0, riskHalted=False)
                c = s['config']; fee = c['costBps']/10000; slip = c['slippageBps']/10000
                opening_equity = s['cash']+s['quantity']*bar['open']
                if s['dayStartEquity']-opening_equity >= c['dailyLossLimit']: s['riskHalted'] = True
                intent = s['pending']; s['pending'] = None
                if intent:
                    side = intent['side']; units = c['units'] if side == 'BUY' else s['quantity']
                    price, commission = assumed_fill(bar['open'], units, side, c['costBps'], c['slippageBps'])
                    cost = units*price+commission
                    reason = None
                    if side == 'BUY':
                        if s.get('entriesPaused'): reason = 'New entries paused'
                        elif s['riskHalted']: reason = 'Daily loss threshold reached'
                        elif cost > s['cash'] or cost > c['maxExposure']: reason = 'Cash or exposure limit at next open'
                    if reason:
                        self.save(db,s,dict(type='rejected',bar=bar['date'],side=side,reason=reason,signalAt=intent['signalAt']))
                    elif units:
                        if side == 'BUY': s.update(cash=s['cash']-cost,quantity=units,basis=cost)
                        else:
                            proceeds=units*price-commission
                            s.update(cash=s['cash']+proceeds,quantity=0,realized=s['realized']+proceeds-s['basis'],basis=0,completedTrades=s['completedTrades']+1)
                        s['fees'] += commission
                        self.save(db,s,dict(type='fill',bar=bar['date'],side=side,quantity=units,price=price,fee=commission,signalAt=intent['signalAt']))
                s['equity'] = s['cash']+s['quantity']*bar['close']
                s['dayLoss'] = max(0,s['dayStartEquity']-s['equity'])
                s['riskHalted'] = s['riskHalted'] or s['dayLoss'] >= c['dailyLossLimit']
                s['closes'] = (s['closes']+[bar['close']])[-20:]
                s['lastBar'] = bar['date']
                if len(s['closes']) == 20:
                    long = target_long(s['closes'])
                    if long and not s['quantity'] and s['riskHalted']:
                        self.save(db,s,dict(type='skipped',side='BUY',quantity=c['units'],signalAt=bar['date'],
                                            reason='Daily loss threshold reached'))
                    side = 'BUY' if long and not s['quantity'] and not s['riskHalted'] and not s.get('entriesPaused') else 'SELL' if not long and s['quantity'] else None
                    if side: s['pending'] = dict(side=side,signalAt=bar['date'])
                db.execute('INSERT INTO bars VALUES(?,?,?)',(identity,bar['date'],encoded))
                if feed:
                    received=dt.datetime.now(IST)
                    feed.pop('lastError',None)
                    db.execute('INSERT INTO receipts VALUES(?,?,?,?,?)',(identity,bar['date'],received.isoformat(),feed['source'],fixture_instrument))
                    feed.update(received=received.isoformat(),exchangeStart=bar['date'],ageAtReceiptSeconds=(received-stamp-dt.timedelta(minutes=5)).total_seconds())
                self.save(db,s,dict(type='bar',bar=bar['date'],equity=s['equity'],pending=s['pending'],riskHalted=s['riskHalted']))
                processed += 1
            if transaction_guard is not None: transaction_guard(db)
        return dict(account=s,processed=processed,duplicates=duplicates)
