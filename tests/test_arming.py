import copy
import datetime as dt
import json
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import arming
import auto_selector
from test_auto_selector import SelectionTests

ROOT = Path(__file__).resolve().parents[1]
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
NOW = dt.datetime(2026, 11, 25, 9, 20, tzinfo=IST)
SESSION = dict(access_token='fixture-token', profile={'user_id': 'FIXTURE'})
ENV = {'KITE_DATA_STORAGE_APPROVED': 'true'}


def calendar(**overrides):
    base = json.loads((ROOT / 'docs' / 'infy-paper-calendar-2026-11-20.json').read_text())
    base.pop('symbol', None)
    base.update(overrides)
    return base


def check(**overrides):
    args = dict(environ=ENV, session=SESSION, calendar=calendar(), now=NOW)
    args.update(overrides)
    return arming.checklist(**args)


def item(result, key):
    return next(i for i in result['items'] if i['key'] == key)


class ChecklistTests(unittest.TestCase):
    def test_everything_in_place_is_ready_but_authorises_nothing(self):
        result = check()
        self.assertTrue(result['ready'], result)
        self.assertEqual(result['ownerSteps'], [])
        self.assertFalse(result['attestationsWrittenByCode'])
        self.assertFalse(result['authorizesOrders'])
        self.assertEqual(result['mode'], 'paper-only')
        self.assertFalse(result['armed'])

    def test_no_login_blocks_and_names_the_owner_step(self):
        for session in (None, {}, dict(SESSION, access_token=None), dict(SESSION, profile={})):
            result = check(session=session)
            self.assertFalse(result['ready'])
            self.assertEqual(item(result, 'login')['status'], 'BLOCKED')
            self.assertIn('sign in yourself', item(result, 'login')['ownerAction'])

    def test_retention_attestation_must_come_from_the_owner_environment(self):
        for env in ({}, {'KITE_DATA_STORAGE_APPROVED': 'false'}, {'KITE_DATA_STORAGE_APPROVED': 'yes'}):
            result = check(environ=env)
            self.assertFalse(result['ready'])
            self.assertEqual(item(result, 'storage')['status'], 'BLOCKED')
        self.assertTrue(check(environ={'KITE_DATA_STORAGE_APPROVED': ' TRUE '})['ready'])

    def test_holiday_unlisted_stale_or_missing_calendar_is_not_ready(self):
        cases = {'holiday': NOW.replace(day=24), 'unlisted': NOW.replace(month=12, day=15)}
        for label, moment in cases.items():
            result = check(now=moment)
            self.assertFalse(result['ready'], label)
            self.assertIn(item(result, 'calendar')['status'], ('BLOCKED', 'FAIL'), label)
        stale = check(calendar=calendar(availableAt='2025-01-01T00:00:00+05:30'))
        self.assertEqual(item(stale, 'calendar')['status'], 'FAIL')
        self.assertIn('stale', item(stale, 'calendar')['detail'])
        for bad in (None, 'x', {}, {'sessions': 5}):
            self.assertFalse(check(calendar=bad)['ready'])

    def test_checklist_never_mutates_inputs_environment_or_files(self):
        env, session, cal = dict(ENV), copy.deepcopy(SESSION), calendar()
        before = (dict(env), copy.deepcopy(session), copy.deepcopy(cal), dict(os.environ))
        arming.checklist(environ=env, session=session, calendar=cal, now=NOW)
        self.assertEqual((env, session, cal, dict(os.environ)), before)

    def test_selector_status_reports_armed_without_arming(self):
        self.assertTrue(check(selector_status={'enabled': True})['armed'])
        self.assertFalse(check(selector_status={'enabled': False})['armed'])

    def test_no_repository_code_writes_the_retention_attestation(self):
        writers = re.compile(r"environ\[['\"]KITE_DATA_STORAGE_APPROVED['\"]\]\s*=|putenv\(|setdefault\(['\"]KITE_DATA_STORAGE_APPROVED|"
                             r"environ\.update\([^)]*KITE_DATA_STORAGE_APPROVED")
        hits = []
        for path in ROOT.rglob('*.py'):
            relative = path.relative_to(ROOT).as_posix()
            if relative.startswith(('tests/', '.venv/', '.tools/', 'security_research/', '.claude/')):
                continue
            if writers.search(path.read_text(encoding='utf-8', errors='ignore')):
                hits.append(relative)
        self.assertEqual(hits, [])


class SelectorArmingTests(unittest.TestCase):
    """Real AutoSelector, offline fixtures."""
    setUp = SelectionTests.setUp
    advance = SelectionTests.advance

    def arm(self, session=None, calendar_override=None):
        with patch('auto_selector.threading.Thread') as thread:
            self.selector.start(self.session if session is None else session, self.config,
                                calendar_override or self.calendar)
        return thread

    def test_a_fresh_process_starts_disarmed(self):
        self.assertFalse(self.selector.enabled)
        self.assertEqual(self.selector.status()['state'], 'disarmed')
        self.assertIsNone(self.selector.worker.account)
        with self.engine.db() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM auto_selection').fetchone())

    def test_start_refuses_without_a_broker_token_and_stays_disarmed(self):
        for session in (dict(self.session, access_token=None), dict(self.session, profile=None), {}):
            with self.assertRaises((PermissionError, ValueError)):
                self.arm(session)
            self.assertFalse(self.selector.enabled)

    def test_start_refuses_unlisted_and_stale_calendars(self):
        unlisted = dict(self.calendar, sessions={'2026-01-05': self.calendar['sessions']['2026-01-02']})
        with self.assertRaises(ValueError):
            self.arm(calendar_override=unlisted)
        stale = dict(self.calendar, availableAt='2025-10-01T00:00:00+05:30')
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.arm(calendar_override=stale)
        self.assertFalse(self.selector.enabled)

    def test_start_is_idempotent_and_never_creates_a_second_worker_thread(self):
        with patch('auto_selector.threading.Thread') as thread:
            first = self.selector.start(self.session, self.config, self.calendar)
            second = self.selector.start(self.session, self.config, self.calendar)
        self.assertEqual(thread.call_count, 1)
        self.assertEqual(first['state'], second['state'])
        with self.assertRaises(PermissionError):   # a different broker session cannot take over
            self.selector.start(dict(self.session, access_token='someone-else'), self.config, self.calendar)

    def test_end_session_kill_switch_wins_and_nothing_is_funded_afterwards(self):
        self.arm()
        self.selector.control('end_session')
        self.assertFalse(self.selector.enabled)
        self.advance(15)
        with self.engine.db() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM auto_selection').fetchone())
        self.assertIsNone(self.selector.worker.account)

    def test_pausing_entries_stops_funding_until_the_owner_resumes(self):
        self.arm()
        self.selector.control('pause_entries')
        self.advance(15)
        with self.engine.db() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM auto_selection').fetchone())
        self.assertEqual(self.selector.detail['state'], 'entries-paused')
        self.selector.control('resume_entries')
        self.advance(5)
        with self.engine.db() as db:
            self.assertIsNotNone(db.execute('SELECT 1 FROM auto_selection').fetchone())

    def _control_during_scan(self, action):
        """The owner's control arrives after tick() passed its checks but before allocation."""
        real = auto_selector.rank_candidates

        def ranked_then_control(*args, **kwargs):
            result = real(*args, **kwargs)
            self.selector.control(action)
            return result
        self.arm()
        with patch.object(auto_selector, 'rank_candidates', side_effect=ranked_then_control):
            try:
                self.selector.tick()
            except ValueError as error:   # the existing guard refuses loudly once the session has ended
                self.assertIn('Selection stopped before allocation', str(error))
        with self.engine.db() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM auto_selection').fetchone())
        self.assertIsNone(self.selector.worker.account)

    def test_pause_arriving_during_an_in_flight_scan_funds_nothing(self):
        self._control_during_scan('pause_entries')

    def test_end_session_arriving_during_an_in_flight_scan_funds_nothing(self):
        self._control_during_scan('end_session')

    def test_without_a_control_the_same_scan_does_fund_so_the_race_tests_are_meaningful(self):
        self.arm()
        self.selector.tick()
        with self.engine.db() as db:
            self.assertIsNotNone(db.execute('SELECT 1 FROM auto_selection').fetchone())

    def test_code_never_writes_the_retention_attestation_while_arming(self):
        before = os.environ.get('KITE_DATA_STORAGE_APPROVED')
        self.arm()
        self.assertEqual(os.environ.get('KITE_DATA_STORAGE_APPROVED'), before)
        with self.engine.db() as db:
            rows = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            self.assertNotIn('attestations', rows)


del SelectionTests

if __name__ == '__main__':
    unittest.main()
