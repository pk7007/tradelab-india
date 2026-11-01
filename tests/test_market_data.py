"""Offline tests: no API credentials or broker requests are used."""
import datetime as dt
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_data import IST, MarketData, chunks, clean_candles, date_range, simulate_rule, synthetic_research


class HistoricalTests(unittest.TestCase):
    def test_windows_cover_range_once(self):
        start,end=dt.date(2024,1,1),dt.date(2024,4,1)
        days=[]
        for first,last in chunks(start,end):
            self.assertLessEqual((last-first).days,29)
            days.extend(first+dt.timedelta(days=i) for i in range((last-first).days+1))
        self.assertEqual(len(days),len(set(days)))
        self.assertEqual(days[0],start); self.assertEqual(days[-1],end)
        self.assertEqual(len(days),(end-start).days+1)

    def test_invalid_ranges_rejected(self):
        for start,end in [('2024-02-01','2024-01-01'),('2024-01-01','2999-01-01'),('1900-01-01','2024-01-01')]:
            with self.assertRaises(ValueError): date_range(start,end)

    def test_candles_deduplicate_sort_and_validate(self):
        candle={'date':dt.datetime(2024,1,1,tzinfo=IST),'open':100,'high':110,'low':90,'close':105,'volume':20}
        self.assertEqual(len(clean_candles([candle,candle])),1)
        self.assertTrue(clean_candles([candle])[0]['date'].endswith('+05:30'))
        for invalid in [{'low':106},{'high':99},{'volume':-1},{'close':math.nan},{'date':dt.datetime(2024,1,1)}]:
            with self.assertRaises(ValueError): clean_candles([{**candle,**invalid}])

    def test_storage_gate_prevents_network_and_disk(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'KITE_DATA_STORAGE_APPROVED':'false'}):
            market=MarketData('not-a-real-key',folder)
            with patch.object(market,'client',side_effect=AssertionError('Must not fetch')):
                with self.assertRaises(ValueError):
                    market.start_history('owner','no-token',{'symbols':'INFY','from':'2024-01-01','to':'2024-02-01','save':True})
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_jobs_are_private_and_payload_bounded(self):
        market=MarketData('not-a-real-key','unused')
        market.jobs['id']={'owner':'a','rows':{'INFY':[{'date':str(i)} for i in range(600)]},'cancel':False,'state':'complete'}
        with self.assertRaises(ValueError): market.job('b','id','INFY')
        result=market.job('a','id','INFY')
        self.assertEqual(len(result['candles']),500)
        self.assertEqual(result['counts']['INFY'],600)
        self.assertNotIn('owner',result)

    def test_stream_state_not_shared(self):
        market=MarketData('not-a-real-key','unused')
        market.stream_owner='a'; market.stream_state={'state':'connected','points':[{'close':123}], 'lastTick':'now'}
        self.assertEqual(market.stream_status('b')['points'],[])


class StrategyTests(unittest.TestCase):
    def test_signal_executes_on_next_open(self):
        bars=[{'date':str(i),'open':o,'close':c} for i,(o,c) in enumerate([(100,100),(100,100),(100,200),(400,400)])]
        result=simulate_rule(bars,2,3,0,0)
        self.assertEqual(result['fills'],1)
        self.assertEqual(result['openQuantity'],250)  # Next open is 400, not signal close 200.
        self.assertEqual(result['finalEquity'],100000)

    def test_no_future_signal_executes_on_final_bar(self):
        bars=[{'date':str(i),'open':100,'close':c} for i,c in enumerate([100,100,200])]
        result=simulate_rule(bars,2,3,0,0)
        self.assertEqual(result['fills'],0)

    def test_demo_deterministic_and_validates_inputs(self):
        self.assertEqual(synthetic_research({}),synthetic_research({}))
        for values in [{'fast':30,'slow':10},{'costBps':-1},{'slippageBps':float('nan')}]:
            with self.assertRaises(ValueError): synthetic_research(values)


if __name__=='__main__': unittest.main()
