"""Load only pure order validation and Handler definitions; no app setup or real broker."""
import ast
import http.server
import hashlib
import hmac
import json
import math
import threading
import time
import unittest
import tempfile
import sqlite3
import secrets
import urllib.error
import urllib.request
import urllib.parse
import io
from execution_journal import ExecutionJournal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

source=ast.parse((Path(__file__).resolve().parents[1]/'app.py').read_text())
namespace=dict(sqlite3=sqlite3,math=math,hashlib=hashlib,Any=object,http=SimpleNamespace(server=http.server),time=time,LOCK=threading.RLock(),LIVE_ORDERS_ENABLED=True,LIVE_EXECUTION_READY=True,LIVE_READINESS_REASON="fixture readiness blocked")
exec(compile(ast.Module(body=[n for n in source.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in ('KiteError','KiteSessionExpired','kite_request','validate_order','Handler')],type_ignores=[]),'app.py','exec'),namespace)
validate=namespace['validate_order'];Handler=namespace['Handler']
ORDER=dict(exchange='NSE',tradingsymbol='INFY',transaction_type='BUY',product='CNC',order_type='LIMIT',quantity='2',price='100',validity='DAY')
class OrderTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        namespace["EXECUTION"]=ExecutionJournal(Path(directory.name)/"execution.sqlite")
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
        h.place_order({'profile':{'user_id':'fixture-user'},'access_token':'fixture'},ORDER|dict(confirm_text='PLACE LIVE ORDER',confirmation_id='a'*24))
        broker.assert_not_called();self.assertEqual(h.error.call_args.args[0],409)
    def test_expired_or_changed_review_blocked(self):
        for review in [dict(order=validate(ORDER),created=time.monotonic()-121),dict(order=validate(ORDER)|dict(quantity=99),created=time.monotonic())]:
            review['loginDigest']=hashlib.sha256(b'fixture').digest()
            h=self.handler();broker=Mock();namespace['kite_request']=broker
            h.place_order({'profile':{'user_id':'fixture-user'},'access_token':'fixture','reviews':{'a'*24:review}},ORDER|dict(confirm_text='PLACE LIVE ORDER',confirmation_id='a'*24))
            broker.assert_not_called()
    def test_ambiguous_submission_cannot_replay(self):
        h=self.handler();broker=Mock(side_effect=namespace['KiteError']('timeout'));namespace['kite_request']=broker
        session={'profile':{'user_id':'fixture-user'},'access_token':'fixture','reviews':{'a'*24:dict(order=validate(ORDER),created=time.monotonic(),loginDigest=hashlib.sha256(b'fixture').digest())}}
        values=ORDER|dict(confirm_text='PLACE LIVE ORDER',confirmation_id='a'*24)
        h.place_order(session,values);h.place_order(session,values)
        self.assertEqual(broker.call_count,1);self.assertEqual(h.error.call_args.args[0],409)
    def test_host_header_rejects_rebinding(self):
        h=self.handler();h.server=SimpleNamespace(server_port=8765)
        h.headers={'Host':'evil.example:8765'};self.assertFalse(h.valid_host())
        h.headers={'Host':'127.0.0.1:8765'};self.assertTrue(h.valid_host())

    def test_configured_permission_alone_cannot_send_order(self):
        h=self.handler();broker=Mock();namespace['kite_request']=broker
        namespace['LIVE_EXECUTION_READY']=False
        try:
            h.place_order({'access_token':'fixture'},ORDER)
            broker.assert_not_called()
            self.assertEqual(h.error.call_args.args[0],403)
        finally:
            namespace['LIVE_EXECUTION_READY']=True
    def test_expired_oauth_state_cannot_exchange_token(self):
        h=self.handler();h.redirect=Mock()
        h.session=lambda:('id', {'oauth_state':'fixture-state','oauth_created':time.monotonic()-601})
        h.kite_callback({'state':['fixture-state'],'status':['success'],'request_token':['fixture-token']})
        h.redirect.assert_called_once_with('/?notice=login_state_error')

    def _callback(self, fetch):
        h=self.handler();h.redirect=Mock();session={'oauth_state':'s','oauth_created':time.monotonic()}
        h.session=lambda:('id',session)
        with patch('broker_transport.fetch_json',fetch), patch.dict(namespace,API_KEY='fixture-key',API_SECRET='fixture-secret',hmac=hmac,urllib=urllib,json=json,
                           KITE_API='https://api.kite.trade',AUTO_SELECTOR=SimpleNamespace(enabled=False,profile=None)), \
                patch('urllib.request.urlopen',side_effect=AssertionError('plain urlopen must not be used')):
            h.kite_callback({'state':['s'],'status':['success'],'request_token':['fixture-token']})
        return h,session

    def test_oauth_token_exchange_uses_hardened_transport(self):
        fetch=Mock(return_value={'status':'success','data':{'access_token':'tok','user_id':'U1'}})
        h,session=self._callback(fetch)
        request=fetch.call_args.args[0]
        self.assertEqual(request.full_url,'https://api.kite.trade/session/token')
        h.redirect.assert_called_once_with('/?notice=connected')
        self.assertEqual(session['access_token'],'tok')

    def test_oauth_token_exchange_failure_is_generic(self):
        for failure in (urllib.error.HTTPError('https://api.kite.trade/session/token',302,'x',{},io.BytesIO(b'')),ValueError('Broker response changed its destination.')):
            h,session=self._callback(Mock(side_effect=failure))
            h.redirect.assert_called_once_with('/?notice=login_failed')
            self.assertNotIn('access_token',session)

    def test_idle_session_is_revoked_and_capacity_is_bounded(self):
        h=self.handler();h.headers={'Cookie':'tradelab_session=expired'}
        expired={'csrf':'old','access_token':'secret','last_seen':time.monotonic()-1801}
        sessions={'expired':expired}
        with patch.dict(namespace,SESSIONS=sessions,SESSION_IDLE_SECONDS=1800,MAX_SESSIONS=2,secrets=secrets):
            new_id,new_session=h.session()
            self.assertNotEqual(new_id,'expired');self.assertEqual(expired,{})
            for _ in range(4):
                h.headers={};h.session()
            self.assertEqual(len(sessions),2)
    def test_provider_error_bodies_never_reach_user(self):
        # Capture real wrapper before the handler tests replace namespace kite_request.
        source_tree=ast.parse((Path(__file__).resolve().parents[1]/'app.py').read_text())
        local=dict(namespace,urllib=urllib,json=json,API_KEY='fixture',KITE_API='https://api.kite.trade')
        function=next(n for n in source_tree.body if isinstance(n,ast.FunctionDef) and n.name=='kite_request')
        exec(compile(ast.Module(body=[function],type_ignores=[]),'app.py','exec'),local)
        error=urllib.error.HTTPError('https://fixture.invalid?token=secret',400,'secret',{},io.BytesIO(b'{"message":"secret"}'))
        with patch('broker_transport.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=error
            with self.assertRaises(namespace['KiteError']) as captured:
                local['kite_request']('/orders','fixture-token')
        self.assertNotIn('secret',str(captured.exception))
        response=Mock();response.geturl.return_value='https://api.kite.trade/orders';response.read.return_value=b'{"status":"error","message":"secret"}'
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        with patch('broker_transport.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=response
            with self.assertRaises(namespace['KiteError']) as captured:
                local['kite_request']('/orders','fixture-token')
        self.assertNotIn('secret',str(captured.exception))

    def test_paper_storage_failure_returns_safe_service_error(self):
        h=self.handler();h.path='/api/trader/paper-state'
        h.valid_host=lambda:True;h.authenticated_session=lambda:('fixture',{})
        h.body_json=lambda:{}
        paper=Mock();paper.status.side_effect=sqlite3.OperationalError('private/path/secret')
        with patch.dict(namespace,PAPER=paper,urllib=urllib):
            h.do_POST()
        self.assertEqual(h.error.call_args.args[0],503)
        self.assertNotIn('secret',h.error.call_args.args[1])

    def test_reconciliation_commit_holds_account_identity_lock(self):
        h=self.handler();h.path='/api/orders/reconcile';h.valid_host=lambda:True;h.body_json=lambda:{}
        session={'access_token':'fixture','profile':{'user_id':'fixture-user'}}
        h.authenticated_session=lambda:('fixture',session)
        class TrackingLock:
            active=False
            def __enter__(self):self.active=True
            def __exit__(self,*args):self.active=False
        lock=TrackingLock();journal=Mock()
        journal.account.return_value='account'
        def commit(*args):
            self.assertTrue(lock.active)
            return []
        journal.reconcile.side_effect=commit
        with patch.dict(namespace,LOCK=lock,EXECUTION=journal,urllib=urllib,kite_request=Mock(return_value={'data':[]})):
            h.do_POST()
        journal.reconcile.assert_called_once_with('account',[],[])
        self.assertEqual(h.json_response.call_args.args[0],200)

    def test_reconciliation_after_relogin_preserves_unresolved_intent(self):
        h=self.handler();h.path='/api/orders/reconcile';h.valid_host=lambda:True;h.body_json=lambda:{}
        session={'access_token':'fixture','profile':{'user_id':'fixture-user'}}
        h.authenticated_session=lambda:('fixture',session)
        journal=Mock();journal.account.return_value='account'
        def broker(*args):
            session['access_token']='changed'
            return {'data':[]}
        with patch.dict(namespace,EXECUTION=journal,urllib=urllib,kite_request=broker):h.do_POST()
        journal.reconcile.assert_not_called()
        self.assertEqual(h.error.call_args.args[0],409)
