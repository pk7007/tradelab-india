import datetime as dt
import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import supervision
from auto_selector import AutoSelector
from operational_alerts import OperationalAlerts
from paper import PaperEngine
import test_auto_selector as fixtures


class SupervisionTests(unittest.TestCase):
    """Real AutoSelector and PaperEngine with offline fixtures and an injected clock."""

    def setUp(self):
        fixtures.SelectionTests.setUp(self)
        self.alerts = OperationalAlerts(Path(self.temp.name) / 'alerts.sqlite')
        self.selector.alerts = self.alerts

    start = fixtures.SelectionTests.start
    advance = fixtures.SelectionTests.advance

    def open_position(self):
        self.start()
        self.selector.tick()
        self.selector.tick()
        self.advance(10)
        identity = self.selector.worker.account
        self.assertGreater(self.engine.reconcile(identity)['quantity'], 0)
        return identity

    def active(self):
        return {row['key']: row for row in self.alerts.status()['items'] if not row['resolved_at']}

    def lose_token(self):
        self.selector.token = None
        return self.selector.step()

    def fills(self, identity):
        with self.engine.db() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT body FROM events WHERE account=? ORDER BY seq', (identity,))
                    if json.loads(r[0]).get('type') == 'fill']

    def test_token_loss_with_an_open_position_alerts_blocks_entries_and_flags_exposed(self):
        identity = self.open_position()
        self.assertFalse(self.lose_token())
        alerts = self.active()
        self.assertEqual(alerts['paper:token-loss']['severity'], 'critical')
        self.assertEqual(alerts['paper:exposed']['severity'], 'critical')
        status = self.selector.status()
        self.assertEqual(status['state'], 'blocked')
        self.assertIn('Exposure or pending intent remains', status['reason'])   # status() names the exposure
        self.assertFalse(status['enabled'])
        self.assertEqual(status['exposure']['status'], 'EXPOSED')
        self.assertEqual(status['exposure']['positions'][0]['accountId'], identity)
        self.assertGreater(status['exposure']['positions'][0]['quantity'], 0)
        self.assertEqual(status['exposure']['positions'][0]['squareOff'], '15:05')
        with self.engine.db() as db:
            self.assertTrue(self.engine.load(db, identity)['entriesPaused'])

    def test_exposed_terminal_state_has_no_phantom_fill_and_the_alert_persists(self):
        identity = self.open_position()
        before = self.fills(identity)
        self.lose_token()
        self.now += dt.timedelta(hours=5)     # the market moves on; nobody is logged in
        self.assertEqual(self.fills(identity), before)
        self.assertGreater(self.engine.reconcile(identity)['quantity'], 0)
        self.assertTrue(self.engine.reconcile(identity)['matches'])
        self.assertEqual(supervision.phantom_fills(self.engine, identity), [])
        self.assertIn('paper:exposed', self.active())
        self.assertIn('paper:token-loss', self.active())

    def test_phantom_fill_check_flags_a_fill_with_no_accepted_candle(self):
        identity = self.open_position()
        self.assertEqual(supervision.phantom_fills(self.engine, identity), [])
        with self.engine.db() as db:
            db.execute('INSERT INTO events(account,at,body) VALUES(?,?,?)',
                       (identity, '2026-01-02T15:00:00+05:30',
                        json.dumps(dict(type='fill', bar='2026-01-02T15:10:00+05:30', side='SELL', quantity=1))))
        self.assertEqual([f['bar'] for f in supervision.phantom_fills(self.engine, identity)], ['2026-01-02T15:10:00+05:30'])

    def test_owner_relogin_and_rearm_resolve_the_login_alert_but_exposure_stays_until_flat(self):
        self.open_position()
        self.lose_token()
        self.selector.session = None
        self.selector.thread = None          # the real loop thread exits after a failure
        fresh = dict(self.session, access_token='fresh-token', last_seen=self.session['last_seen'])
        with patch('auto_selector.threading.Thread'):
            self.selector.start(fresh, self.config, self.calendar)
        active = self.active()
        self.assertNotIn('paper:token-loss', active)
        self.assertIn('paper:exposed', active)

    def test_flat_account_losing_its_token_only_warns(self):
        self.start()
        self.assertFalse(self.lose_token())
        active = self.active()
        self.assertEqual(active['paper:token-loss']['severity'], 'warning')
        self.assertNotIn('paper:exposed', active)
        self.assertEqual(self.selector.status()['exposure']['status'], 'FLAT')

    def test_restart_is_disarmed_pauses_the_ledger_and_raises_the_exposure_alert(self):
        identity = self.open_position()
        self.lose_token()
        quantity = self.engine.reconcile(identity)['quantity']
        restarted_engine = PaperEngine(self.engine.path)          # crash and restart
        restarted = AutoSelector(restarted_engine, self.market, clock=lambda: self.now)
        self.assertFalse(restarted.enabled)
        self.assertEqual(restarted.status()['state'], 'disarmed')
        with restarted_engine.db() as db:
            account = restarted_engine.load(db, identity)
        self.assertEqual((account['quantity'], account['status']), (quantity, 'paused'))
        self.assertIsNone(account['pending'])
        self.assertTrue(restarted_engine.reconcile(identity)['matches'])
        fresh_alerts = OperationalAlerts(Path(self.temp.name) / 'alerts2.sqlite')
        report = supervision.observe_exposure(fresh_alerts, restarted_engine, now=self.now)
        self.assertEqual(report[0]['quantity'], quantity)
        self.assertEqual(fresh_alerts.status()['active'], 1)

    def test_exposure_alert_resolves_once_the_ledger_is_flat(self):
        alerts = OperationalAlerts(Path(self.temp.name) / 'flat.sqlite')
        self.assertEqual(supervision.observe_exposure(alerts, self.engine, now=self.now), [])
        self.assertEqual(alerts.status()['active'], 0)
        identity = self.open_position()
        supervision.observe_exposure(alerts, self.engine, now=self.now)
        self.assertEqual(alerts.status()['active'], 1)
        with self.engine.db() as db:
            state = self.engine.load(db, identity)
            state.update(quantity=0, pending=None)
        with patch.object(self.engine, 'reconcile_in', return_value=dict(matches=True)):
            with patch.object(supervision, 'exposure_report', return_value=[]):
                supervision.observe_exposure(alerts, self.engine, now=self.now)
        self.assertEqual(alerts.status()['active'], 0)

    def test_a_broken_alert_inbox_never_stops_the_failure_handling(self):
        self.open_position()
        with patch.object(self.alerts, 'observe', side_effect=sqlite3.OperationalError('inbox down')):
            self.assertFalse(self.lose_token())
        status = self.selector.status()
        self.assertEqual(status['state'], 'blocked')
        self.assertFalse(status['enabled'])

    def test_explicit_logout_with_an_open_position_raises_both_incidents(self):
        self.open_position()
        self.selector.revoke()
        active = self.active()
        self.assertEqual(active['paper:token-loss']['severity'], 'critical')
        self.assertEqual(active['paper:exposed']['severity'], 'critical')
        self.assertEqual(self.selector.status()['exposure']['status'], 'EXPOSED')

    def test_stopping_selection_with_an_open_position_leaves_an_exposure_incident(self):
        self.open_position()
        self.selector.stop()
        self.assertIn('paper:exposed', self.active())
        self.assertNotIn('paper:token-loss', self.active())

    def test_logout_or_stop_when_flat_leaves_no_exposure_incident(self):
        self.start()
        self.selector.stop()
        self.assertNotIn('paper:exposed', self.active())

    def test_nothing_can_be_funded_after_a_failure(self):
        self.start()
        self.lose_token()
        with self.assertRaises(ValueError):
            self.selector.allocate('2026-01-02', dict(exchange='NSE', symbol='DEMO', token=123))
        self.advance(10)
        with self.engine.db() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM auto_selection').fetchone())

    def test_startup_scan_records_exposure_and_never_raises(self):
        identity = self.open_position()
        self.lose_token()
        fresh = OperationalAlerts(Path(self.temp.name) / 'startup.sqlite')
        self.assertTrue(supervision.startup_scan(fresh, PaperEngine(self.engine.path)))
        self.assertEqual(fresh.status()['active'], 1)
        with self.assertLogs('supervision', level='WARNING') as captured:
            broken = OperationalAlerts(Path(self.temp.name) / 'broken.sqlite')
            with patch.object(broken, 'observe', side_effect=sqlite3.OperationalError('down')):
                self.assertFalse(supervision.startup_scan(broken, self.engine))
        self.assertIn('OperationalError', captured.output[0])
        self.assertTrue(identity)

    def test_non_login_failures_alert_too_and_a_healthy_step_changes_nothing(self):
        self.open_position()
        self.assertTrue(self.selector.step())                       # normal tick: no alert
        self.assertEqual(self.active(), {})
        with patch.object(self.selector, 'tick', side_effect=ValueError('Selection data failed')):
            self.assertFalse(self.selector.step())
        self.assertNotIn('paper:token-loss', self.active())
        self.assertIn('paper:exposed', self.active())
        self.assertEqual(self.selector.status()['state'], 'blocked')


if __name__ == '__main__':
    unittest.main()
