import copy
import datetime as dt
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from auto_selector import AutoSelector, rank_candidates
from paper import PaperEngine
from test_intraday_paper import CONFIG, bars


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.sleep=patch('auto_selector.time', SimpleNamespace(**dict(vars(time), sleep=lambda *_: None)))
        self.sleep.start()
        self.addCleanup(self.sleep.stop)
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine=PaperEngine(Path(self.temp.name)/'paper.sqlite')
        self.now=dt.datetime.fromisoformat('2026-01-02T11:00:00+05:30')
        self.config=dict(CONFIG,source='imported',squareOff='15:05')
        self.calendar=dict(exchange='NSE',segment='EQ',version='fixture',source='https://example.invalid/calendar',
            availableAt='2026-01-01T00:00:00+05:30',sessions={'2026-01-02':dict(
                open='2026-01-02T09:15:00+05:30',close='2026-01-02T15:15:00+05:30')})
        master=[dict(tradingsymbol='DEMO',instrument_token=123,instrument_type='EQ',segment='NSE',exchange='NSE')]
        self.rows=bars(30)
        client=SimpleNamespace(quote=lambda _: {'NSE:DEMO':dict(last_price=102,volume=10000,timestamp=self.now)},
            historical_data=lambda token,start,end,*args,**kwargs:[
                dict(r,date=dt.datetime.fromisoformat(r['date'])) for r in self.rows
                if start<=dt.datetime.fromisoformat(r['date'])<=end])
        self.market=SimpleNamespace(master=master,instruments=lambda *_:master,
            resolve=lambda *_:dict(instrument_token=123,exchange='NSE'),
            rate_lock=threading.Lock(),last_request=0,client=lambda _:client)
        self.selector=AutoSelector(self.engine,self.market,clock=lambda:self.now)
        self.session=dict(access_token='fixture',profile={'user_id':'fixture'},last_seen=time.monotonic())

    def start(self):
        with patch('auto_selector.threading.Thread'):
            self.selector.start(self.session,self.config,self.calendar)

    def advance(self, minutes):
        for _ in range(minutes*2):
            self.now+=dt.timedelta(seconds=30)
            self.selector.tick()

    def test_normal_start_discovery_selection_and_forward_fill_once(self):
        self.start()
        self.selector.tick()
        selected=self.selector.status()
        self.assertEqual(selected['symbol'],'DEMO')
        identity=selected['accountId']
        self.selector.tick()
        with self.engine.db() as db:
            self.assertEqual(self.engine.load(db,identity)['quantity'],0)
        self.advance(10)
        first=self.engine.reconcile(identity)
        self.selector.tick()
        self.assertEqual(first,self.engine.reconcile(identity))
        self.assertTrue(first['matches'])
        self.assertGreater(first['quantity'],0)
        self.assertLess(first['cash'],self.config['capital'])
        self.selector.stop()
        self.assertFalse(self.selector.status()['enabled'])

    def test_ranking_rejects_gaps_stale_zero_volume_and_unaffordable(self):
        good=bars(21)
        variants=[good[1:],good[:10]+good[11:],good[:-1],
                  [dict(r,volume=0) for r in good]]
        for rows in variants:
            candidates,_=rank_candidates({'DEMO':rows},self.config,self.calendar,self.now.isoformat())
            self.assertEqual(candidates,[])
        self.assertEqual(len(rank_candidates({'DEMO':good},self.config,self.calendar,self.now.isoformat())[0]),1)
        self.assertEqual(rank_candidates({'DEMO':good},dict(self.config,capital=1,maxExposure=1),
                                         self.calendar,self.now.isoformat())[0],[])

    def test_reservation_recovers_idempotently_without_duplicate_account(self):
        self.start()
        self.selector.allocate('2026-01-02',dict(exchange='NSE',symbol='DEMO',token=123))
        identity=self.selector.worker.account
        self.selector.stop()
        self.selector=AutoSelector(self.engine,self.market,clock=lambda:self.now)
        self.start()
        self.selector.tick()
        self.assertEqual(self.selector.worker.account,identity)
        self.assertEqual(len(self.engine.status()['accounts']),1)
        self.selector.stop()

    def test_closed_late_or_single_symbol_calendar_and_exposure_block(self):
        for calendar in (dict(self.calendar,symbol='INFY'),
                         dict(self.calendar,sessions={'2026-01-02':None})):
            with self.assertRaises(ValueError):
                self.selector.start(self.session,self.config,calendar)
        self.now=self.now.replace(hour=14,minute=30)
        with self.assertRaises(ValueError):
            self.start()

    def test_stop_prevents_allocation_and_config_identity_is_immutable(self):
        self.start()
        self.selector.stop()
        with self.assertRaises(ValueError):
            self.selector.allocate('2026-01-02',dict(exchange='NSE',symbol='DEMO',token=123))
        first=self.engine.create(self.config,identity='stable')
        self.assertEqual(self.engine.create(self.config,identity='stable')['id'],first['id'])
        with self.assertRaises(ValueError):
            self.engine.create(dict(self.config,capital=999),identity='stable')

    def test_standing_grant_and_persistent_preselection_pause(self):
        self.start()
        with self.assertRaises(PermissionError):
            self.selector.start(dict(self.session, access_token='another-user'), self.config, self.calendar)
        self.session['last_seen'] -= 2000
        self.selector.check_login()
        self.selector.control('pause_entries')
        self.selector.stop()
        self.selector=AutoSelector(self.engine,self.market,clock=lambda:self.now)
        self.session['last_seen']=time.monotonic()
        self.start()
        self.selector.tick()
        self.assertEqual(self.selector.status()['state'],'entries-paused')
        self.assertIsNone(self.selector.worker.account)
        self.selector.control('resume_entries')
        self.selector.tick()
        self.assertIsNotNone(self.selector.worker.account)
        self.selector.stop()
        with self.assertRaises(PermissionError):
            self.selector.check_login()

    def test_invalid_entry_reviewer_cannot_roll_back_protective_exit(self):
        self.start()
        self.selector.tick()
        self.selector.tick()
        self.advance(10)
        identity=self.selector.worker.account
        self.assertGreater(self.engine.reconcile(identity)['quantity'],0)
        # This bar crosses the stop but closes back on trend, triggering a
        # fresh entry review in the same transaction as the protective SELL.
        self.rows[23]=dict(self.rows[23],low=90)
        from types import SimpleNamespace
        self.engine.entry_reviewer=SimpleNamespace(review=lambda _:dict(
            status='eligible',maxQuantity=1,reason=object(),reviewers=[]))
        self.advance(5)
        with self.engine.db() as db:
            account=self.engine.load(db,identity)
            self.assertEqual(account['quantity'],0)
            self.assertIsNone(account['pending'])
            rejected=db.execute("SELECT body FROM entry_reviews WHERE state='rejected' AND account=?",
                                (identity,)).fetchall()
            self.assertTrue(any('temporarily-blocked' in row[0] for row in rejected))
        self.assertTrue(self.engine.reconcile(identity)['matches'])

    def test_crash_after_consumption_rolls_back_approval_and_fill_together(self):
        self.start()
        self.selector.tick()
        self.selector.tick()
        self.advance(5)
        identity=self.selector.worker.account
        # Keep the worker lease alive up to the next completed bar.
        self.advance(4)
        self.now+=dt.timedelta(minutes=1)
        save=self.engine.save
        def interrupted(db,state,event):
            if event['type']=='fill':
                raise RuntimeError('fixture process interruption before commit')
            return save(db,state,event)
        with patch.object(self.engine,'save',side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.selector.tick()
        with self.engine.db() as db:
            self.assertEqual(self.engine.load(db,identity)['quantity'],0)
            self.assertEqual(db.execute('SELECT state FROM entry_reviews WHERE account=?',(identity,)).fetchone()[0],'eligible')
        self.selector.tick()
        self.selector.tick()
        self.assertEqual(self.engine.reconcile(identity)['fills'],1)

    def test_review_timeout_blocks_buy_and_leaves_session_running(self):
        from entry_review import EntryReviewer
        release=threading.Event()
        self.addCleanup(release.set)
        self.engine.entry_reviewer=EntryReviewer(lambda evidence:release.wait(2),timeout=.01)
        self.start()
        self.selector.tick()
        self.selector.tick()
        self.advance(10)
        with self.engine.db() as db:
            account=self.engine.load(db,self.selector.worker.account)
            self.assertIsNone(account['pending'])
            self.assertEqual(account['quantity'],0)
            self.assertTrue(db.execute("SELECT 1 FROM entry_reviews WHERE state='rejected'").fetchone())
        self.assertTrue(self.selector.enabled)

    def test_expired_review_cannot_buy_even_if_price_still_qualifies(self):
        self.start()
        self.selector.tick()
        self.selector.tick()
        self.advance(5)
        with self.engine.db() as db:
            db.execute("UPDATE entry_reviews SET body=json_set(body,'$.expiresAt',?) WHERE state='eligible'",
                       (self.now.isoformat(),))
        self.advance(5)
        with self.engine.db() as db:
            self.assertTrue(db.execute("SELECT 1 FROM entry_reviews WHERE state='invalidated'").fetchone())
        self.assertEqual(self.engine.reconcile(self.selector.worker.account)['fills'],0)

    def test_recover_reserved_account_after_creation_failure(self):
        self.start()
        with patch.object(self.engine,'create',side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                self.selector.allocate('2026-01-02',dict(exchange='NSE',symbol='DEMO',token=123))
        self.selector.stop()
        self.selector=AutoSelector(self.engine,self.market,clock=lambda:self.now)
        self.start()
        self.selector.tick()
        self.assertEqual(len(self.engine.status()['accounts']),1)
        self.assertEqual(self.selector.status()['symbol'],'DEMO')
        self.selector.stop()

    def test_losing_allocation_carries_cash_forward(self):
        self.start()
        self.selector.tick()
        identity=self.selector.worker.account
        # An actual round trip supplies fees and realized losses to the funding carry.
        self.selector.tick()
        self.advance(10)
        self.engine.control(identity,'close_position')
        self.rows[23]=dict(self.rows[23],open=100,low=99,high=103,close=100)
        self.advance(5)
        self.selector.stop()
        previous=self.engine.reconcile(identity)
        self.assertEqual(previous['quantity'],0)
        self.assertLess(previous['cash'],self.config['capital'])
        self.selector.enabled=True
        self.selector.shutdown.clear()
        with patch.object(self.selector,'attach'):
            self.selector.allocate('2026-01-05',dict(exchange='NSE',symbol='DEMO',token=123))
        accounts=self.engine.status()['accounts']
        newer=next(a for a in accounts if a['id']!=identity)
        self.assertEqual(newer['config']['capital'],min(previous['cash'],self.config['capital']))

    def test_pause_new_entries_keeps_processing_and_end_closes_and_reconciles(self):
        self.start()
        self.selector.tick()
        self.selector.tick()
        self.advance(10)
        identity=self.selector.worker.account
        before=self.engine.reconcile(identity)
        self.assertGreater(before['quantity'],0)
        paused=self.selector.control('pause_entries')
        self.assertTrue(paused['enabled'])
        self.assertTrue(paused['entriesPaused'])
        self.assertTrue(self.selector.worker.status()['enabled'])
        ending=self.selector.control('end_session')
        self.assertEqual(ending['closureState'],'unresolved-exposure')
        self.assertEqual(ending['balance']['pending']['side'],'SELL')
        self.assertTrue(ending['enabled'])
        with self.assertRaises(ValueError):
            self.selector.control('resume_entries')
        # Independent cash oracle for the next modeled open, including both
        # the already-booked buy basis and the configured sell slip and fee.
        raw=self.rows[23]['open']
        units=before['quantity']
        price=raw*(1-self.config['slippageBps']/10000)
        fee=units*price*self.config['costBps']/10000
        expected_cash=before['cash']+units*price-fee
        self.advance(5)
        ended=self.selector.status()
        self.assertFalse(ended['enabled'])
        self.assertEqual(ended['state'],'reconciled-flat')
        self.assertEqual(ended['balance']['quantity'],0)
        self.assertAlmostEqual(ended['balance']['cash'],expected_cash)
        self.assertTrue(self.engine.reconcile(identity)['matches'])
        fresh=AutoSelector(self.engine,self.market,clock=lambda:self.now).status()
        self.assertEqual(fresh['accountId'],identity)
        self.assertTrue(fresh['endRequested'])
        self.assertEqual(fresh['selectionTrace']['strategyVersion'],'intraday-v1')

    def test_end_with_missing_liquidity_retains_exposure_and_pending_exit(self):
        self.start()
        self.selector.tick()
        self.selector.tick()
        self.advance(10)
        self.selector.control('end_session')
        self.rows[23]=dict(self.rows[23],volume=0)
        self.advance(5)
        state=self.selector.status()
        self.assertEqual(state['closureState'],'unresolved-exposure')
        self.assertGreater(state['balance']['quantity'],0)
        self.assertEqual(state['balance']['pending']['side'],'SELL')
        self.assertTrue(state['enabled'])
        self.selector.stop()
        state=self.selector.status()
        self.assertEqual(state['closureState'],'unresolved-exposure')
        self.assertIn('Exposure',state['reason'])

    def test_pause_before_selection_and_end_no_trade(self):
        self.start()
        self.selector.control('pause_entries')
        self.selector.tick()
        self.assertIsNone(self.selector.worker.account)
        self.assertEqual(len(self.engine.status()['accounts']),0)
        ended=self.selector.control('end_session')
        self.assertFalse(ended['enabled'])
        self.assertEqual(ended['state'],'reconciled-flat')

    def test_saved_exposure_can_recover_after_entry_cutoff_and_close(self):
        self.start()
        self.selector.tick()
        self.selector.tick()
        self.advance(10)
        identity=self.selector.worker.account
        self.selector.stop()
        self.now=self.now.replace(hour=15,minute=20)
        self.rows=bars(72)
        self.selector=AutoSelector(self.engine,self.market,clock=lambda:self.now)
        self.start()
        self.selector.tick()
        state=self.selector.status()
        self.assertEqual(state['accountId'],identity)
        self.assertTrue(state['entriesPaused'])
        self.assertTrue(state['endRequested'])
        self.selector.tick()
        self.assertEqual(self.selector.status()['closureState'],'reconciled-flat')
        self.assertFalse(self.selector.status()['enabled'])

    def test_new_manual_exit_cannot_fill_before_request_time(self):
        self.start()
        self.selector.tick()
        self.selector.tick()
        self.advance(10)
        self.advance(2)
        self.selector.control('end_session')
        self.advance(3)
        state=self.selector.status()
        self.assertGreater(state['balance']['quantity'],0)
        self.assertEqual(state['balance']['pending']['requestedAt'],'2026-01-02T11:12:00+05:30')
        self.advance(5)
        self.assertEqual(self.selector.status()['closureState'],'reconciled-flat')

    def test_recovery_end_does_not_backdate_new_exit_into_missed_candles(self):
        self.config['targetMultiple']=20
        self.start()
        self.selector.tick()
        self.selector.tick()
        self.advance(10)
        self.selector.stop()
        self.now=self.now.replace(hour=14,minute=35)
        self.rows=bars(65)
        self.selector=AutoSelector(self.engine,self.market,clock=lambda:self.now)
        self.start()
        self.selector.tick()
        self.selector.tick()
        self.assertGreater(self.selector.status()['balance']['quantity'],0)
        self.advance(5)
        self.assertEqual(self.selector.status()['closureState'],'reconciled-flat')

    def test_news_failure_cannot_block_protective_candle_transport(self):
        self.start()
        self.selector.announcements=SimpleNamespace(status=lambda *_: (_ for _ in ()).throw(OSError('fixture')))
        self.selector.tick()
        self.selector.tick()
        self.advance(10)
        state=self.selector.status()
        self.assertGreater(state['balance']['quantity'],0)
        self.assertEqual(state['newsContext']['status'],'unavailable')
        self.selector.control('end_session')
        self.advance(5)
        self.assertEqual(self.selector.status()['closureState'],'reconciled-flat')

    def test_restart_with_selected_account_preserves_original_template(self):
        self.config['symbol']='ORIGINAL'
        self.start()
        self.selector.tick()
        identity=self.selector.worker.account
        self.selector.stop()
        with self.engine.db() as db:
            managed=self.engine.load(db,identity)['config']
        self.assertEqual(managed['symbol'],'DEMO')
        self.selector=AutoSelector(self.engine,self.market,clock=lambda:self.now)
        with patch('auto_selector.threading.Thread'):
            self.selector.start(self.session,managed,self.calendar)
        self.selector.tick()
        self.assertEqual(self.selector.worker.account,identity)
        self.assertEqual(self.selector.config['symbol'],'ORIGINAL')
        self.assertEqual(len(self.engine.status()['accounts']),1)
        self.selector.stop()

    def test_no_qualifying_session_preserves_scan_without_funding_account(self):
        self.rows=[dict(r,open=100,high=101,low=99,close=100) for r in self.rows]
        self.start()
        self.selector.tick()
        state=self.selector.status()
        self.assertEqual(state['state'],'no-qualifying-candidate')
        self.assertEqual(state['candidates'],[])
        self.assertEqual(state['excluded'][0]['reason'],'Shared SMA condition is false.')
        self.assertEqual(len(self.engine.status()['accounts']),0)
        ended=self.selector.control('end_session')
        self.assertFalse(ended['enabled'])
        recovered=AutoSelector(self.engine,self.market,clock=lambda:self.now).status()
        self.assertEqual(recovered['lastScan']['examinedSymbols'],['DEMO'])
        self.assertEqual(recovered['lastScan']['candleChecks'],1)
        self.assertTrue(recovered['noTradeReport']['final'])
        self.assertEqual(recovered['noTradeReport']['day'],'2026-01-02')
        self.assertEqual(recovered['noTradeReport']['config'],self.config)
        self.assertEqual(recovered['noTradeReport']['openingCash'],self.config['capital'])
        self.assertEqual(recovered['noTradeReport']['closingCash'],self.config['capital'])
        self.assertEqual(recovered['noTradeReport']['netResult'],0)
        self.assertEqual(recovered['noTradeReport']['fills'],0)
        self.assertNotIn('accountId',recovered)

    def test_recovery_control_before_first_tick_preserves_protective_processing(self):
        self.start()
        self.selector.tick()
        self.selector.tick()
        self.advance(10)
        identity=self.selector.worker.account
        self.selector.stop()
        self.selector=AutoSelector(self.engine,self.market,clock=lambda:self.now)
        self.start()
        self.assertEqual(self.selector.worker.account,identity)
        self.selector.control('pause_entries')
        self.assertTrue(self.selector.worker.status()['enabled'])
        ending=self.selector.control('end_session')
        self.assertEqual(ending['closureState'],'unresolved-exposure')
        self.assertEqual(ending['balance']['pending']['side'],'SELL')
        self.assertTrue(ending['enabled'])
        self.advance(5)
        self.assertEqual(self.selector.status()['closureState'],'reconciled-flat')

    def test_next_day_recovery_uses_existing_funding_and_explicit_calendar(self):
        self.start()
        self.selector.tick()
        self.selector.tick()
        self.advance(10)
        identity=self.selector.worker.account
        self.selector.stop()
        self.now=dt.datetime.fromisoformat('2026-01-05T09:20:00+05:30')
        self.calendar=copy.deepcopy(self.calendar)
        self.calendar['sessions'].update({'2026-01-03':None,'2026-01-04':None,
            '2026-01-05':dict(open='2026-01-05T09:15:00+05:30',close='2026-01-05T15:15:00+05:30')})
        self.selector=AutoSelector(self.engine,self.market,clock=lambda:self.now)
        self.start()
        state=self.selector.status()
        self.assertEqual(state['accountId'],identity)
        self.assertTrue(state['entriesPaused'])
        self.assertTrue(state['endRequested'])
        self.assertEqual(state['closureState'],'unresolved-exposure')
        self.assertEqual(len(self.engine.status()['accounts']),1)
        # Incomplete history blocks recovery honestly instead of opening a
        # second funded account or inferring a close.
        with self.assertRaises(ValueError):
            self.selector.tick()
        self.assertEqual(self.selector.status()['closureState'],'unresolved-exposure')
        self.assertEqual(len(self.engine.status()['accounts']),1)
        self.selector.stop()

    def test_unfunded_new_day_reports_carried_cash_and_keeps_previous_account_historical(self):
        self.start()
        self.selector.tick()
        self.selector.tick()
        self.advance(10)
        identity=self.selector.worker.account
        self.selector.control('end_session')
        self.rows[23]=dict(self.rows[23],open=100,low=99,high=103,close=100)
        self.advance(5)
        cash=self.engine.reconcile(identity)['cash']
        self.assertLess(cash,self.config['capital'])
        self.now=dt.datetime.fromisoformat('2026-01-05T11:00:00+05:30')
        self.calendar=copy.deepcopy(self.calendar)
        self.calendar['sessions']['2026-01-05']=dict(open='2026-01-05T09:15:00+05:30',close='2026-01-05T15:15:00+05:30')
        self.selector=AutoSelector(self.engine,self.market,clock=lambda:self.now)
        self.start()
        state=self.selector.status()
        self.assertNotIn('accountId',state)
        self.assertEqual(state['previousAccountId'],identity)
        self.assertAlmostEqual(state['noTradeReport']['openingCash'],cash)
        self.selector.control('end_session')
        restarted=AutoSelector(self.engine,self.market,clock=lambda:self.now).status()
        self.assertTrue(restarted['noTradeReport']['final'])
        self.assertAlmostEqual(restarted['noTradeReport']['closingCash'],cash)
