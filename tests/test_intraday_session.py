import tempfile
import unittest
from pathlib import Path

from intraday_session import INTENDED_PROFILE, session_snapshot
from paper import PaperEngine
from paper_worker import PaperWorker
from test_intraday_paper import CONFIG, bars


class SessionPresentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = PaperEngine(Path(self.temp.name) / 'paper.sqlite')
        PaperWorker(self.engine, lambda *args: [])
        self.account = self.engine.create(CONFIG)
        self.identity = self.account['id']

    def snapshot(self, **selection):
        return session_snapshot(self.engine, dict(accountId=self.identity, **selection),
                                INTENDED_PROFILE, connected=False, storage_approved=True)

    def test_saved_limits_and_flat_do_not_claim_completed_active_session(self):
        result = self.snapshot(enabled=True, state='selected')
        self.assertEqual(result['savedProfile']['capital'], 1000)
        self.assertEqual(result['profileDifferences']['capital'], dict(saved=1000, intended=10000))
        self.assertFalse(result['report']['final'])
        self.assertTrue(result['report']['reconciliation']['matches'])
        self.assertFalse(result['readiness']['canRequestStart'])

    def test_ledger_report_matches_independent_cost_calculation_and_retains_open_exposure(self):
        self.engine.control(self.identity, 'start')
        self.engine.ingest(self.identity, bars(21), True)
        result = self.snapshot(enabled=False, state='blocked')
        # Nine shares at 102 open, 5 bps adverse slippage and 10 bps commission.
        price = 102 * 1.0005
        expected_cash = 1000 - 9 * price * 1.001
        self.assertAlmostEqual(result['report']['cash'], expected_cash)
        self.assertEqual(result['report']['quantity'], 9)
        self.assertEqual(result['report']['closureState'], 'unresolved-exposure')
        self.assertFalse(result['report']['final'])
        self.assertEqual(result['report']['fillCount'], 1)
        self.assertEqual(result['outstandingExposure'][0]['quantity'], 9)
        self.assertTrue(any('exposure' in message for message in result['attention']))

    def test_no_selection_no_trade_and_missing_news_are_explicit(self):
        result = session_snapshot(self.engine, dict(state='no-qualifying-candidate'),
                                  INTENDED_PROFILE, connected=True, storage_approved=True)
        self.assertIsNone(result['report'])
        self.assertIn('remaining in cash', result['nextAction'])
        self.assertEqual(result['news']['status'], 'unavailable')
        self.assertEqual(result['deferred'], ['Long-term research', 'Live-money activation'])

    def test_pending_buy_cannot_be_reported_as_final(self):
        self.engine.control(self.identity, 'start')
        self.engine.ingest(self.identity, bars(20), True)
        self.engine.control(self.identity, 'pause')
        result = self.snapshot(enabled=False, state='stopped')
        self.assertEqual(result['report']['pending']['side'], 'BUY')
        self.assertFalse(result['report']['final'])

    def test_managed_exposure_allows_recovery_but_foreign_exposure_blocks_it(self):
        self.engine.control(self.identity, 'start')
        self.engine.ingest(self.identity, bars(21), True)
        result = session_snapshot(self.engine, dict(accountId=self.identity, enabled=False),
                                  INTENDED_PROFILE, connected=True, storage_approved=True)
        self.assertTrue(result['readiness']['canRequestStart'])
        self.assertTrue(result['readiness']['recoveryRequired'])
        other = self.engine.create(CONFIG)['id']
        self.engine.control(other, 'start')
        self.engine.ingest(other, bars(21), True)
        result = session_snapshot(self.engine, dict(accountId=self.identity, enabled=False),
                                  INTENDED_PROFILE, connected=True, storage_approved=True)
        self.assertFalse(result['readiness']['canRequestStart'])
