import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import ema_adx_report as report
from test_ema_adx_backtest import BARS, CONFIG, flat_bars


class ReportCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def write(self, name, value):
        path = self.dir / name
        path.write_text(json.dumps(value), encoding='utf-8')
        return str(path)

    def run_cli(self, *extra, bars=None, config=None):
        out = io.StringIO()
        argv = ['--bars', self.write('bars.json', bars or BARS), '--config', self.write('config.json', config or CONFIG), *extra]
        report.main(argv, out)
        return json.loads(out.getvalue())

    def test_backtest_report_is_json_without_the_equity_series_and_claims_nothing(self):
        result = self.run_cli()
        self.assertEqual(result['version'], 'ema20-50-adx14-intraday-5m-v1')
        self.assertNotIn('equity', result)
        self.assertFalse(result['claimsProfitability'])
        self.assertGreater(len(result['trades']), 0)

    def test_walk_forward_report_lists_windows_and_trims_trade_fields(self):
        result = self.run_cli('--walk-forward', '--minimum-train', '150', '--test-size', '75')
        self.assertGreaterEqual(len(result['folds']), 2)
        trade = next(t for f in result['folds'] for t in f['trades'])
        self.assertEqual(set(trade), {'entryDate', 'exitDate', 'exitReason', 'quantity', 'netPnl'})
        self.assertFalse(result['claimsProfitability'])

    def test_corporate_actions_are_applied_before_the_run(self):
        bars = flat_bars() + flat_bars(price=50.0, day=1)             # a 2:1 split between the sessions, unadjusted
        actions = self.write('actions.json', [dict(date='2026-01-03', type='split', ratio=2)])
        result = self.run_cli('--actions', actions, bars=bars)
        self.assertEqual(result['version'], 'ema20-50-adx14-intraday-5m-v1')

    def test_bad_input_exits_with_a_clear_message_and_runs_nothing(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_cli(config=dict(CONFIG, maxLoss=1e9))
        self.assertIn('Cannot run', str(caught.exception))
        with self.assertRaises(SystemExit):
            report.main(['--bars', str(self.dir / 'missing.json'), '--config', str(self.dir / 'c.json')], io.StringIO())
        (self.dir / 'broken.json').write_text('{not json', encoding='utf-8')
        with self.assertRaises(SystemExit):
            report.main(['--bars', str(self.dir / 'broken.json'), '--config', str(self.dir / 'broken.json')], io.StringIO())

    def test_cli_has_no_network_or_broker_imports(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts' / 'ema_adx_report.py').read_text(encoding='utf-8')
        for forbidden in ('urllib', 'requests', 'kiteconnect', 'import app', 'import paper', 'sqlite3', 'socket'):
            self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main()
