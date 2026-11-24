import copy
from contextlib import contextmanager
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import eod_report
from operational_alerts import OperationalAlerts
from paper import PaperEngine
from scripts import eod_report as cli
from test_paper import CONFIG
from test_trader_suite import bars

DAY = '2026-10-01'


@contextmanager
def writable(path):
    db = sqlite3.connect(path)
    try:
        yield db
        db.commit()
    finally:
        db.close()
CONFIG_COSTS = dict(CONFIG, costBps=5, slippageBps=10)


class EodReportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.path = self.root / 'paper.sqlite'
        engine = PaperEngine(self.path)
        self.identity = engine.create(CONFIG_COSTS)['id']
        engine.control(self.identity, 'start')
        engine.ingest(self.identity, bars()[:30], True)

    def report(self, **kwargs):
        return eod_report.build(self.path, DAY, **kwargs)

    def test_lists_positions_pnl_costs_and_slippage_against_modelled_fills(self):
        report = self.report()
        self.assertEqual(report['status'], 'PASS')
        account = report['accounts'][0]
        self.assertEqual(account['quantity'], 10)
        fill = account['fills'][0]
        self.assertEqual(fill['side'], 'BUY')
        self.assertAlmostEqual(fill['rawOpen'], 120)
        self.assertAlmostEqual(fill['price'], 120 * 1.001)
        self.assertAlmostEqual(fill['slippageBps'], 10, places=6)
        self.assertAlmostEqual(fill['slippageCost'], 10 * 120 * 0.001, places=6)
        self.assertAlmostEqual(account['fees'], fill['fee'])
        self.assertGreater(account['fees'], 0)
        self.assertEqual(account['pnl']['basis'], 'modelled paper result at the last accepted close')
        self.assertAlmostEqual(account['pnl']['change'], account['equity'] - CONFIG_COSTS['capital'])
        self.assertIs(report['claimsProfitability'], False)

    def test_building_the_report_never_writes_or_restarts_anything(self):
        before = self.path.read_bytes()
        with writable(self.path) as db:
            body = json.loads(db.execute('SELECT body FROM accounts').fetchone()[0])
        self.assertEqual(body['status'], 'running')
        self.report()
        self.assertEqual(self.path.read_bytes(), before)
        with writable(self.path) as db:
            self.assertEqual(json.loads(db.execute('SELECT body FROM accounts').fetchone()[0])['status'], 'running')

    def test_a_missing_database_is_reported_as_failed_not_empty(self):
        report = eod_report.build(self.root / 'absent.sqlite', DAY)
        self.assertEqual(report['status'], 'FAILED')
        self.assertIn('not found', report['failures'][0].lower())

    def test_a_day_without_candles_is_no_data_not_pass(self):
        report = eod_report.build(self.path, '2026-10-02')
        self.assertEqual(report['status'], 'NO DATA')
        self.assertEqual(report['accounts'][0]['fills'], [])

    def test_abstentions_are_listed_with_their_reason(self):
        path = self.root / 'abstain.sqlite'
        engine = PaperEngine(path)
        identity = engine.create(CONFIG_COSTS)['id']
        engine.control(identity, 'start')
        engine.ingest(identity, bars()[:20], True)
        row = bars()[20]
        row.update(open=100000, high=100001, low=99999, close=100000)
        engine.ingest(identity, [row], True)
        account = eod_report.build(path, DAY)['accounts'][0]
        self.assertTrue(any('Cash or exposure' in item['reason'] for item in account['abstentions']))

    def test_a_ledger_that_does_not_reconcile_shows_as_failed(self):
        with writable(self.path) as db:
            state = json.loads(db.execute('SELECT body FROM accounts').fetchone()[0])
            state['cash'] += 5
            db.execute('UPDATE accounts SET body=?', (json.dumps(state),))
        report = self.report()
        self.assertEqual(report['status'], 'FAILED')
        self.assertFalse(report['accounts'][0]['reconciled'])
        self.assertTrue(any('reconcile' in item.lower() for item in report['failures']))

    def test_a_fill_without_an_accepted_candle_shows_as_failed(self):
        with writable(self.path) as db:
            db.execute('DELETE FROM bars WHERE stamp=?', (bars()[20]['date'],))
        report = self.report()
        self.assertEqual(report['status'], 'FAILED')
        self.assertTrue(any('without an accepted candle' in item for item in report['failures']))

    def test_slippage_that_differs_from_the_model_shows_as_failed(self):
        with writable(self.path) as db:
            row = db.execute('SELECT seq,body FROM events').fetchall()
            for seq, body in row:
                event = json.loads(body)
                if event['type'] == 'fill':
                    event['price'] += 1
                    db.execute('UPDATE events SET body=? WHERE seq=?', (json.dumps(event), seq))
        report = self.report()
        self.assertEqual(report['status'], 'FAILED')
        self.assertTrue(any('slippage' in item.lower() for item in report['failures']))

    def test_open_incidents_are_failures(self):
        alerts = OperationalAlerts(self.root / 'alerts.sqlite')
        alerts.observe('paper:token-loss', 'Zerodha login lost.', True, severity='critical')
        report = self.report(alerts_path=self.root / 'alerts.sqlite')
        self.assertEqual(report['status'], 'FAILED')
        self.assertIn('Zerodha login lost.', ' '.join(report['failures']))

    def test_an_intraday_position_still_open_is_a_failure_but_overnight_is_noted(self):
        # the legacy account may hold overnight: not a failure
        self.assertEqual(self.report()['status'], 'PASS')
        with writable(self.path) as db:
            state = json.loads(db.execute('SELECT body FROM accounts').fetchone()[0])
            state['config']['overnight'] = False
            db.execute('UPDATE accounts SET body=?', (json.dumps(state),))
        self.assertTrue(any('square-off' in item.lower() for item in self.report()['failures']))

    def test_markdown_states_failures_and_never_claims_profit(self):
        text = eod_report.render(self.report())
        self.assertIn('No profitability is established', text)
        self.assertIn('modelled', text)
        failed = copy.deepcopy(self.report())
        failed.update(status='FAILED', failures=['Example failure.'])
        rendered = eod_report.render(failed)
        self.assertIn('FAILED', rendered)
        self.assertIn('Example failure.', rendered)
        import re
        for line in text.splitlines():
            if re.search(r'(?i)profitab|guarantee|risk[- ]free', line):
                self.assertRegex(line, r'(?i)\b(no|not|never|without)\b')

    def test_write_creates_a_dated_file_only_in_the_requested_folder(self):
        out = self.root / 'private-reports'
        path = eod_report.write(self.report(), out)
        self.assertEqual(path, out / ('eod-%s.md' % DAY))
        self.assertIn(DAY, path.read_text(encoding='utf-8'))

    def test_the_day_must_be_an_iso_date(self):
        for bad in ('2026-13-01', 'yesterday', '', None):
            with self.assertRaises(ValueError):
                eod_report.build(self.path, bad)

    def test_week_summary_counts_days_and_does_not_hide_a_failed_day(self):
        days = ['2026-09-30', DAY, '2026-10-02']
        week = eod_report.build_week(self.path, days)
        self.assertEqual([d['day'] for d in week['days']], days)
        self.assertEqual(week['fillCount'], 1)
        self.assertEqual(week['noDataDays'], 2)
        self.assertEqual(week['status'], 'PASS')
        with writable(self.path) as db:
            state = json.loads(db.execute('SELECT body FROM accounts').fetchone()[0])
            state['cash'] += 5
            db.execute('UPDATE accounts SET body=?', (json.dumps(state),))
        self.assertEqual(eod_report.build_week(self.path, days)['status'], 'FAILED')
        self.assertIs(week['claimsProfitability'], False)

    def test_an_unreadable_incident_inbox_is_a_failure(self):
        bad = self.root / 'bad-alerts.sqlite'
        bad.write_bytes(b'not a database' * 100)
        report = self.report(alerts_path=bad)
        self.assertEqual(report['status'], 'FAILED')
        self.assertTrue(any('inbox could not be read' in item for item in report['failures']))

    def test_a_feed_error_is_a_failure(self):
        with writable(self.path) as db:
            state = json.loads(db.execute('SELECT body FROM accounts').fetchone()[0])
            state['feed'] = dict(lastError='Quote request timed out.')
            db.execute('UPDATE accounts SET body=?', (json.dumps(state),))
        report = self.report()
        self.assertEqual(report['status'], 'FAILED')
        self.assertTrue(any('Quote request timed out.' in item for item in report['failures']))

    def test_a_file_that_is_not_a_database_is_failed(self):
        junk = self.root / 'junk.sqlite'
        junk.write_bytes(b'garbage' * 200)
        report = eod_report.build(junk, DAY)
        self.assertEqual(report['status'], 'FAILED')
        self.assertIn('could not be read', report['failures'][0])

    def test_a_missing_inbox_is_noted_and_a_required_one_fails(self):
        gone = self.root / 'nope.sqlite'
        noted = self.report(alerts_path=gone)
        self.assertEqual(noted['status'], 'PASS')
        self.assertTrue(any('not checked' in item for item in noted['notes']))
        self.assertIn('not checked', eod_report.render(noted))
        required = self.report(alerts_path=gone, alerts_required=True)
        self.assertEqual(required['status'], 'FAILED')

    def test_the_weekly_report_shows_days_pnl_and_failures(self):
        with writable(self.path) as db:
            state = json.loads(db.execute('SELECT body FROM accounts').fetchone()[0])
            state['cash'] += 5
            db.execute('UPDATE accounts SET body=?', (json.dumps(state),))
        text = eod_report.render_week(eod_report.build_week(self.path, ['2026-09-30', DAY]))
        self.assertIn('FAILED', text)
        self.assertIn('does not reconcile', text)
        self.assertIn('%s: FAILED' % DAY, text)
        self.assertIn('2026-09-30: FAILED', text)   # an unreconciled ledger fails every day it persists
        self.assertIn('not evidence of edge', text)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.path = self.root / 'paper.sqlite'
        engine = PaperEngine(self.path)
        identity = engine.create(CONFIG_COSTS)['id']
        engine.control(identity, 'start')
        engine.ingest(identity, bars()[:30], True)

    def test_exit_code_reflects_the_status_and_a_file_is_written(self):
        out = io.StringIO()
        code = cli.main(['--db', str(self.path), '--day', DAY, '--out', str(self.root / 'reports')], out)
        self.assertEqual(code, 0)
        self.assertTrue((self.root / 'reports' / ('eod-%s.md' % DAY)).exists())
        self.assertIn('PASS', out.getvalue())
        self.assertEqual(cli.main(['--db', str(self.path), '--day', '2026-10-02', '--out', str(self.root / 'reports')], io.StringIO()), 2)
        self.assertEqual(cli.main(['--db', str(self.root / 'none.sqlite'), '--day', DAY, '--out', str(self.root / 'reports')], io.StringIO()), 1)

    def test_week_ending_writes_a_file_and_an_explicit_missing_inbox_fails(self):
        out = io.StringIO()
        code = cli.main(['--db', str(self.path), '--week-ending', '2026-10-03', '--out', str(self.root / 'reports')], out)
        self.assertEqual(code, 0)
        self.assertTrue((self.root / 'reports' / 'weekly-2026-10-03.md').exists())
        self.assertEqual(cli.main(['--db', str(self.path), '--day', DAY, '--alerts', str(self.root / 'typo.sqlite'),
                                   '--out', str(self.root / 'reports')], io.StringIO()), 1)

    def test_a_bad_date_is_a_clean_error_not_a_traceback(self):
        for args in (['--day', 'tomorrow'], ['--week-ending', '2026-99-01']):
            out = io.StringIO()
            self.assertEqual(cli.main(['--db', str(self.path), '--out', str(self.root / 'r')] + args, out), 3)
            self.assertIn('ISO', out.getvalue())

    def test_the_modules_import_no_network_broker_or_engine_constructor(self):
        for name in ('eod_report.py', 'scripts/eod_report.py'):
            source = (Path(__file__).resolve().parents[1] / name).read_text(encoding='utf-8')
            for forbidden in ('urllib', 'requests', 'kiteconnect', 'socket', 'subprocess', 'PaperEngine('):
                self.assertNotIn(forbidden, source, name)


if __name__ == '__main__':
    unittest.main()
