import tempfile
from pathlib import Path
import unittest
from portal import Portal


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'portal.sqlite';self.portal=Portal(self.path)

    def request(self, **extra):
        from datetime import datetime,timedelta
        start=datetime.fromisoformat('2026-01-02T09:15:00+05:30')
        rows=[dict(date=(start+timedelta(minutes=i*5)).isoformat(),open=100,high=101,low=99,close=100,volume=10000) for i in range(4)]
        rows[-1].update(high=103,close=102)
        return dict(horizon='intraday',permitted=True,candles={'DEMO':rows},asOf='2026-01-02T09:35:00+05:30',
                    plans={'DEMO':dict(entry=102,stop=100,target=108,costBps=10,slippageBps=5)},dailyLoss=0,exposure=0,pendingExposure=0,**extra)

    def test_settings_persist_without_changing_paper_accounts(self):
        self.assertEqual(self.portal.status()['settings']['capital'],1000)
        self.portal.update(dict(capital=900,maxLoss=20,dailyLossLimit=90))
        self.assertEqual(Portal(self.path).status()['settings']['maxLoss'],20)
        self.assertFalse(self.portal.status()['liveEnabled'])

    def test_bad_limits_rejected(self):
        for values in (dict(capital=1000,maxLoss=101,dailyLossLimit=100),dict(capital=True,maxLoss=25,dailyLossLimit=100),dict(capital=1000,maxLoss=25,dailyLossLimit=float('nan'))):
            with self.assertRaises(ValueError):self.portal.update(values)

    def test_whole_shares_costed_and_loss_bounded(self):
        item=self.portal.research(self.request())['candidates'][0]
        self.assertEqual(item['plan']['quantity'],9)
        self.assertLessEqual(item['plan']['estimatedCapital'],1000)
        self.assertLessEqual(item['plan']['estimatedStopLoss'],25)
        self.assertFalse(item['autoEligible'])
        self.assertEqual(item['source'],'Imported snapshot')

    def test_daily_loss_and_missing_plan_block(self):
        req=self.request();req['dailyLoss']=100
        self.assertEqual(self.portal.research(req)['candidates'],[])
        req=self.request();req.pop('plans')
        self.assertEqual(self.portal.research(req)['status'],'No qualifying trade')

    def test_stale_or_expensive_candidates_excluded(self):
        req=self.request();req['asOf']='2026-01-02T10:00:00+05:30'
        self.assertEqual(self.portal.research(req)['candidates'],[])

    def test_zero_volume_and_future_news_not_used(self):
        req=self.request();req['candles']['DEMO'][0]['volume']=0
        self.assertEqual(self.portal.research(req)['candidates'],[])
        req=self.request();req['records']=[dict(title='Unavailable news',url='https://example.invalid/future',symbols=['DEMO'],publishedAt='2026-01-02T09:30:00+05:30',availableAt='2026-01-02T10:00:00+05:30')]
        self.assertEqual(self.portal.research(req)['candidates'][0]['news'],[])
        req=self.request();req['plans']['DEMO'].update(entry=1500,stop=1490,target=1600)
        self.assertEqual(self.portal.research(req)['candidates'],[])

    def test_longterm_never_invents_research_or_allocation(self):
        result=self.portal.research(dict(horizon='long-term',watchlist=['INFY','TCS']))
        self.assertEqual(result['status'],'Insufficient evidence')
        self.assertEqual(Portal(self.path).status()['watchlist'],['INFY','TCS'])
        self.assertFalse(result['candidates'][0]['autoPurchase'])

    def test_malformed_symbols_and_missing_snapshot_rejected(self):
        req=self.request();req['candles']={'x'*100:next(iter(req['candles'].values()))}
        with self.assertRaises(ValueError):self.portal.research(req)

    def test_plan_cannot_override_saved_risk_limits(self):
        req=self.request()
        req['plans']['DEMO'].update(budget=100000,maxLoss=999,dailyLossLimit=999,maxExposure=100000,exposure=0)
        result=self.portal.research(req)
        self.assertLessEqual(result['candidates'][0]['plan']['estimatedCapital'],1000)
        self.assertLessEqual(result['candidates'][0]['plan']['estimatedStopLoss'],25)

    def test_duplicate_future_news_does_not_replace_availability_evidence(self):
        req=self.request()
        record=dict(title='Known news',url='https://example.invalid/a',symbols=['DEMO'],publishedAt='2026-01-02T09:20:00+05:30',availableAt='2026-01-02T09:25:00+05:30')
        req['records']=[record,dict(record,availableAt='2026-01-02T10:00:00+05:30')]
        article=self.portal.research(req)['candidates'][0]['news'][0]
        self.assertEqual(article['availableAt'],record['availableAt'])
        self.assertGreaterEqual(article['ageSeconds'],0)
        req=self.request();req.pop('dailyLoss')
        with self.assertRaises(ValueError):self.portal.research(req)
