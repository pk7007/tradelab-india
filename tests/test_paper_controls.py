import unittest
import test_paper
from test_trader_suite import bars


class ExitControlTests(unittest.TestCase):
    setUp = test_paper.PaperTests.setUp
    ingest = test_paper.PaperTests.ingest
    def test_pause_entries_cancels_buy_without_stopping_data(self):
        self.ingest(bars()[:20])
        state = self.engine.control(self.identity, 'pause_entries')
        self.assertEqual(state['status'], 'running')
        self.assertIsNone(state['pending'])
        state = self.ingest(bars()[20:23])['account']
        self.assertEqual(state['quantity'], 0)
        self.assertIsNone(state['pending'])

    def test_close_is_pending_until_next_bar_and_remains_flat(self):
        self.ingest(bars()[:21])
        state = self.engine.control(self.identity, 'close_position')
        self.assertEqual(state['quantity'], 10)
        self.assertEqual(state['pending']['side'], 'SELL')
        state = self.ingest(bars()[21:23])['account']
        self.assertEqual(state['quantity'], 0)
        self.assertIsNone(state['pending'])
        self.assertTrue(self.engine.reconcile(self.identity)['matches'])

    def test_pause_entries_and_cancel_preserve_exit(self):
        self.ingest(bars()[:21])
        self.engine.control(self.identity, 'close_position')
        self.engine.control(self.identity, 'pause_entries')
        state = self.engine.control(self.identity, 'cancel_entries')
        self.assertEqual(state['pending']['side'], 'SELL')
        self.assertEqual(self.ingest(bars()[21:22])['account']['quantity'], 0)

    def test_close_without_shares_and_paused_close_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.control(self.identity, 'close_position')
        self.ingest(bars()[:21])
        self.engine.control(self.identity, 'pause')
        with self.assertRaises(ValueError):
            self.engine.control(self.identity, 'close_position')

    def test_restart_does_not_remove_entry_pause(self):
        from paper import PaperEngine
        self.engine.control(self.identity, 'pause_entries')
        self.engine = PaperEngine(self.path)
        self.engine.control(self.identity, 'start')
        state = self.ingest(bars()[:23])['account']
        self.assertEqual(state['quantity'], 0)
        self.assertTrue(state['entriesPaused'])


if __name__ == '__main__':
    unittest.main()
