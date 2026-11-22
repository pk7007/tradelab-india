import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent_service import AgentService
from desk_coordinator import DeskCoordinator


class DeskTests(unittest.TestCase):
    def test_handoffs_deduplicate_and_failure_reaches_review(self):
        with tempfile.TemporaryDirectory() as folder:
            agents = AgentService(Path(folder)/'agents.sqlite')
            news = SimpleNamespace(status=lambda _: dict(stale=False, items=[]))
            paper = SimpleNamespace(status=lambda: dict(accounts=[dict(id='account',quantity=0,pending=None)]),
                                    reconcile=lambda _: dict(matches=False))
            worker = SimpleNamespace(status=lambda: dict(state='disarmed'))
            desk = DeskCoordinator(news, SimpleNamespace(master=[]), paper, worker, agents)
            with patch('desk_coordinator.dt') as clock:
                import datetime
                clock.datetime.now.return_value = datetime.datetime(2026,11,20,10,tzinfo=datetime.timezone.utc)
                first = desk.tick()
                self.assertEqual(first['tasks'], desk.tick()['tasks'])
            self.assertEqual(first['departments'][2]['state'], 'blocked')
            self.assertFalse(first['executionAllowed'])
            self.assertEqual(len(first['tasks']), 3)
            agents.run_once()
            self.assertEqual(agents.status()['queue'].get('review'), 1)
            desk.tick()
            self.assertEqual(agents.status()['queue'].get('desk-reviewed'), 1)
            self.assertIsNone(agents.status()['queue'].get('accepted'))
            agents.stop()
