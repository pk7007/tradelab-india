import datetime as dt
import unittest
from research import rank_universe, chronological_splits, ResearchRiskGate, experiment_record


def candles(step=1, n=25):
    return [{'date':(dt.datetime(2026,10,1,tzinfo=dt.timezone.utc)+dt.timedelta(days=i)).isoformat(),
             'open':100+i*step,'high':101+i*step,'low':99+i*step,'close':100+i*step,'volume':1000} for i in range(n)]


class RankingTests(unittest.TestCase):
    def rank(self, rows):
        return rank_universe({'TEST':rows},'swing','day','2026-10-26T18:00:00+05:30')

    def test_positive_rank_has_exact_contribution(self):
        item=self.rank(candles())['candidates'][0]
        self.assertAlmostEqual(item['score'],(124/104-1)*100)
        self.assertEqual(item['score'],item['contributions']['20BarMomentum'])

    def test_decline_produces_no_candidate(self):
        self.assertEqual(self.rank(candles(-1))['status'],'no qualifying candidates')

    def test_future_information_does_not_change_rank(self):
        rows=candles(); future=dict(rows[-1],date='2027-01-01T00:00:00+05:30',close=1000,high=1001)
        self.assertEqual(self.rank(rows)['candidates'],self.rank(rows+[future])['candidates'])

    def test_duplicate_and_out_of_order_rejected(self):
        rows=candles()
        for bad in [rows+[rows[-1]],list(reversed(rows))]:
            self.assertFalse(self.rank(bad)['candidates'])

    def test_bad_prices_and_zero_volume_rejected(self):
        for field,value in [('close',float('nan')),('volume',0),('low',999)]:
            rows=candles();rows[-1][field]=value
            self.assertFalse(self.rank(rows)['candidates'])

    def test_stale_daily_rejected(self):
        result=rank_universe({'TEST':candles()},'swing','day','2026-11-20T00:00:00Z')
        self.assertFalse(result['candidates'])

    def test_long_term_is_blocked_without_fundamentals(self):
        self.assertEqual(rank_universe({},'long-term','day','2026-10-26T00:00:00Z')['status'],'insufficient evidence')

    def test_intraday_requires_complete_contiguous_session(self):
        rows=candles()
        start=dt.datetime.fromisoformat('2026-10-26T09:15:00+05:30')
        for i,r in enumerate(rows):r['date']=(start+dt.timedelta(minutes=5*i)).isoformat()
        cutoff=(start+dt.timedelta(minutes=125)).isoformat()
        self.assertTrue(rank_universe({'TEST':rows},'intraday','5minute',cutoff)['candidates'])
        del rows[-3]
        self.assertFalse(rank_universe({'TEST':rows},'intraday','5minute',cutoff)['candidates'])

    def test_purge_prevents_label_overlap(self):
        splits=chronological_splits(200,5)
        self.assertTrue(splits)
        for fold in splits:self.assertLess(fold['train'][1]-1+5,fold['test'][0])

    def test_ranking_job_owner_and_completion_gate(self):
        from market_data import MarketData
        market=MarketData('fixture','unused')
        market.jobs['x']={'owner':'a','state':'running','rows':{},'interval':'day','cancel':False}
        for owner in ['a','b']:
            with self.assertRaises(ValueError):market.rank(owner,'x','swing','2026-10-26T00:00:00Z')
        market.jobs['x'].update(state='complete',rows={'TEST':candles()})
        self.assertTrue(market.rank('a','x','swing','2026-10-26T18:00:00+05:30')['candidates'])

    def test_experiment_hash_changes_with_data(self):
        a=experiment_record({},candles(),{})
        b=experiment_record({},candles(-1),{})
        self.assertNotEqual(a['datasetHash'],b['datasetHash'])
        self.assertFalse(a['holdoutIndependent'])


class RiskContractTests(unittest.TestCase):
    def setUp(self):
        self.gate=ResearchRiskGate()
        self.args=dict(fresh=True,reconciled=True,exposure=20,pending=10,added=10,exposure_limit=50,daily_loss=0,loss_limit=5)

    def test_restart_disarms(self):
        self.assertFalse(self.gate.check('a',**self.args)[0])

    def test_duplicate_rejected(self):
        self.gate.armed=True
        self.assertTrue(self.gate.check('a',**self.args)[0])
        self.assertFalse(self.gate.check('a',**self.args)[0])

    def test_stale_unreconciled_pending_and_daily_loss_gates(self):
        self.gate.armed=True
        for changes in [dict(fresh=False),dict(reconciled=False),dict(pending=30),dict(daily_loss=5),dict(added=float('nan'))]:
            self.assertFalse(self.gate.check('a',**(self.args|changes))[0])

    def test_unknown_acceptance_blocks_resubmit(self):
        self.gate.armed=True;self.gate.uncertain.add('timeout-order')
        self.assertFalse(self.gate.check('new-signal',**self.args)[0])

    def test_kill_does_not_claim_closed_positions(self):
        self.gate.armed=True
        result=self.gate.kill(['pending1'])
        self.assertFalse(result['positionsClosed'])
        self.assertEqual(result['cancelRequests'],['pending1'])
        self.assertFalse(self.gate.check('a',**self.args)[0])

if __name__=='__main__': unittest.main()
