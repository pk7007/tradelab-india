import copy
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from paper import PaperEngine
from test_trader_suite import bars

CONFIG=dict(symbol='DEMO',provider='Synthetic test',adjustment='None; synthetic',source='synthetic',permitted=True,capital=10000,units=10,maxExposure=5000,dailyLossLimit=500,costBps=0,slippageBps=0)


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'paper.sqlite'
        self.engine=PaperEngine(self.path);self.identity=self.engine.create(CONFIG)['id']
        self.engine.control(self.identity,'start')
    def ingest(self,rows):return self.engine.ingest(self.identity,rows,True)
    def test_next_open_cash_and_equity(self):
        state=self.ingest(bars()[:30])['account']
        self.assertEqual(state['cash'],8800)
        self.assertEqual(state['quantity'],10)
        self.assertEqual(state['equity'],10090)
        fills=[e for e in self.engine.status()['events'] if e['type']=='fill']
        self.assertEqual(fills[0]['price'],120)
        self.assertEqual(fills[0]['signalAt'],bars()[19]['date'])
    def test_restart_preserves_state_but_requires_resume(self):
        before=self.ingest(bars()[:20])['account']
        restarted=PaperEngine(self.path)
        after=restarted.status()['accounts'][0]
        self.assertEqual(after['pending'],before['pending'])
        self.assertEqual(after['status'],'paused')
        with self.assertRaises(ValueError):restarted.ingest(self.identity,bars()[20:21],True)
        restarted.control(self.identity,'start')
        self.assertEqual(restarted.ingest(self.identity,bars()[20:21],True)['account']['quantity'],10)
    def test_concurrent_identical_delivery_fills_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            result=list(pool.map(lambda _:self.ingest(bars()[:30]),range(2)))
        self.assertEqual(sorted(r['processed'] for r in result),[0,30])
        self.assertEqual(len([e for e in self.engine.status()['events'] if e['type']=='fill']),1)
    def test_revised_duplicate_and_missing_interval_roll_back_batch(self):
        self.ingest(bars()[:20])
        before=self.engine.status()
        with self.assertRaisesRegex(ValueError,'Missing'):self.ingest([bars()[20],bars()[22]])
        self.assertEqual(before,self.engine.status())
        changed=copy.deepcopy(bars()[:1]);changed[0]['volume']+=1
        with self.assertRaisesRegex(ValueError,'changed'):self.ingest(changed)
    def test_stop_preserves_position_and_cancels_pending(self):
        self.ingest(bars()[:21]);state=self.engine.control(self.identity,'stop')
        self.assertEqual(state['quantity'],10);self.assertIsNone(state['pending'])
    def test_entry_rechecks_gap_and_exposure(self):
        self.ingest(bars()[:20]);row=bars()[20]
        row.update(open=1000,high=1001,low=999,close=1000)
        self.assertEqual(self.ingest([row])['account']['quantity'],0)
        self.assertTrue(any(e['type']=='rejected' for e in self.engine.status()['events']))
    def test_invalid_data_and_permission(self):
        with self.assertRaises(ValueError):self.engine.ingest(self.identity,bars(),False)
        row=bars()[0];row['close']=float('nan')
        with self.assertRaises(ValueError):self.ingest([row])
        self.assertIsNone(self.engine.status()['accounts'][0]['lastBar'])
    def test_round_trip_reconciles_fees_and_realized_pnl(self):
        engine=PaperEngine(Path(self.folder.name)/'costs.sqlite')
        identity=engine.create(CONFIG|dict(costBps=10,slippageBps=5))['id'];engine.control(identity,'start')
        rows=bars()[:24]
        for r in rows[20:]:r.update(open=100,high=101,low=19,close=20)
        s=engine.ingest(identity,rows,True)['account']
        self.assertEqual(s['quantity'],0)
        self.assertAlmostEqual(s['equity']-10000,s['realized'])
        self.assertGreater(s['fees'],0)
        self.assertEqual(s['completedTrades'],1)
