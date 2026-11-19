import datetime as dt
import tempfile
from pathlib import Path
import unittest
from paper import PaperEngine

CONFIG=dict(symbol='DEMO',provider='Synthetic',adjustment='None',source='synthetic',permitted=True,capital=1000,units=100,maxExposure=1000,dailyLossLimit=100,costBps=10,slippageBps=5,strategy='intraday-v1',maxLoss=25,stopDistancePct=2,targetMultiple=2,entryEnd='14:00',squareOff='15:15',participationPct=10)

def bars(count=23):
    start=dt.datetime.fromisoformat('2026-01-02T09:15:00+05:30')
    return [dict(date=(start+dt.timedelta(minutes=i*5)).isoformat(),open=100+i*.1,high=100.2+i*.1,low=99.9+i*.1,close=100.1+i*.1,volume=10000) for i in range(count)]


class IntradayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'paper.sqlite';self.engine=PaperEngine(self.path)
        self.id=self.engine.create(CONFIG)['id'];self.engine.control(self.id,'start')
    def ingest(self,rows):return self.engine.ingest(self.id,rows,True)['account']
    def test_costed_size_and_protection(self):
        s=self.ingest(bars()[:21]);self.assertEqual(s['quantity'],9)
        self.assertGreaterEqual(s['cash'],0)
        p=s['protection'];per_share=s['basis']/s['quantity']-p['stop']*(1-.0005)*(1-.001)
        self.assertLessEqual(per_share*s['quantity'],25)
        self.assertTrue(self.engine.reconcile(self.id)['matches'])
    def test_both_levels_choose_stop(self):
        s=self.ingest(bars()[:21]);p=s['protection'];row=bars()[21]
        row.update(high=p['target']+1,low=p['stop']-1)
        after=self.ingest([row]);self.assertEqual(after['quantity'],0)
        self.assertLess(after['realized'],0)
        self.assertTrue(self.engine.reconcile(self.id)['matches'])
    def test_gap_stop_exceeds_planned_loss(self):
        self.ingest(bars()[:21]);row=bars()[21];row.update(open=80,high=81,low=79,close=80)
        s=self.ingest([row]);self.assertEqual(s['quantity'],0);self.assertLess(s['realized'],-25)
        self.assertTrue(s['riskHalted'])
    def test_partial_exit_persists_and_entry_pause_preserves_it(self):
        self.ingest(bars()[:21]);self.engine.control(self.id,'close_position')
        row=bars()[21];row['volume']=20
        s=self.ingest([row]);self.assertEqual(s['quantity'],7);self.assertEqual(s['pending']['side'],'SELL')
        self.engine.control(self.id,'pause_entries')
        s=self.ingest(bars()[22:23]);self.assertEqual(s['quantity'],0)
        self.assertTrue(self.engine.reconcile(self.id)['matches'])
    def test_no_liquidity_exit_not_invented(self):
        self.ingest(bars()[:21]);self.engine.control(self.id,'close_position')
        row=bars()[21];row['volume']=1
        s=self.ingest([row]);self.assertEqual(s['quantity'],9);self.assertEqual(s['pending']['side'],'SELL')
    def test_tagged_halt_or_rejection_keeps_exit_pending(self):
        self.ingest(bars()[:21]);self.engine.control(self.id,'close_position')
        for i,flag in [(21,'halted'),(22,'reject')]:
            row=bars()[i];row[flag]=True
            s=self.ingest([row]);self.assertEqual(s['quantity'],9);self.assertEqual(s['pending']['side'],'SELL')
        self.assertTrue(self.engine.reconcile(self.id)['matches'])
    def test_zero_volume_exit_stays_pending(self):
        self.ingest(bars()[:21]);self.engine.control(self.id,'close_position')
        row=bars()[21];row['volume']=0
        s=self.ingest([row]);self.assertEqual(s['quantity'],9);self.assertEqual(s['pending']['side'],'SELL')
    def test_squareoff_requires_observation_and_no_new_entry(self):
        self.id=self.engine.create(CONFIG|{'targetMultiple':20})['id'];self.engine.control(self.id,'start')
        rows=bars(75);s=self.ingest(rows[:72]);self.assertGreater(s['quantity'],0)
        s=self.ingest(rows[72:73]);self.assertEqual(s['lastBar'][11:16],'15:15');self.assertEqual(s['quantity'],0);self.assertIsNone(s['pending'])
    def test_restart_preserves_protection_and_pauses(self):
        before=self.ingest(bars()[:21]);engine=PaperEngine(self.path)
        after=engine.status()['accounts'][0]
        self.assertEqual(after['protection'],before['protection']);self.assertEqual(after['status'],'paused')
    def test_missed_exit_carry_is_visible_and_recovery_clears_only_when_flat(self):
        self.id=self.engine.create(CONFIG|{'targetMultiple':20})['id'];self.engine.control(self.id,'start')
        rows=bars(75)
        for row in rows[72:]:row['volume']=1
        before=self.ingest(rows);self.assertGreater(before['quantity'],0)
        self.assertEqual(before['pending']['side'],'SELL')
        nextrow=dict(date='2026-01-05T09:15:00+05:30',open=80,high=81,low=79,close=80,volume=1)
        carried=self.ingest([nextrow]);self.assertTrue(carried['recoveryRequired']);self.assertTrue(carried['entriesPaused'])
        self.assertEqual(carried['day'],'2026-01-02')
        nextrow.update(date='2026-01-05T09:20:00+05:30',volume=10000)
        closed=self.ingest([nextrow]);self.assertEqual(closed['quantity'],0)
        self.assertFalse(closed['recoveryRequired']);self.assertTrue(closed['entriesPaused'])
        self.assertLess(closed['realized'],-25)
        self.assertTrue(self.engine.reconcile(self.id)['matches'])
    def test_legacy_default_unchanged(self):
        config={k:v for k,v in CONFIG.items() if k not in ('strategy','maxLoss','stopDistancePct','targetMultiple','entryEnd','squareOff','participationPct')}
        legacy=self.engine.create(config)
        self.assertTrue(legacy['config']['overnight']);self.assertEqual(legacy['config']['strategy'],'sma5-20-next-open-paper-v1')
    def test_bad_or_missing_contract_rejected(self):
        for change in ({'squareOff':'14:00'},{'maxLoss':101},{'participationPct':True},{'entryEnd':'14:01'}):
            with self.assertRaises(ValueError):self.engine.create(CONFIG|change)
    def test_evaluation_reuses_identical_paper_fills_and_marks(self):
        from intraday_evaluation import evaluate_intraday
        rows=bars();s=self.ingest(rows)
        result=evaluate_intraday(dict(permitted=True,config=CONFIG,bars=rows))
        self.assertEqual(result['finalEquity'],s['equity'])
        self.assertEqual(result['openQuantity'],s['quantity'])
        self.assertEqual(result['fees'],s['fees'])
        self.assertTrue(result['ledgerMatches']);self.assertFalse(result['promotionAllowed'])
    def test_protection_drift_blocks_ingestion(self):
        self.ingest(bars()[:21])
        with self.engine.db() as db:
            s=self.engine.load(db,self.id);s['protection']['stop']=1
            self.engine.save(db,s,dict(type='fixture-corruption'))
        self.assertIn('protection',self.engine.reconcile(self.id)['mismatches'])
        with self.assertRaisesRegex(ValueError,'mismatch'):self.ingest(bars()[21:22])
