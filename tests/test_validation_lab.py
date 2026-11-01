import unittest
from validation_lab import simulate, stress_suite

class ExecutionTests(unittest.TestCase):
    def bars(self):
        return [dict(open=100+i,close=100+i,high=101+i,low=99+i,volume=10000) for i in range(30)]
    def run_sim(self,bars,**kw):
        return simulate(bars,**(dict(capital=100000,units=10,fee_bps=0,slippage_bps=0,participation=.01,stop_pct=.05)|kw))
    def test_next_bar_signal_and_cash_reconciliation(self):
        bars=self.bars();r=self.run_sim(bars)
        self.assertEqual(r['fills'][0]['bar'],20)
        self.assertAlmostEqual(r['finalEquity'],r['cash']+r['openQuantity']*bars[-1]['close'])
        self.assertEqual(r['cash'],100000-120*10)
    def test_gap_stop_fills_below_stop(self):
        bars=self.bars();bars[21]=dict(open=80,high=82,low=79,close=81,volume=10000)
        r=self.run_sim(bars)
        stop=next(f for f in r['fills'] if f['reason']=='stop')
        self.assertEqual(stop['price'],80)
        self.assertGreater(r['maxDrawdownPct'],0)
    def test_halt_prevents_fills(self):
        bars=self.bars()
        for b in bars:b['halted']=True
        self.assertEqual(self.run_sim(bars)['fills'],[])
    def test_partial_fills_respect_participation(self):
        bars=self.bars()
        for b in bars:b['volume']=100
        r=self.run_sim(bars)
        self.assertTrue(r['fills'])
        self.assertTrue(all(f['quantity']<=1 for f in r['fills']))
    def test_rejection_never_changes_cash(self):
        bars=self.bars()
        for b in bars:b['reject']=True
        r=self.run_sim(bars)
        self.assertEqual(r['cash'],100000)
        self.assertGreater(r['rejectedOrders'],0)
    def test_costs_reduce_equity_for_same_fills(self):
        bars=self.bars()
        self.assertLess(self.run_sim(bars,fee_bps=40)['finalEquity'],self.run_sim(bars)['finalEquity'])
    def test_delay_defers_first_fill(self):
        self.assertEqual(self.run_sim(self.bars(),delay=3)['fills'][0]['bar'],22)
    def test_stress_suite_has_losses_and_all_variants(self):
        r=stress_suite()
        self.assertEqual(len(r['results']),24)
        self.assertTrue(any(x['returnPct']<0 for x in r['results']))
        self.assertFalse(r['liveAutomation'])
