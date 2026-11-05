import datetime as dt
import unittest
from trader_suite import plan,risk_check,scan,time_machine,news,earnings,disclosures,dispatch

PLAN=dict(entry=100,stop=95,target=110,budget=10000,maxLoss=100,costBps=0,slippageBps=0)
RISK=PLAN|dict(exposure=0,pendingExposure=0,maxExposure=10000,dailyLoss=0,dailyLossLimit=1000)
def bars():
    start=dt.datetime.fromisoformat('2026-10-01T09:15:00+05:30')
    return [dict(date=(start+dt.timedelta(minutes=i*5)).isoformat(),open=100+i,high=101+i,low=99+i,close=100+i,volume=1000) for i in range(40)]
class TraderSuiteTests(unittest.TestCase):
    def test_budget_bounds_units_by_risk(self):
        p=plan(PLAN);self.assertEqual(p['quantity'],20);self.assertEqual(p['estimatedStopLoss'],100)
    def test_costs_reduce_quantity(self):self.assertLess(plan(PLAN|dict(costBps=20))['quantity'],20)
    def test_invalid_long_plan_and_nan_rejected(self):
        for change in [dict(stop=101),dict(target=90),dict(budget=float('nan'))]:
            with self.assertRaises(ValueError):plan(PLAN|change)
    def test_pending_exposure_and_daily_loss_block(self):
        self.assertFalse(risk_check(RISK|dict(pendingExposure=9000))['allowed'])
        self.assertFalse(risk_check(RISK|dict(dailyLoss=1000))['allowed'])
    def test_zero_size_cannot_pass_risk(self):self.assertFalse(risk_check(RISK|dict(budget=1))['allowed'])
    def test_scanner_requires_permission(self):
        with self.assertRaises(ValueError):scan(dict(candles={'A':bars()},asOf='2026-10-01T15:30:00+05:30'))
    def test_orb_uses_complete_opening_window(self):
        rows=bars()[:5];rows[-2]['close']=102;rows[-2]['low']=101
        result=scan(dict(candles={'A':rows},asOf='2026-10-01T09:40:00+05:30',permitted=True))
        self.assertIn('opening-range breakout',result['matches'][0]['setups'])
    def test_future_incomplete_bar_excluded(self):
        data=dict(candles={'A':bars()[:4]},asOf='2026-10-01T09:32:00+05:30',permitted=True)
        self.assertEqual(scan(data)['matches'],[])
    def test_time_machine_runs_10000_reproducibly(self):
        data=PLAN|dict(candles={'A':bars()},asOf='2026-10-01T15:30:00+05:30',permitted=True,horizon=5)
        a=time_machine(data);self.assertEqual(a['sessions'],10000);self.assertEqual(a,time_machine(data))
    def test_news_deduplicates_and_matches_exact_symbol(self):
        r=dict(title='Earnings',symbols=['INFY'],url='https://example.invalid/a',publishedAt='2026-10-01T00:00:00Z')
        self.assertEqual(len(news(dict(records=[r,r],watchlist='INFY',asOf='2026-10-01T01:00:00Z',permitted=True))['items']),1)
        self.assertEqual(news(dict(records=[r],watchlist='IN',permitted=True))['items'],[])
    def test_earnings_zero_base_has_no_percentage(self):
        r=dict(metric='Revenue',unit='INR',period='Q2',priorPeriod='Q1',current=100,previous=0,source='https://example.invalid/r',publishedAt='2026-10-01T00:00:00Z')
        self.assertIsNone(earnings(dict(records=[r],permitted=True))['metrics'][0]['changePct'])
    def test_disclosure_preserves_owner_and_lag(self):
        r=dict(filingId='fixture',filer='Synthetic',owner='Spouse',asset='Fixture',transactionDate='2026-09-01',filedAt='2026-10-01T10:00:00Z',amountRange='Test range',source='https://example.invalid/r')
        out=disclosures(dict(records=[r,r],permitted=True))['records'];self.assertEqual(len(out),1);self.assertEqual(out[0]['filingLagDays'],30);self.assertEqual(out[0]['owner'],'Spouse')
    def test_price_alert_boundary(self):self.assertTrue(dispatch('alerts',dict(price=100,threshold=100,direction='above'))['triggered'])

class PaperApprovalTests(unittest.TestCase):
    def test_open_paper_plans_cannot_spend_the_same_loss_allowance_twice(self):
        import secrets,urllib.parse
        from unittest.mock import Mock
        from test_orders import Handler,namespace
        namespace.update(dispatch=dispatch,secrets=secrets,urllib=urllib)
        session={};h=object.__new__(Handler);h.valid_host=lambda:True
        h.authenticated_session=lambda:('fixture',session)
        h.error=Mock();h.json_response=Mock()
        request=RISK|dict(symbol='DEMO',dailyLossLimit=150)
        h.path='/api/trader/broker';h.body_json=lambda:request
        h.do_POST();draft=h.json_response.call_args.args[1]['draftId']
        h.path='/api/trader/approve';h.body_json=lambda:dict(draftId=draft,confirm='APPROVE PAPER ORDER')
        h.do_POST()
        self.assertEqual(session['paper_book'][0]['estimatedStopLoss'],100)
        h.path='/api/trader/broker';h.body_json=lambda:request
        h.do_POST()
        self.assertIn('daily loss',h.error.call_args.args[1])
        self.assertNotIn('paper_draft',session)
    def test_explicit_approval_and_no_replay(self):
        import secrets,urllib.parse
        from unittest.mock import Mock
        from test_orders import Handler,namespace
        namespace.update(dispatch=dispatch,secrets=secrets,urllib=urllib)
        session={};h=object.__new__(Handler);h.valid_host=lambda:True
        h.authenticated_session=lambda:('fixture',session)
        h.error=Mock();h.json_response=Mock()
        h.path='/api/trader/broker';h.body_json=lambda:RISK|dict(symbol='SYNTHETIC')
        h.do_POST();draft=h.json_response.call_args.args[1]['draftId']
        h.path='/api/trader/approve';h.body_json=lambda:dict(draftId=draft,confirm='no')
        h.do_POST();self.assertEqual(h.error.call_args.args[0],400)
        self.assertNotIn('paper_book',session)
        h.body_json=lambda:dict(draftId=draft,confirm='APPROVE PAPER ORDER')
        h.do_POST();self.assertEqual(len(session['paper_book']),1)
        h.do_POST();self.assertEqual(h.error.call_args.args[0],400);self.assertEqual(len(session['paper_book']),1)
    def test_scans_two_thousand_synthetic_symbols(self):
        data=dict(candles={str(i):bars()[:4] for i in range(2000)},asOf='2026-10-01T15:30:00+05:30',permitted=True)
        self.assertEqual(scan(data)['scanned'],2000)
