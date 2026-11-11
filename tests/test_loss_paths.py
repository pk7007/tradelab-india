import datetime as dt
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import secrets
import tempfile
import unittest
import urllib.parse
from unittest.mock import Mock
from unittest.mock import patch
import sqlite3

from market_data import MarketData
from paper import PaperEngine
from test_orders import Handler, ORDER, namespace
from test_paper import CONFIG, bars


class LossPathTests(unittest.TestCase):
    def reviewed(self):
        handler=object.__new__(Handler)
        handler.error=Mock()
        handler.json_response=Mock()
        session={'access_token':'first-fixture'}
        handler.valid_host=lambda:True
        handler.authenticated_session=lambda:('fixture',session)
        handler.body_json=lambda:ORDER
        handler.path='/api/orders/preview'
        namespace.update(secrets=secrets,urllib=urllib,kite_request=Mock(return_value={'data':{}}))
        handler.do_POST()
        identity=handler.json_response.call_args.args[1]['confirmationId']
        handler.json_response.reset_mock()
        return handler,session,dict(ORDER,confirmation_id=identity,confirm_text='PLACE LIVE ORDER')

    def test_login_change_invalidates_actual_preview(self):
        handler,session,request=self.reviewed()
        session['access_token']='second-fixture'
        handler.place_order(session,request)
        namespace['kite_request'].assert_not_called()
        self.assertEqual(handler.error.call_args.args[0],409)

    def test_missing_order_id_is_unknown_and_review_consumed(self):
        handler,session,request=self.reviewed()
        handler.place_order(session,request)
        self.assertEqual(handler.error.call_args.args[0],502)
        handler.json_response.assert_not_called()
        handler.place_order(session,request)
        self.assertEqual(namespace['kite_request'].call_count,1)

    def test_double_approval_one_submission(self):
        handler,session,request=self.reviewed()
        namespace['kite_request'].return_value={'data':{'order_id':'fixture-ID'}}
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _:handler.place_order(session,request),range(2)))
        self.assertEqual(namespace['kite_request'].call_count,1)
        self.assertEqual(len(session['submitted']),1)
        self.assertEqual(handler.json_response.call_args.args[1]['orderId'],'fixture-ID')

    def test_write_failure_after_fill_rolls_back_intent_and_cash(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'paper.sqlite'
            engine=PaperEngine(path)
            identity=engine.create(CONFIG)['id'];engine.control(identity,'start')
            engine.ingest(identity,bars()[:20],True)
            original=engine.save
            def interrupted(db,state,event):
                original(db,state,event)
                if event['type']=='fill':raise sqlite3.OperationalError('simulated disk failure')
            with patch.object(engine,'save',side_effect=interrupted),self.assertRaises(sqlite3.OperationalError):
                engine.ingest(identity,bars()[20:21],True)
            recovered=PaperEngine(path)
            self.assertEqual(recovered.reconcile(identity)['fills'],0)
            self.assertEqual(recovered.status()['accounts'][0]['pending']['side'],'BUY')
            recovered.control(identity,'start')
            recovered.ingest(identity,bars()[20:21],True)
            self.assertEqual(recovered.reconcile(identity)['fills'],1)

    def test_imported_marks_and_realized_drift_block_next_update(self):
        with tempfile.TemporaryDirectory() as directory:
            engine=PaperEngine(Path(directory)/'paper.sqlite')
            identity=engine.create(CONFIG)['id']
            engine.control(identity,'start')
            engine.ingest(identity,bars()[:21],True)
            with engine.db() as db:
                state=engine.load(db,identity)
                for key in ('equity','realized','basis'): state[key]+=500
                db.execute('UPDATE accounts SET body=? WHERE id=?',(json.dumps(state),identity))
            self.assertEqual(set(engine.reconcile(identity)['mismatches']),{'equity','realized','basis'})
            with self.assertRaisesRegex(ValueError,'ledger mismatch'):engine.ingest(identity,bars()[21:22],True)

    def test_row_identity_mismatch_rolls_back_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            engine=PaperEngine(Path(directory)/'paper.sqlite')
            identity=engine.create(CONFIG)['id']
            engine.control(identity,'start')
            for change in [dict(symbol='OTHER'),dict(exchange='BSE'),dict(instrument_token=123)]:
                with self.assertRaises(ValueError):engine.ingest(identity,[bars()[0],bars()[1]|change],True)
                self.assertIsNone(engine.status()['accounts'][0]['lastBar'])

    def test_old_trade_with_new_receipt_is_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            market=MarketData('',Path(directory))
            now=dt.datetime.now(dt.timezone.utc)
            market.stream_owner='fixture'
            market.stream_state=dict(state='connected',points=[],lastTick=now.isoformat(),exchangeTimestamp=now.isoformat(),tradeTimestamp=now.isoformat())
            self.assertTrue(market.stream_status('fixture')['freshTrade'])
            for value in [None,(now-dt.timedelta(hours=1)).isoformat(),(now+dt.timedelta(hours=1)).isoformat()]:
                market.stream_state['tradeTimestamp']=value
                self.assertFalse(market.stream_status('fixture')['freshTrade'])
