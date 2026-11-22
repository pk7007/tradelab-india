"""Real local HTTP entry points with an isolated ledger and controlled broker data."""
import ast
import hashlib
import hmac
import http.client
import http.server
import json
import math
import os
import secrets
import sqlite3
import threading
import time
import unittest
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_auto_selector
from intraday_session import session_snapshot
from operational_alerts import OperationalAlerts
from operations import Operations


class IntradayHTTPTests(unittest.TestCase):
    def setUp(self):
        fixture = test_auto_selector.SelectionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.template = fixture.engine.create(fixture.config)['id']
        alerts = OperationalAlerts(fixture.engine.path.parent / 'alerts.sqlite')
        operations = Operations([fixture.engine.path, alerts.path], fixture.engine.path.parent,
                                paper_engine=fixture.engine, alerts=alerts)
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'app.py').read_text())
        self.broker_order = Mock(side_effect=AssertionError('Paper must never submit broker orders'))
        namespace = dict(Any=object, http=SimpleNamespace(server=http.server),
            hashlib=hashlib, hmac=hmac, math=math, json=json, os=os,
            secrets=secrets, sqlite3=sqlite3, threading=threading, time=time,
            urllib=SimpleNamespace(parse=urllib.parse), ROOT=root, WEB=root/'web',
            SESSIONS={'fixture':dict(fixture.session, csrf='fixture-csrf')},
            LOCK=threading.RLock(), SESSION_IDLE_SECONDS=1800, MAX_SESSIONS=128,
            AUTO_SELECTOR=fixture.selector, PAPER=fixture.engine, ALERTS=alerts, OPERATIONS=operations,
            PAPER_WORKER=SimpleNamespace(status=lambda:dict(enabled=False)),
            PORTAL=SimpleNamespace(status=lambda:dict(settings=fixture.config)),
            NEWS_AGENT=SimpleNamespace(status=lambda *args:dict(status='fixture',stale=False,sources=[])),
            MARKET=fixture.market, DESK=SimpleNamespace(status=lambda:dict(state='fixture')),
            AGENTS=SimpleNamespace(status=lambda:dict(state='fixture')),
            session_snapshot=session_snapshot, TOOLS={}, kite_request=self.broker_order)
        names = {'Handler', 'automatic_selection_status'}
        exec(compile(ast.Module(body=[n for n in tree.body
            if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names],
            type_ignores=[]), 'app.py', 'exec'), namespace)
        self.namespace = namespace
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), namespace['Handler'])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.fixture.selector.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, body=None, *, csrf=True):
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        headers = {'Cookie':'tradelab_session=fixture', 'Content-Type':'application/json'}
        if csrf:
            headers['X-CSRF-Token'] = 'fixture-csrf'
        client.request('GET' if body is None else 'POST', path,
                       None if body is None else json.dumps(body), headers)
        response = client.getresponse()
        raw = response.read().decode()
        status = response.status
        client.close()
        return status, json.loads(raw) if response.getheader('Content-Type','').startswith('application/json') else raw

    def start(self):
        # Disable only selector background scheduling. HTTP requests still use real threads.
        with patch.dict(os.environ, KITE_DATA_STORAGE_APPROVED='true'), patch(
                'auto_selector.threading', SimpleNamespace(Thread=Mock())):
            return self.request('/api/auto-selection/start', dict(
                templateAccount=self.template, permitted=True, calendar=self.fixture.calendar))

    def test_start_pause_end_and_report_via_real_http(self):
        status, page = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn('Auto Trading', page)
        self.assertEqual(self.start()[0], 200)
        self.assertEqual(self.start()[0], 200)
        f = self.fixture
        f.selector.tick()
        f.selector.tick()
        f.advance(10)
        identity = f.selector.worker.account
        self.assertNotEqual(identity, self.template)
        status, paused = self.request('/api/auto-selection/control', {'action':'pause_entries'})
        self.assertEqual(status, 200)
        self.assertTrue(paused['entriesPaused'])
        self.assertTrue(paused['enabled'])
        status, ending = self.request('/api/auto-selection/control', {'action':'end_session'})
        self.assertEqual(status, 200)
        self.assertEqual(ending['closureState'], 'unresolved-exposure')
        f.advance(5)
        status, summary = self.request('/api/intraday-session')
        self.assertEqual(status, 200)
        self.assertTrue(summary['report']['final'])
        self.assertEqual(summary['report']['quantity'], 0)
        self.assertEqual(summary['report']['fillCount'], 2)
        self.assertTrue(summary['report']['trace']['receipts'])
        self.assertEqual(summary['report']['trace']['selection']['strategyVersion'], 'intraday-v1')
        fills = summary['report']['trace']['fills']
        buy, sell = fills
        expected = f.config['capital'] - buy['quantity']*buy['price'] - buy['fee']
        expected += sell['quantity']*sell['price'] - sell['fee']
        self.assertAlmostEqual(summary['report']['cash'], expected)
        # Reload-style GET cannot reopen or fund another account.
        self.assertEqual(self.request('/api/intraday-session')[1]['account']['id'], identity)
        self.assertEqual(len(f.engine.status()['accounts']), 2)
        self.broker_order.assert_not_called()

    def test_csrf_manual_bypass_and_optional_news_outage(self):
        status, _ = self.request('/api/auto-selection/control', {'action':'end_session'}, csrf=False)
        self.assertEqual(status, 403)
        self.start()
        self.fixture.selector.tick()
        identity = self.fixture.selector.worker.account
        for action, body in [('paper-control', dict(action='stop')),
                             ('paper-bars', dict(bars=[], permitted=True))]:
            status, _ = self.request('/api/trader/'+action, dict(id=identity, **body))
            self.assertEqual(status, 400)
        self.namespace['NEWS_AGENT'] = SimpleNamespace(status=Mock(side_effect=OSError('private')))
        status, result = self.request('/api/intraday-session')
        self.assertEqual(status, 200)
        self.assertEqual(result['news']['status'], 'unavailable')
        self.assertNotIn('private', json.dumps(result))
        self.broker_order.assert_not_called()

    def test_no_qualifying_candidate_remains_cash_then_ends(self):
        self.fixture.rows = [dict(row, volume=0) for row in self.fixture.rows]
        self.start()
        self.fixture.selector.tick()
        status, result = self.request('/api/intraday-session')
        self.assertEqual(status, 200)
        self.assertEqual(result['selection']['state'], 'no-qualifying-candidate')
        self.assertEqual(result['report']['fillCount'], 0)
        self.assertFalse(result['report']['final'])
        status, ended = self.request('/api/auto-selection/control', {'action':'end_session'})
        self.assertEqual(status, 200)
        self.assertEqual(ended['state'], 'reconciled-flat')
        result = self.request('/api/intraday-session')[1]
        self.assertTrue(result['report']['final'])
        self.assertEqual(result['report']['totalPnl'], 0)
        self.assertFalse(result['readiness']['canRequestStart'])
        self.assertEqual(len(self.fixture.engine.status()['accounts']), 1)
        self.broker_order.assert_not_called()

    def test_scheduled_start_uses_saved_permissions_and_reviewed_calendar(self):
        f = self.fixture
        # The local supervisor uses the same authenticated Start route as the
        # browser. Simulate its two deliveries without starting a real clock.
        self.namespace['automatic_selection_status'] = lambda: dict(f.selector.status(), calendar=f.calendar)
        payload = dict(templateAccount=self.template)
        with patch.dict(os.environ, KITE_DATA_STORAGE_APPROVED='false'):
            self.assertEqual(self.request('/api/auto-selection/start', payload)[0], 400)
        with patch.dict(os.environ, KITE_DATA_STORAGE_APPROVED='true'), patch(
                'auto_selector.threading', SimpleNamespace(Thread=Mock())):
            for _ in range(2):
                self.assertEqual(self.request('/api/auto-selection/start', payload)[0], 200)
        f.selector.tick()
        f.selector.tick()
        f.advance(15)
        report = self.request('/api/intraday-session')[1]['report']
        self.assertEqual(report['fillCount'], 1)
        self.assertTrue(report['quantity'] > 0)
        self.assertEqual(len(f.engine.status()['accounts']), 2)
        self.broker_order.assert_not_called()
