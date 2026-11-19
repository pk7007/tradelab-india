import unittest
from intraday_evaluation import evaluate_intraday
from test_intraday_paper import CONFIG,bars


class ReplayTests(unittest.TestCase):
    def test_same_engine_keeps_unclosed_exposure_and_matches_costed_fills(self):
        result=evaluate_intraday(dict(permitted=True,config=CONFIG,bars=bars(21)))
        self.assertEqual(result['openQuantity'],9)
        self.assertTrue(result['ledgerMatches'])
        self.assertEqual(result['fills'][0]['quantity'],9)
        self.assertFalse(result['promotionAllowed'])
        self.assertGreater(result['fees'],0)
        self.assertEqual(result,evaluate_intraday(dict(permitted=True,config=CONFIG,bars=bars(21))))

    def test_no_permission_or_legacy_protocol(self):
        with self.assertRaises(ValueError):evaluate_intraday(dict(config=CONFIG,bars=bars()))
        with self.assertRaises(ValueError):evaluate_intraday(dict(permitted=True,config=dict(CONFIG,strategy='legacy'),bars=bars()))
