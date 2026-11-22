"""Opt-in intraday OHLC simulation. Prices and available volume are assumptions."""
import datetime as dt
import math
from strategy_contract import assumed_fill, target_long

VERSION = 'intraday-v1'


def validate(data):
    result = {}
    for key, low, high in [('maxLoss', .01, 1e12), ('stopDistancePct', .01, 50), ('targetMultiple', .1, 20), ('participationPct', .01, 100)]:
        value = data.get(key)
        if isinstance(value, bool): raise ValueError('Invalid '+key)
        try: value = float(value)
        except (TypeError, ValueError): raise ValueError('Specify '+key) from None
        if not math.isfinite(value) or not low <= value <= high: raise ValueError('Invalid '+key)
        result[key] = value
    for key in ('entryEnd', 'squareOff'):
        try: value = dt.time.fromisoformat(data[key])
        except (KeyError, TypeError, ValueError): raise ValueError('Specify '+key+' as HH:MM IST') from None
        if value.tzinfo or value.second or value.microsecond or value.minute % 5: raise ValueError('Five-minute IST boundary required.')
        result[key] = value.isoformat(timespec='minutes')
    if not '09:15' < result['entryEnd'] < result['squareOff'] <= '15:25': raise ValueError('Require 09:15 < entryEnd < squareOff <= 15:25.')
    if result['maxLoss'] > float(data['dailyLossLimit']): raise ValueError('Trade risk cannot exceed daily loss threshold.')
    return result


def entry_size(s, price, volume):
    """Shared pre-entry and fill-time whole-share risk calculation."""
    c=s['config']
    stop=price*(1-c['stopDistancePct']/100)
    buy,buy_fee=assumed_fill(price,1,'BUY',c['costBps'],c['slippageBps'])
    sell,sell_fee=assumed_fill(stop,1,'SELL',c['costBps'],c['slippageBps'])
    opening_equity=s['cash']+s['quantity']*price
    remaining=max(0,c['dailyLossLimit']-max(0,s['dayStartEquity']-opening_equity))
    return max(0,math.floor(min(c['units'],s['cash']/(buy+buy_fee),c['maxExposure']/(buy+buy_fee),
                  min(c['maxLoss'],remaining)/(buy+buy_fee-sell+sell_fee),volume*c['participationPct']/100)))


def advance(s, bar, entry_gate=None):
    """Update one accepted completed candle; return journal events for same transaction."""
    c = s['config']; day = bar['date'][:10]; clock = bar['date'][11:16]
    events = []
    entry_review_id=None
    def event(kind, **extra): events.append(dict(type=kind, bar=bar['date'], **extra))
    if day != s['day']:
        if s['quantity']:
            s['entriesPaused'] = True
            s['recoveryRequired'] = True
            s['pending'] = dict(side='SELL', signalAt=s['lastBar'], reason='Missed prior-session exit')
            event('recovery', detail='Prior session shares remain exposed; entries paused, exit waits for modeled liquidity.')
        else:
            s.update(day=day, dayStartEquity=s['equity'], dayLoss=0, riskHalted=False, closes=[])
    capacity = 0 if bar.get('halted') or bar.get('reject') else math.floor(bar['volume'] * c['participationPct'] / 100)
    used = 0
    def fill(side, requested, raw, reason):
        nonlocal used
        units = min(requested, max(0, capacity-used))
        if not units:
            event('order', side=side, state='OPEN', quantity=requested, reason='No modeled volume available: '+reason)
            return 0
        price, fee = assumed_fill(raw, units, side, c['costBps'], c['slippageBps'])
        if side == 'BUY':
            s['cash'] -= units*price+fee; s['basis'] += units*price+fee; s['quantity'] += units
        else:
            basis = s['basis'] * units / s['quantity']
            s['cash'] += units*price-fee; s['basis'] -= basis
            s['realized'] += units*price-fee-basis; s['quantity'] -= units
            if not s['quantity']: s['completedTrades'] += 1
        used += units; s['fees'] += fee
        if side=='BUY' and entry_review_id:
            s['lastEntryReviewId']=entry_review_id
        event('fill', side=side, quantity=units, price=price, fee=fee, signalAt=s.get('pending',{}).get('signalAt') if s.get('pending') else s['lastBar'],
              reason=reason,reviewId=entry_review_id if side=='BUY' else s.get('lastEntryReviewId'))
        event('order', side=side, state='FILLED' if units==requested else 'PARTIAL', quantity=requested, filled=units, reason=reason)
        return units
    opening_equity = s['cash']+s['quantity']*bar['open']
    if s['dayStartEquity']-opening_equity >= c['dailyLossLimit']: s['riskHalted'] = True
    pending = s.get('pending'); s['pending'] = None
    if s['quantity'] and (clock >= c['squareOff'] or s.get('recoveryRequired')):
        pending = dict(side='SELL',signalAt=s['lastBar'],reason='Session square-off or recovery')
    if pending and pending['side']=='SELL' and s['quantity']:
        fill('SELL',s['quantity'],bar['open'],pending.get('reason','Completed-bar exit'))
        if s['quantity']: s['pending'] = pending
    elif pending and pending['side']=='BUY':
        review=entry_gate('consume',s,bar,pending) if entry_gate else dict(status='eligible',maxQuantity=c['units'])
        if review['status']=='waiting':
            s['pending']=pending
        elif review['status']!='eligible':
            event('rejected',side='BUY',reason=review['reason'],reviewId=pending.get('reviewId'))
        elif s.get('entriesPaused') or s['riskHalted'] or clock >= c['entryEnd'] or s['quantity']:
            event('rejected',side='BUY',reason='Entry paused, risk halted, entry window ended, or shares already held')
        else:
            entry_review_id=pending.get('reviewId')
            stop = bar['open']*(1-c['stopDistancePct']/100)
            units=min(entry_size(s,bar['open'],math.inf),review['maxQuantity'])
            if units < 1: event('rejected',side='BUY',reason='No whole share fits capital, costs and planned risk')
            else:
                filled=fill('BUY',units,bar['open'],'SMA completed-close entry; unfilled remainder cancelled')
                if filled:
                    s['protection'] = dict(stop=stop,target=bar['open']+(bar['open']-stop)*c['targetMultiple'])
                if filled<units: event('cancelled',side='BUY',reason='Unfilled entry remainder cancelled')
    if s['quantity'] and not s.get('pending'):
        p=s.get('protection')
        reason=raw=None
        if p:
            if bar['open']<=p['stop']: raw=bar['open'];reason='Stop gap at observed open'
            elif bar['low']<=p['stop']: raw=p['stop'];reason='Protective stop; stop-first if both levels crossed'
            elif bar['open']>=p['target']: raw=p['target'];reason='Target, no favourable gap assumption'
            elif bar['high']>=p['target']: raw=p['target'];reason='Target crossed'
        if raw is not None:
            fill('SELL',s['quantity'],raw,reason)
            if s['quantity']: s['pending']=dict(side='SELL',signalAt=bar['date'],reason=reason)
    s['equity']=s['cash']+s['quantity']*bar['close']
    s['dayLoss']=max(0,s['dayStartEquity']-s['equity']);s['riskHalted']=s['riskHalted'] or s['dayLoss']>=c['dailyLossLimit']
    s['closes']=(s['closes']+[bar['close']])[-20:];s['lastBar']=bar['date']
    if not s['quantity']:
        s.pop('protection',None)
        # Recovery remains entry-paused until explicit operator resume, but a
        # completed exit must not contaminate a later independently resumed trade.
        s['recoveryRequired'] = False
    if not s.get('pending') and clock < c['entryEnd'] and len(s['closes'])==20:
        long=target_long(s['closes'])
        side='SELL' if not long and s['quantity'] else 'BUY' if long and not s['quantity'] and not s['riskHalted'] and not s.get('entriesPaused') else None
        if side:
            proposed=dict(side=side,signalAt=bar['date'])
            if side=='BUY' and entry_gate:
                reviewed=entry_gate('create',s,bar,proposed)
                if reviewed['status']=='eligible':
                    proposed['reviewId']=reviewed['reviewId']
                    s['pending']=proposed
            else:
                s['pending']=proposed
    return events
