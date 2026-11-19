"""Validate read-only broker evidence without granting order or ownership authority.

Broker REST reads are not atomic. Callers must bind the fetch to the authenticated
account, then recheck that identity before publishing the result. This module has
no network, credentials, mutation, allocation or order-submission capability.
"""
import datetime as dt
import hashlib
import json
import math
import re


TERMINAL = {'COMPLETE', 'CANCELLED', 'REJECTED'}


def _stamp(value):
    if not isinstance(value, str):
        raise ValueError('Snapshot timestamps must include a timezone.')
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Snapshot timestamps must include a timezone.')
    return parsed.astimezone(dt.timezone.utc)


def _text(value, label, pattern=r'[A-Za-z0-9_-]{1,64}'):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError('Invalid '+label+'.')
    return value


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Invalid '+label+'.')
    return value


def _units(value, label, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValueError('Invalid '+label+'.')
    return value


def _data(payloads, name):
    payload = payloads.get(name)
    if isinstance(payload, dict) and 'status' in payload:
        if payload.get('status') != 'success' or 'data' not in payload:
            raise ValueError('Unsuccessful '+name+' response.')
        payload = payload['data']
    return payload


def _scope(row, *, holding=False):
    if not isinstance(row, dict):
        raise ValueError('Broker records must be objects.')
    exchange = _text(row.get('exchange'), 'exchange', r'[A-Z0-9]{2,8}')
    symbol = _text(row.get('tradingsymbol'), 'symbol', r'[A-Z0-9&_-]{1,64}')
    product = 'CNC' if holding else _text(row.get('product'), 'product', r'[A-Z0-9_-]{1,16}')
    return exchange+':'+symbol+':'+product


def _list(payload, label):
    if not isinstance(payload, list) or len(payload)>20000:
        raise ValueError('Missing or oversized '+label+' list.')
    return payload


def _position_map(rows, *, holding=False):
    result = {}
    for row in _list(rows, 'holdings' if holding else 'positions'):
        scope = _scope(row, holding=holding)
        if scope in result:
            raise ValueError('Duplicate instrument/product ownership record.')
        quantity = _units(row.get('quantity'), 'quantity', 0 if holding else None)
        record = dict(quantity=quantity)
        if holding:
            record['t1Quantity'] = _units(row.get('t1_quantity', 0), 'unsettled quantity', 0)
        result[scope] = record
    return result


def _expected_map(value, label):
    if not isinstance(value, dict) or any(not isinstance(k,str) or not re.fullmatch(r'[A-Z0-9]{2,8}:[A-Z0-9&_-]{1,64}:[A-Z0-9_-]{1,16}',k) for k in value):
        raise ValueError('Expected '+label+' must map exact exchange:symbol:product to quantity.')
    return {k:_units(v,'expected quantity',0 if label=='holdings' else None) for k,v in value.items()}


def build_snapshot(account, payloads, *, expected=None, as_of, received_at, max_age_seconds=30):
    """Return validated, hashed read evidence and differences from explicit books.

    Required payloads: profile, funds, orders, trades, positions and holdings,
    each either raw broker data or a {status:'success',data:...} envelope.
    Optional expected: {cash, positions:{scope:quantity}, holdings:{scope:quantity},
    workingOrderIds:[...], tradeIds:[...]}. Holdings and net positions remain
    separate: they must never be summed as independently sellable inventory.
    Expected values are caller assertions, not a substitute for broker truth.
    """
    account = _text(account, 'account identity')
    if not isinstance(payloads, dict):
        raise ValueError('Broker payloads must be an object.')
    cutoff, received = _stamp(as_of), _stamp(received_at)
    age_limit = _number(max_age_seconds, 'freshness budget')
    if age_limit<=0 or not 0 <= (cutoff-received).total_seconds()<=age_limit:
        raise ValueError('Stale or future broker snapshot receipt.')
    profile = _data(payloads,'profile')
    if not isinstance(profile,dict) or profile.get('user_id') != account:
        raise ValueError('Broker profile does not match the bound account.')
    funds = _data(payloads,'funds')
    equity = funds.get('equity') if isinstance(funds,dict) else None
    if not isinstance(equity,dict) or not isinstance(equity.get('available'),dict):
        raise ValueError('Equity funding response is missing.')
    cash = _number(equity.get('net'), 'broker net funds')
    raw_cash = _number(equity['available'].get('cash'), 'broker available cash')
    positions_payload = _data(payloads,'positions')
    if not isinstance(positions_payload,dict):
        raise ValueError('Net position response is missing.')
    positions = _position_map(positions_payload.get('net'))
    holdings = _position_map(_data(payloads,'holdings'),holding=True)
    orders=[];order_ids=set();working=[];uncertain=[]
    for row in _list(_data(payloads,'orders'),'orders'):
        scope = _scope(row)
        identity = _text(row.get('order_id'),'order identity')
        if identity in order_ids: raise ValueError('Duplicate broker order identity.')
        order_ids.add(identity)
        side = row.get('transaction_type')
        if side not in ('BUY','SELL'): raise ValueError('Invalid order side.')
        quantity = _units(row.get('quantity'),'order quantity',1)
        filled = _units(row.get('filled_quantity'),'filled quantity',0)
        state = _text(row.get('status'),'order status',r'[A-Z0-9 _-]{1,64}')
        if filled>quantity or (state=='COMPLETE' and filled!=quantity) or (state=='REJECTED' and filled):
            raise ValueError('Broker order state conflicts with fill quantity.')
        orders.append(dict(id=identity,scope=scope,side=side,quantity=quantity,filled=filled,state=state))
        if state not in TERMINAL: working.append(identity)
        if state in ('UNKNOWN','SUBMITTING') or state not in TERMINAL|{'OPEN','PARTIAL','TRIGGER PENDING','OPEN PENDING','MODIFY PENDING','MODIFY VALIDATION PENDING','CANCEL PENDING','AMO REQ RECEIVED','PUT ORDER REQ RECEIVED','VALIDATION PENDING'}:
            uncertain.append(identity)
    trade_ids=set();trades=[]
    for row in _list(_data(payloads,'trades'),'trades'):
        scope = _scope(row)
        identity = _text(row.get('trade_id'),'trade identity')
        if identity in trade_ids: raise ValueError('Duplicate trade identity.')
        trade_ids.add(identity)
        order = _text(row.get('order_id'),'trade order identity')
        quantity = _units(row.get('quantity'),'trade quantity',1)
        price = _number(row.get('average_price'),'trade price')
        if price<=0 or row.get('transaction_type') not in ('BUY','SELL'):
            raise ValueError('Invalid trade evidence.')
        trades.append(dict(id=identity,orderId=order,scope=scope,quantity=quantity,price=price,side=row['transaction_type']))
    differences=[]
    by_order={row['id']:row for row in orders}
    traded={}
    for trade in trades:
        order=by_order.get(trade['orderId'])
        if order is None:
            differences.append('Trade has no matching order in this read; sequential snapshot or external activity requires review.')
            continue
        if (trade['scope'],trade['side']) != (order['scope'],order['side']):
            raise ValueError('Trade instrument/product/side conflicts with its broker order.')
        traded[order['id']]=traded.get(order['id'],0)+trade['quantity']
    for order in orders:
        if traded.get(order['id'],0)!=order['filled']:
            differences.append('Order/trade fill quantities differ; refetch evidence before reconciliation.')
    if cash<0 or raw_cash<0: differences.append('Broker funds are negative.')
    if uncertain: differences.append('Uncertain broker order states require investigation.')
    if expected is None:
        differences.append('Strategy allocations and external activity have not been reconciled.')
    else:
        keys={'cash','positions','holdings','workingOrderIds','tradeIds'}
        if not isinstance(expected,dict) or set(expected)!=keys:
            raise ValueError('Complete explicit expected book evidence is required.')
        expected_cash = _number(expected['cash'],'expected cash')
        if not math.isclose(cash,expected_cash,rel_tol=0,abs_tol=.01): differences.append('Cash differs from the expected books.')
        ep=_expected_map(expected['positions'],'positions');eh=_expected_map(expected['holdings'],'holdings')
        if {k:v['quantity'] for k,v in positions.items() if v['quantity']}!={k:v for k,v in ep.items() if v}:
            differences.append('Net positions differ; external/manual exposure or ownership mismatch.')
        if {k:v['quantity'] for k,v in holdings.items() if v['quantity']}!={k:v for k,v in eh.items() if v}:
            differences.append('Holdings differ; do not infer sellable strategy inventory.')
        for key,actual in (('workingOrderIds',set(working)),('tradeIds',trade_ids)):
            ids=expected[key]
            if not isinstance(ids,list) or any(not isinstance(i,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',i) for i in ids) or len(ids)!=len(set(ids)):
                raise ValueError('Expected activity IDs must be unique strings.')
            if set(ids)!=actual: differences.append(key+' differ; external/unmatched activity requires review.')
    evidence=dict(accountHash=hashlib.sha256(('zerodha:'+account).encode()).hexdigest(),
                  receivedAt=received.isoformat(),asOf=cutoff.isoformat(),funds=dict(net=cash,availableCash=raw_cash),
                  positions=positions,holdings=holdings,orders=orders,trades=trades)
    fingerprint=hashlib.sha256(json.dumps(evidence,sort_keys=True,allow_nan=False).encode()).hexdigest()
    return dict(**evidence,fingerprint=fingerprint,workingOrderIds=working,uncertainOrderIds=uncertain,
                differences=differences,matchesExpected=expected is not None and not differences,
                executionAllowed=False,positionsReconciled=False,cashComparisonBasis='Broker net funds, not certified sellable inventory or withdrawable cash.',
                scope='Read-only sequential broker snapshot; matching caller books is not atomic broker ownership proof.',
                limitations=['No live order authority.','Broker reads may change between endpoints.',
                             'Receipt freshness is not an exchange timestamp or complete account history.',
                             'Holdings, unsettled shares and net positions are separate; no sellable total inferred.'])
