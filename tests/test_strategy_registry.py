import tempfile
import unittest
from pathlib import Path

import strategy_registry as registry
from paper import PaperEngine
from test_intraday_paper import CONFIG


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = PaperEngine(Path(self.temp.name) / 'paper.sqlite')

    def create(self, name):
        return self.engine.create(dict(CONFIG, source='imported', strategy=name))

    def test_registry_agrees_with_what_the_paper_engine_actually_accepts(self):
        for name, info in registry.STRATEGIES.items():
            allowed, _ = registry.paper_allowed(name)
            self.assertEqual(allowed, info['paperApproved'])
            if allowed:
                self.assertTrue(self.create(name)['id'], name)
            else:
                with self.assertRaisesRegex(ValueError, 'Unknown paper strategy'):
                    self.create(name)

    def test_the_ema_adx_strategies_are_research_only_unpromoted_and_say_why(self):
        for name in ('ema20-50-adx14-cross-v1', 'ema20-50-adx14-intraday-5m-v1'):
            info = registry.describe(name)
            self.assertEqual((info['status'], info['paperApproved'], info['promoted']), ('research-only', False, False))
            text = ' '.join(info['blockers'])
            for needle in ('hard-wired', 'resets', 'walk-forward', 'Owner approval'):
                self.assertIn(needle, text, name)

    def test_unknown_names_are_never_allowed_and_nothing_is_ever_promoted(self):
        self.assertEqual(registry.paper_allowed('mystery-v9')[0], False)
        self.assertEqual(registry.describe('mystery-v9')['status'], 'unknown')
        self.assertFalse(any(info['promoted'] for info in registry.STRATEGIES.values()))

    def test_describe_returns_a_copy_so_callers_cannot_loosen_the_registry(self):
        info = registry.describe('ema20-50-adx14-intraday-5m-v1')
        info['blockers'].clear()
        info['paperApproved'] = True
        self.assertFalse(registry.describe('ema20-50-adx14-intraday-5m-v1')['paperApproved'])
        self.assertTrue(registry.describe('ema20-50-adx14-intraday-5m-v1')['blockers'])

    def test_backtest_module_has_no_execution_imports(self):
        source = (Path(__file__).resolve().parents[1] / 'ema_adx_backtest.py').read_text(encoding='utf-8')
        for forbidden in ('import paper', 'from paper', 'import app', 'kiteconnect', 'broker_transport', 'urllib', 'sqlite3'):
            self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main()
