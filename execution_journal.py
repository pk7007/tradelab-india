"""Durable manual submission journal; broker evidence, never retry inference, resolves intents."""
from contextlib import contextmanager
import hashlib
import json
import math
import secrets
import sqlite3
import time
from pathlib import Path

TERMINAL = {'COMPLETE', 'CANCELLED', 'REJECTED'}

class ExecutionJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS intents (id TEXT PRIMARY KEY, account TEXT NOT NULL, scope TEXT NOT NULL, body TEXT NOT NULL)')
    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()
    @staticmethod
    def account(profile):
        identity = str((profile or {}).get('user_id') or '').strip()
        if not identity:
            raise ValueError('Broker account identity is missing. Reconnect before placing orders.')
        return hashlib.sha256(('zerodha:' + identity).encode()).hexdigest()
    def list(self, account):
        with self.db() as db:
            items = [json.loads(row[0]) for row in db.execute('SELECT body FROM intents WHERE account=? ORDER BY rowid DESC', (account,))]
            for item in items:
                item.pop('sessionDigest', None)
            return items
    def prepare(self, account, review_id, order, login_digest):
        identity = hashlib.sha256((account + review_id).encode()).hexdigest()
        scope = '|'.join(str(order[k]) for k in ('exchange', 'tradingsymbol', 'product'))
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM intents WHERE id=?', (identity,)).fetchone():
                raise ValueError('This review already has a durable submission. Reconcile its outcome.')
            for row in db.execute('SELECT body FROM intents WHERE account=? AND scope=?', (account, scope)):
                if json.loads(row[0])['state'] not in TERMINAL:
                    raise ValueError('An unresolved order exists for this instrument and product. Reconcile before another submission.')
            intent = dict(id=identity, tag='TL' + secrets.token_hex(9), order=order, state='SUBMITTING', brokerOrderId=None,
                          filledQuantity=0, created=time.time(), sessionDigest=login_digest.hex(), source='manual', strategyVersion='manual-v1')
            db.execute('INSERT INTO intents VALUES (?,?,?,?)', (identity, account, scope, json.dumps(intent)))
            return intent
    def acknowledgement(self, identity, order_id=None):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM intents WHERE id=?', (identity,)).fetchone()
            item = json.loads(row[0])
            # A late acknowledgement must not undo already reconciled state.
            if item['state'] in TERMINAL:
                return
            if item.get('brokerOrderId') and order_id and item['brokerOrderId'] != order_id:
                item['state'] = 'UNKNOWN'
            else:
                item['brokerOrderId'] = order_id or item.get('brokerOrderId')
                if item['state'] not in {'PARTIAL', 'OPEN'}:
                    item['state'] = 'ACKNOWLEDGED' if order_id else 'UNKNOWN'
            db.execute('UPDATE intents SET body=? WHERE id=?', (json.dumps(item), identity))
    def reconcile(self, account, orders, trades):
        if not isinstance(orders, list) or not isinstance(trades, list):
            raise ValueError('Broker reconciliation requires order and trade lists.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('SELECT id,body FROM intents WHERE account=?', (account,)).fetchall()
            for identity, body in rows:
                item = json.loads(body)
                if item['state'] in TERMINAL:
                    continue
                matches = [o for o in orders if isinstance(o, dict) and (o.get('tag') == item['tag'] or (item['brokerOrderId'] and o.get('order_id') == item['brokerOrderId']))]
                if len(matches) != 1:
                    item['state'] = 'UNKNOWN'
                    item['reason'] = 'No unique broker match; absence is not proof of rejection.'
                else:
                    broker = matches[0]
                    expected = item['order']
                    keys = tuple(k for k in ('exchange', 'tradingsymbol', 'product', 'transaction_type', 'quantity', 'order_type', 'price', 'trigger_price', 'validity', 'variety') if k in expected)
                    try:
                        filled = broker.get('filled_quantity')
                        valid = (broker.get('tag') == item['tag']
                                 and all(broker.get(k) == expected[k] for k in keys)
                                 and isinstance(filled, int) and not isinstance(filled, bool)
                                 and item['filledQuantity'] <= filled <= expected['quantity']
                                 and bool(broker.get('order_id'))
                                 and (not item['brokerOrderId'] or item['brokerOrderId'] == broker['order_id']))
                        matching_trades = [t for t in trades if isinstance(t, dict) and t.get('order_id') == broker.get('order_id')]
                        trade_ids = [t.get('trade_id') for t in matching_trades]
                        trade_quantity = sum(t['quantity'] for t in matching_trades)
                        valid = valid and len(set(trade_ids)) == len(trade_ids) and all(trade_ids) and trade_quantity == filled
                        valid = valid and all(all(t.get(k) == expected[k] for k in ('exchange','tradingsymbol','product','transaction_type'))
                                              and isinstance(t['quantity'], int) and not isinstance(t['quantity'], bool) and t['quantity'] > 0
                                              and type(t.get('average_price')) in (int,float) and math.isfinite(t['average_price']) and t['average_price'] > 0
                                              and (expected['order_type'] not in ('LIMIT','SL') or
                                                   (t['average_price'] <= expected['price'] if expected['transaction_type']=='BUY' else t['average_price'] >= expected['price']))
                                              for t in matching_trades)
                        status = broker.get('status')
                        valid = valid and (status != 'COMPLETE' or filled == expected['quantity']) and (status != 'REJECTED' or filled == 0)
                    except (KeyError, TypeError, ValueError):
                        valid = False
                    if not valid:
                        item['state'] = 'UNKNOWN'
                        item['reason'] = 'Broker order/trade evidence conflicts with intent or recorded fills.'
                    else:
                        item.update(brokerOrderId=broker['order_id'], filledQuantity=filled,
                                    state=status if status in TERMINAL else ('PARTIAL' if filled else 'OPEN'), reason='Broker order and trades matched.')
                item['reconciledAt'] = time.time()
                db.execute('UPDATE intents SET body=? WHERE id=?', (json.dumps(item), identity))
        return self.list(account)
