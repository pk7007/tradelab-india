"""Forward PAPER decisions use completed bars and subsequent fresh bid/ask quotes.

These pure state transitions have no broker or database authority. The caller
must persist state, quotes and returned events in one fenced transaction.
"""
import datetime as dt
import math

from market_contract import session_for, validate_quote
from research import timestamp, validate_rows
from strategy_contract import assumed_fill, target_long


def _intraday(state):
    if state['config']['strategy'] != 'intraday-v1':
        raise ValueError('Forward observations require Intraday v1')


def _pending(side, bar, decision, reason):
    return dict(side=side, signalAt=bar, decisionAt=decision, eligibleAfter=decision, reason=reason)


def record_signal(state, bar, received_at, decision_at, warmup=False):
    """Observe a completed bar, update the SMA, and create an eligible intent."""
    _intraday(state)
    if type(warmup) is not bool:
        raise ValueError('Explicit warmup flag required')
    if not isinstance(bar, dict):
        raise ValueError('Candle object required')
    received, decision, at = timestamp(received_at), timestamp(decision_at), timestamp(bar['date'])
    if decision < received or at + dt.timedelta(minutes=5) > received:
        raise ValueError('Signal must follow candle completion and receipt')
    if any(isinstance(bar.get(key), bool) for key in ('open', 'high', 'low', 'close', 'volume')):
        raise ValueError('Boolean OHLCV is invalid')
    validate_rows([bar], decision)
    if at.second or at.microsecond or at.minute % 5 or not dt.time(9,15) <= at.time() <= dt.time(15,25):
        raise ValueError('Completed five-minute regular-session bar required')
    previous = timestamp(state['lastBar']) if state['lastBar'] else None
    if previous and at <= previous:
        raise ValueError('Signal observation duplicated or out of order')
    if previous and previous.date() == at.date() and at - previous != dt.timedelta(minutes=5):
        raise ValueError('Missing completed signal candle')
    events = []
    if state['day'] != at.date().isoformat():
        state.update(day=at.date().isoformat(), dayStartEquity=state['equity'], dayLoss=0,
                     riskHalted=False, closes=[])
        if state['quantity']:
            state['entriesPaused'] = True
            state['recoveryRequired'] = True
            state['pending'] = _pending('SELL', state['lastBar'], decision.isoformat(), 'Prior-session exposure recovery')
    state['closes'] = (state['closes'] + [float(bar['close'])])[-20:]
    state['lastBar'] = at.isoformat()
    state['lastSignalReceivedAt'] = received.isoformat()
    state['lastDecisionAt'] = decision.isoformat()
    events.append(dict(type='forward-signal-observation', bar=at.isoformat(), receivedAt=received.isoformat(),
                       decisionAt=decision.isoformat(), warmup=warmup, close=float(bar['close']),
                       mode='forward-quote-paper'))
    if warmup:
        if state.get('pending') and state['pending']['side'] == 'BUY':
            state['pending'] = None
        return events
    if len(state['closes']) < 20:
        events.append(dict(type='skipped', bar=at.isoformat(), reason='SMA warmup requires 20 completed closes'))
        return events
    long = target_long(state['closes'])
    side = None
    if not long and state['quantity']:
        side = 'SELL'
    elif long and not state['quantity'] and not state.get('entriesPaused') and not state['riskHalted']:
        if decision.time() < dt.time.fromisoformat(state['config']['entryEnd']):
            side = 'BUY'
    if side and not state.get('pending'):
        state['pending'] = _pending(side, at.isoformat(), decision.isoformat(), 'Completed-close SMA condition')
        events.append(dict(type='forward-intent', **state['pending']))
    else:
        events.append(dict(type='skipped', bar=at.isoformat(), reason='No eligible change in position'))
    return events


def observe(state, quote, as_of, calendar, max_age_seconds=15, max_spread_bps=50):
    """Fill eligible paper intents against newly received executable-side quotes."""
    _intraday(state)
    config = state['config']
    now = timestamp(as_of)
    clean = validate_quote(quote, instrument='NSE:' + config['symbol'], as_of=as_of,
                           max_age_seconds=max_age_seconds)
    if isinstance(max_spread_bps, bool) or not isinstance(max_spread_bps, (int,float)) or not math.isfinite(max_spread_bps) or not 0 < max_spread_bps <= 500:
        raise ValueError('Spread cap must be positive and at most 500 bps')
    at, received = timestamp(clean['exchangeAt']), timestamp(clean['receivedAt'])
    for field in ('bidQuantity', 'askQuantity'):
        value = clean.get(field)
        if type(value) is not int or not 0 <= value <= 1000000000:
            raise ValueError('Explicit nonnegative quoted ' + field + ' required')
    session = session_for(calendar, date=now.date().isoformat(), as_of=as_of)
    if not session['open'] or not timestamp(session['start']) <= at <= now < timestamp(session['end']):
        raise ValueError('Quote is outside the attributed trading session')
    previous = state.get('lastQuote')
    if previous and at <= timestamp(previous['exchangeAt']):
        return [dict(type='forward-quote-skipped', reason='Duplicate or older exchange observation')]
    bid, ask = clean['bid'], clean['ask']
    spread = 10000 * (ask-bid) / bid
    events = []
    quote_metadata = dict(exchangeAt=at.isoformat(), receivedAt=received.isoformat(),
                          decisionAt=now.isoformat(), bid=bid, ask=ask,
                          provider=clean['provider'], instrument=clean['instrument'])
    state['lastQuote'] = quote_metadata
    state['equity'] = state['cash'] + state['quantity'] * bid
    if state['day'] != now.date().isoformat():
        state.update(day=now.date().isoformat(), dayStartEquity=state['equity'], dayLoss=0, riskHalted=False, closes=[])
        if state['quantity']:
            state['entriesPaused'] = True
            state['recoveryRequired'] = True
    state['dayLoss'] = max(0, state['dayStartEquity'] - state['equity'])
    state['riskHalted'] = state['riskHalted'] or state['dayLoss'] >= config['dailyLossLimit']
    pending = state.get('pending')
    protection = state.get('protection')
    exit_reason = None
    if state['quantity']:
        if now.time() >= dt.time.fromisoformat(config['squareOff']) or state.get('recoveryRequired'):
            exit_reason = 'Session square-off or recovery at fresh bid'
        elif protection and bid <= protection['stop']:
            exit_reason = 'Protective stop crossed at fresh bid'
        elif protection and bid >= protection['target']:
            exit_reason = 'Target crossed at fresh bid'
        if exit_reason:
            pending = _pending('SELL', state['lastBar'], now.isoformat(), exit_reason)
            state['pending'] = pending
    events.append(dict(type='forward-quote-observation', **quote_metadata, spreadBps=spread, equity=state['equity']))
    if state['status'] != 'running':
        events.append(dict(type='skipped', reason='Paper ingestion paused; exposure remains visible'))
        return events
    if not pending:
        return events
    # A normal intent requires a later exchange observation than the decision.
    # A quote-triggered protective exit uses the triggering quote itself.
    eligibility = pending.get('eligibleAfter')
    if not eligibility:
        state['pending'] = dict(pending, eligibleAfter=now.isoformat(), decisionAt=now.isoformat())
        events.append(dict(type='skipped', reason='Recovered intent needs a subsequent fresh quote'))
        return events
    if not exit_reason and (at <= timestamp(eligibility) or received < timestamp(eligibility)):
        events.append(dict(type='skipped', reason='Quote predates intent eligibility'))
        return events
    side = pending['side']
    if side not in ('BUY', 'SELL'):
        raise ValueError('Unknown intent side')
    raw = ask if side == 'BUY' else bid
    price, fee_per_unit = assumed_fill(raw, 1, side, config['costBps'], config['slippageBps'])
    if side == 'BUY':
        if state['quantity'] or state.get('entriesPaused') or state['riskHalted'] or now.time() >= dt.time.fromisoformat(config['entryEnd']):
            state['pending'] = None
            events.append(dict(type='rejected', side=side, reason='Entry paused, risk halted, held position or cutoff reached'))
            return events
        if spread > max_spread_bps:
            events.append(dict(type='skipped', side=side, reason='Observed spread exceeds entry cap'))
            return events
        stop = raw * (1-config['stopDistancePct']/100)
        sell, sell_fee = assumed_fill(stop, 1, 'SELL', config['costBps'], config['slippageBps'])
        risk_per_unit = price + fee_per_unit - sell + sell_fee
        remaining = max(0, config['dailyLossLimit'] - state['dayLoss'])
        requested = math.floor(min(config['units'], state['cash']/(price+fee_per_unit),
                                   config['maxExposure']/(price+fee_per_unit),
                                   min(config['maxLoss'], remaining)/risk_per_unit))
        units = min(requested, clean['askQuantity'])
        if units < 1:
            events.append(dict(type='skipped', side=side, reason='No whole share fits observed depth, capital and planned risk'))
            return events
        basis = units * (price+fee_per_unit)
        state['cash'] -= basis
        state['basis'] += basis
        state['quantity'] += units
        state['protection'] = dict(stop=stop, target=raw + raw*config['stopDistancePct']/100*config['targetMultiple'])
        state['pending'] = None
        if units < requested:
            events.append(dict(type='cancelled', side='BUY', reason='Unfilled entry remainder cancelled'))
    else:
        requested = state['quantity']
        units = min(requested, clean['bidQuantity'])
        if not units:
            events.append(dict(type='skipped', side=side, reason='No observed bid quantity; exit remains pending'))
            return events
        basis = state['basis'] * units / state['quantity']
        proceeds = units * (price-fee_per_unit)
        state['cash'] += proceeds
        state['basis'] -= basis
        state['realized'] += proceeds - basis
        state['quantity'] -= units
        state['pending'] = pending if state['quantity'] else None
        if not state['quantity']:
            state['completedTrades'] += 1
            state['recoveryRequired'] = False
            state.pop('protection', None)
    fee = units * fee_per_unit
    state['fees'] += fee
    state['equity'] = state['cash'] + state['quantity'] * bid
    state['dayLoss'] = max(0, state['dayStartEquity'] - state['equity'])
    state['riskHalted'] = state['riskHalted'] or state['dayLoss'] >= config['dailyLossLimit']
    events.append(dict(type='fill', side=side, quantity=units, price=price, fee=fee,
                       signalAt=pending.get('signalAt'), eligibleAfter=eligibility,
                       bar=at.isoformat(), exchangeAt=at.isoformat(), receivedAt=received.isoformat(),
                       decisionAt=now.isoformat(), reason=pending.get('reason'), mode='forward-quote-paper'))
    events.append(dict(type='order', side=side, state='FILLED' if units == requested else 'PARTIAL',
                       quantity=requested, filled=units, reason=pending.get('reason')))
    return events
