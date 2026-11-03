"""Load only pure order validation and Handler definitions; no app setup or real broker."""
import ast
import http.server
import json
import math
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

source=ast.parse((Path(__file__).resolve().parents[1]/'app.py').read_text())
namespace=dict(math=math,Any=object,http=SimpleNamespace(server=http.server),time=time,LOCK=threading.RLock(),LIVE_ORDERS_ENABLED=True)
exec(compile(ast.Module(body=[n for n in source.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in ('KiteError','KiteSessionExpired','validate_order','Handler')],type_ignores=[]),'app.py','exec'),namespace)
validate=namespace['validate_order'];Handler=namespace['Handler']
ORDER=dict(exchange='NSE',tradingsymbol='INFY',transaction_type='BUY',product='CNC',order_type='LIMIT',quantity='2',price='100',validity='DAY')
class OrderTests(unittest.TestCase):
    def test_fraction_boolean_and_nonfinite_quantity_rejected(self):
        for value in [1.5,True,float('inf'),'2.2']:
            with self.assertRaises(ValueError):validate(ORDER|dict(quantity=value))
    def test_stop_limit_direction_validated(self):
        with self.assertRaises(ValueError):validate(ORDER|dict(order_type='SL',trigger_price=110))
        self.assertEqual(validate(ORDER|dict(order_type='SL',trigger_price=90))['price'],100)
    def handler(self):
        h=object.__new__(Handler);h.error=Mock();h.json_response=Mock();return h
    def test_unreviewed_order_cannot_submit(self):
        h=self.handler();broker=Mock();namespace['kite_request']=broker
        h.place_order({'access_token':'fixture'},ORDER|dict(confirm_text='PLACE LIVE ORDER',confirmation_id='a'*24))
        broker.assert_not_called();self.assertEqual(h.error.call_args.args[0],409)
    def test_expired_or_changed_review_blocked(self):
        for review in [dict(order=validate(ORDER),created=time.monotonic()-121),dict(order=validate(ORDER)|dict(quantity=99),created=time.monotonic())]:
            h=self.handler();broker=Mock();namespace['kite_request']=broker
            h.place_order({'access_token':'fixture','reviews':{'a'*24:review}},ORDER|dict(confirm_text='PLACE LIVE ORDER',confirmation_id='a'*24))
            broker.assert_not_called()
    def test_ambiguous_submission_cannot_replay(self):
        h=self.handler();broker=Mock(side_effect=namespace['KiteError']('timeout'));namespace['kite_request']=broker
        session={'access_token':'fixture','reviews':{'a'*24:dict(order=validate(ORDER),created=time.monotonic())}}
        values=ORDER|dict(confirm_text='PLACE LIVE ORDER',confirmation_id='a'*24)
        h.place_order(session,values);h.place_order(session,values)
        self.assertEqual(broker.call_count,1);self.assertEqual(h.error.call_args.args[0],409)
    def test_host_header_rejects_rebinding(self):
        h=self.handler();h.server=SimpleNamespace(server_port=8765)
        h.headers={'Host':'evil.example:8765'};self.assertFalse(h.valid_host())
        h.headers={'Host':'127.0.0.1:8765'};self.assertTrue(h.valid_host())
