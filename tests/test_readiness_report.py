import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import readiness_report as cli


class ReadinessReportCliTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def run_cli(self, *args):
        out = io.StringIO()
        return cli.main(list(args), out), out.getvalue()

    def test_default_report_is_honest_json_with_blockers(self):
        code, text = self.run_cli()
        self.assertEqual(code, 0)
        report = json.loads(text)
        self.assertFalse(report['liveTradingPermitted'])
        self.assertEqual(report['decision'], 'NOT READY')
        self.assertIs(report['claimsProfitability'], False)
        self.assertIn('human_authorisation', {b['id'] for b in report['blockers'] if b['status'] == 'blocked'})

    def test_trades_add_measured_metrics_and_statistics(self):
        trades = self.root / 'trades.json'
        trades.write_text(json.dumps([dict(day='2026-02-%02d' % (1 + i % 27), net=(5 if i % 3 else -4)) for i in range(40)]))
        code, text = self.run_cli('--trades', str(trades), '--capital', '10000', '--forward-days', '3')
        self.assertEqual(code, 0)
        report = json.loads(text)
        self.assertEqual(report['performance']['tradeCount'], 40)
        self.assertEqual(len(report['statistics']['expectancyInterval95']), 2)
        self.assertEqual(report['forwardTesting']['forwardDays'], 3)
        self.assertEqual({b['id']: b['status'] for b in report['blockers']}['independent_trade_sample'], 'blocked')
        self.assertEqual(len(report['lineage']['tradesSha256']), 64)
        self.assertIn('trades', report['lineage']['selfReported'])

    def test_malformed_evidence_is_a_clean_refusal(self):
        for body in ('[]', '{"criteria": ["x"]}', '{"nope": 1}', 'not json'):
            evidence = self.root / 'evidence.json'
            evidence.write_text(body)
            code, text = self.run_cli('--evidence', str(evidence))
            self.assertIn(code, (0, 3), body)
            if code == 0:
                self.assertEqual(json.loads(text)['score'], 0)

    def test_markdown_and_bad_inputs(self):
        code, text = self.run_cli('--markdown')
        self.assertEqual(code, 0)
        self.assertIn('Hard blockers', text)
        self.assertIn('NOT READY', text)
        bad = self.root / 'bad.json'
        bad.write_text('[{"day": "nope", "net": 1}]')
        self.assertEqual(self.run_cli('--trades', str(bad))[0], 3)
        self.assertEqual(self.run_cli('--trades', str(self.root / 'missing.json'))[0], 3)
        self.assertEqual(self.run_cli('--forward-days', '-1')[0], 3)

    def test_no_network_broker_or_order_code(self):
        for name in ('live_readiness.py', 'deployment_state.py', 'scripts/readiness_report.py'):
            source = (Path(__file__).resolve().parents[1] / name).read_text(encoding='utf-8')
            for forbidden in ('urllib', 'requests', 'kiteconnect', 'socket', 'subprocess', 'place_order'):
                self.assertNotIn(forbidden, source, name)


if __name__ == '__main__':
    unittest.main()
