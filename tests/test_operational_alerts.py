import datetime as dt
import tempfile
from pathlib import Path
import unittest

from operational_alerts import OperationalAlerts, observe_service
from operations import Operations
from paper import PaperEngine
from test_intraday_paper import CONFIG, bars


class OperationalAlertsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.alerts = OperationalAlerts(self.root / 'alerts.sqlite')

    def test_incident_dedup_acknowledgement_recovery_and_recurrence_survive_restart(self):
        for _ in range(3):
            self.alerts.observe('app:unreachable', 'App unavailable.', True, severity='critical')
        incident = self.alerts.status()['items'][0]
        self.assertEqual(len(self.alerts.status()['items']), 1)
        self.alerts.acknowledge(incident['id'])
        restarted = OperationalAlerts(self.alerts.path)
        self.assertEqual(restarted.status()['unacknowledged'], 0)
        restarted.observe('app:unreachable', 'App unavailable.', False)
        self.assertEqual(restarted.status()['active'], 0)
        restarted.observe('app:unreachable', 'App unavailable.', True)
        self.assertEqual(restarted.status()['unacknowledged'], 1)
        self.assertEqual(len(restarted.status()['items']), 2)

    def test_only_one_independent_watcher_owns_a_fresh_lease(self):
        self.assertTrue(self.alerts.lease('one', 100))
        self.assertFalse(self.alerts.lease('two', 101))
        self.assertTrue(self.alerts.lease('two', 191))

    def test_disabled_feed_is_not_an_incident_and_blocked_paper_is_visible(self):
        observe_service(self.alerts, dict(sources=[dict(source='moneycontrol', status='disabled', stale=True)],
                                        selection=dict(enabled=False, state='blocked')))
        self.assertEqual(self.alerts.status()['active'], 1)
        self.assertEqual(self.alerts.status()['items'][0]['key'], 'paper:processing')

    def test_backup_coverage_and_restore_drill_include_every_current_ledger(self):
        paper = PaperEngine(self.root / 'paper.sqlite')
        account = paper.create(CONFIG)['id']
        paper.control(account, 'start')
        paper.ingest(account, bars(21), True)
        before = paper.status()
        operations = Operations([paper.path, self.alerts.path], self.root, paper_engine=paper)
        self.assertIsNone(operations.coverage())
        operations.backup()
        self.assertEqual(operations.coverage()['missing'], [])
        self.assertEqual(operations.coverage()['included'], 2)
        drill = operations.restore_drill()
        self.assertEqual(drill['reconciledAccounts'], 1)
        self.assertEqual(drill['databases'], 2)
        self.assertTrue(operations.status()['lastRestoreDrill']['complete'])
        self.assertEqual(paper.status(), before)
