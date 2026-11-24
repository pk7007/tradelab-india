"""Mock-only design of the live safety path: kill with confirmed closure, and broker reconciliation.

Nothing here can reach a broker. `kill_with_confirmation` only talks to an object whose `mode` is 'offline-mock'; any
other broker is refused before it is touched, after the risk gate has already been killed (entries blocked). It never
raises. Closure is CONFIRMED_FLAT only when a snapshot with a strictly newer revision than the pre-kill snapshot (or the
pre-kill snapshot itself when nothing needed doing) shows no position and no working order. Every other outcome is
NOT_CONFIRMED with the residual exposure listed, because a cancel or exit request is not proof that it worked.
Any order state other than COMPLETE, CANCELLED or REJECTED (including a missing or unknown state) counts as working.
An exit is held until a newer snapshot shows every working order on the same side of the same symbol as terminal
(an acknowledged cancel is not enough), so a stuck stop and a new exit cannot both fill and reverse the position.

`reconcile` compares the local ledger with a broker snapshot: positions, missing or unknown orders, fills, order
details and working-versus-terminal state. Any difference, or input it cannot read, blocks new entries; it never
blocks exits.

Relation to execution_controls.py: ExecutionControls.observe is the stricter contract for a future live adapter
(monotonic revision, receipt within 5 s, bounded payloads, NSE MIS scopes). This module is the minimal drill of the
kill-and-confirm sequence; a live adapter must satisfy both, and must route cancel and exit bursts through
api_rate_limits.AtomicRateLimiter, which this mock does not exercise.
"""
import copy
import itertools

TERMINAL = {'COMPLETE', 'CANCELLED', 'REJECTED'}


def _working(order):
    return order.get('state') not in TERMINAL


class MockBroker:
    """In-memory broker for tests and drills. Positions are signed share counts; every change bumps `revision`."""

    mode = 'offline-mock'

    def __init__(self, positions=None, orders=None, *, failing_cancels=(), exit_fill_ratio=1.0, rejected_exits=(),
                 snapshot_failures=0):
        self.positions = dict(positions or {})
        self.orders = [dict(order) for order in (orders or [])]
        self.failing_cancels, self.rejected_exits = set(failing_cancels), set(rejected_exits)
        self.exit_fill_ratio, self.snapshot_failures = exit_fill_ratio, snapshot_failures
        self.revision, self.calls, self._ids = 1, [], itertools.count(1)

    def snapshot(self):
        self.calls.append(('snapshot',))
        if self.snapshot_failures:
            self.snapshot_failures -= 1
            raise TimeoutError('mock broker unreachable')
        return dict(revision=self.revision, positions=copy.deepcopy(self.positions), orders=copy.deepcopy(self.orders))

    def cancel(self, order_id):
        self.calls.append(('cancel', order_id))
        if order_id in self.failing_cancels:
            raise TimeoutError('mock cancel timed out')
        order = next(o for o in self.orders if o['id'] == order_id)
        if _working(order):
            order['state'] = 'CANCELLED'
            self.revision += 1
        return order_id

    def submit_exit(self, intent):
        self.calls.append(('exit', intent['symbol'], intent['side'], intent['quantity']))
        identity = 'mock-exit-%d' % next(self._ids)
        self.revision += 1
        if intent['symbol'] in self.rejected_exits:
            self.orders.append(dict(id=identity, symbol=intent['symbol'], side=intent['side'], quantity=intent['quantity'],
                                    filled=0, state='REJECTED'))
            return identity
        filled = int(intent['quantity'] * self.exit_fill_ratio)
        sign = -1 if intent['side'] == 'SELL' else 1
        self.positions[intent['symbol']] = self.positions.get(intent['symbol'], 0) + sign * filled
        self.orders.append(dict(id=identity, symbol=intent['symbol'], side=intent['side'], quantity=intent['quantity'],
                                filled=filled, state='COMPLETE' if filled == intent['quantity'] else 'PARTIAL'))
        return identity


def _snapshot(broker):
    """A validated snapshot or ValueError."""
    snap = broker.snapshot()
    if not isinstance(snap, dict) or type(snap.get('revision')) is not int or snap['revision'] < 1:
        raise ValueError('snapshot without a revision')
    positions, orders = snap.get('positions'), snap.get('orders')
    if not isinstance(positions, dict) or not all(isinstance(k, str) and type(v) is int for k, v in positions.items()):
        raise ValueError('invalid positions')
    if not isinstance(orders, list) or not all(isinstance(o, dict) and isinstance(o.get('id'), str) for o in orders):
        raise ValueError('invalid orders')
    return snap


def _rows(positions):
    return [dict(symbol=symbol, side='BUY' if quantity > 0 else 'SELL', quantity=abs(quantity))
            for symbol, quantity in sorted(positions.items()) if quantity]


def _residual(snapshot):
    return ({s: q for s, q in snapshot['positions'].items() if q}, [o['id'] for o in snapshot['orders'] if _working(o)])


def kill_with_confirmation(gate, broker):
    """Kill the gate, cancel working orders, request exits, then confirm closure from newer evidence. Never raises."""
    result = dict(closure='NOT_CONFIRMED', positionsClosed=False, submittedToRealBroker=False, cancels=[], exits=[],
                  residualPositions=None, workingOrders=None, problems=[])
    try:
        is_mock = getattr(broker, 'mode', None) == 'offline-mock'
    except Exception:
        is_mock = False
    if not is_mock:
        result['intents'] = gate.kill(None, None)
        result['problems'].append('Refused: only an offline mock broker may be used; live protective operations are disabled.')
        return result
    try:
        before = _snapshot(broker)
        positions, working = _residual(before)
    except Exception as error:
        result['intents'] = gate.kill(None, None)
        result['problems'].append('Broker state unavailable before the kill (%s); exposure unknown.' % type(error).__name__)
        return result
    intents = gate.kill(working, _rows(positions))
    result['intents'] = intents
    orders = {o['id']: o for o in before['orders']}
    exit_sides = {(intent['symbol'], intent['side']) for intent in intents['exitRequests']}
    blocking = {o['id'] for o in before['orders'] if _working(o) and (o.get('symbol'), o.get('side')) in exit_sides}
    stuck = set()
    for order_id in intents['cancelRequests']:
        try:
            broker.cancel(order_id)
            result['cancels'].append(dict(orderId=order_id, outcome='REQUESTED'))
        except Exception as error:
            result['cancels'].append(dict(orderId=order_id, outcome='FAILED', error=type(error).__name__))
            order = orders.get(order_id, {})
            stuck.add((order.get('symbol'), order.get('side')))
    if blocking:   # an acknowledged cancel is not a cancelled order: wait for newer evidence that it is terminal
        try:
            middle = _snapshot(broker)
            if middle['revision'] <= before['revision']:
                raise ValueError('no newer evidence')
            states = {o['id']: o for o in middle['orders']}
            for order_id in blocking:
                if order_id not in states or _working(states[order_id]):
                    stuck.add((orders[order_id].get('symbol'), orders[order_id].get('side')))
        except Exception:
            stuck.update((orders[i].get('symbol'), orders[i].get('side')) for i in blocking)
    for intent in intents['exitRequests']:
        if (intent['symbol'], intent['side']) in stuck:
            result['exits'].append(dict(intent, outcome='HELD', reason='A same-side order could not be cancelled; an exit could double-fill.'))
            continue
        try:
            result['exits'].append(dict(intent, outcome='REQUESTED', orderId=broker.submit_exit(dict(intent))))
        except Exception as error:
            result['exits'].append(dict(intent, outcome='FAILED', error=type(error).__name__))
    acted = bool(result['cancels'] or result['exits'])
    try:
        after = _snapshot(broker)
        positions, working = _residual(after)
    except Exception as error:
        result['problems'].append('Broker state unavailable after the kill (%s); closure cannot be confirmed.' % type(error).__name__)
        return result
    result.update(residualPositions=positions, workingOrders=working)
    if acted and after['revision'] <= before['revision']:
        result['problems'].append('No newer broker evidence after the kill requests; closure cannot be confirmed.')
    elif positions or working or intents['rejectedPositions']:
        result['problems'].append('Exposure remains after the kill; manage it at the broker and reconcile.')
    else:
        result.update(closure='CONFIRMED_FLAT', positionsClosed=True)
    return result


CORE = ('symbol', 'side', 'quantity', 'filled', 'state')


def _order_map(orders):
    if isinstance(orders, dict):
        orders = [dict(order, id=key) for key, order in orders.items()]
    mapped = {}
    for order in orders:
        if (not isinstance(order, dict) or not isinstance(order.get('id'), str) or order['id'] in mapped
                or any(field not in order for field in CORE)):
            raise ValueError('Each order needs a unique string id and %s.' % ', '.join(CORE))
        mapped[order['id']] = order
    return mapped


def _positions(value):
    if not isinstance(value, dict) or not all(isinstance(k, str) and type(v) is int for k, v in value.items()):
        raise ValueError('Positions must map symbols to whole share counts.')
    return {k: v for k, v in value.items() if v}


def reconcile(ledger, snapshot):
    """Every difference between the local ledger and a broker snapshot. Unreadable input fails closed."""
    try:
        ledger_positions, broker_positions = _positions(ledger['positions']), _positions(snapshot['positions'])
        ledger_orders, broker_orders = _order_map(ledger['orders']), _order_map(snapshot['orders'])
    except (KeyError, TypeError, ValueError) as error:
        return dict(status='UNVERIFIED', blockNewEntries=True, mismatches=[], detail='Unreadable input: %s' % error)
    mismatches = []
    for symbol in sorted(set(ledger_positions) | set(broker_positions)):
        if ledger_positions.get(symbol, 0) != broker_positions.get(symbol, 0):
            mismatches.append(dict(kind='position-mismatch', symbol=symbol, ledger=ledger_positions.get(symbol, 0),
                                   broker=broker_positions.get(symbol, 0)))
    for order_id in sorted(set(ledger_orders) - set(broker_orders)):
        mismatches.append(dict(kind='missing-at-broker', orderId=order_id))
    for order_id in sorted(set(broker_orders) - set(ledger_orders)):
        mismatches.append(dict(kind='unknown-at-broker', orderId=order_id, detail='Placed outside this system (for example a manual order).'))
    for order_id in sorted(set(ledger_orders) & set(broker_orders)):
        mine, theirs = ledger_orders[order_id], broker_orders[order_id]
        for field in ('symbol', 'side', 'quantity'):
            if mine[field] != theirs[field]:
                mismatches.append(dict(kind='order-mismatch', orderId=order_id, field=field, ledger=mine[field], broker=theirs[field]))
        if mine['filled'] != theirs['filled']:
            mismatches.append(dict(kind='fill-mismatch', orderId=order_id, ledger=mine['filled'], broker=theirs['filled']))
        if _working(mine) != _working(theirs):
            mismatches.append(dict(kind='state-mismatch', orderId=order_id, ledger=mine['state'], broker=theirs['state']))
    return dict(status='MISMATCH' if mismatches else 'MATCHED', blockNewEntries=bool(mismatches), mismatches=mismatches,
                detail='Exits and square-off are never blocked by reconciliation; only new entries are.')
