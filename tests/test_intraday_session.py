import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from intraday_session import INTENDED_PROFILE, session_snapshot
from paper import PaperEngine
from paper_worker import PaperWorker
from test_intraday_paper import CONFIG, bars


ROOT = Path(__file__).resolve().parents[1]
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
SAMPLE = json.loads((ROOT / 'docs' / 'infy-paper-calendar-2026-11-20.json').read_text())


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

    def calendar_snapshot(self, when, calendar=SAMPLE):
        return session_snapshot(self.engine, dict(enabled=False, calendar=calendar), INTENDED_PROFILE,
                                connected=True, storage_approved=True, now=when)

    def test_open_calendar_day_is_ready_and_a_closed_day_disables_start_with_a_reason(self):
        ready = self.calendar_snapshot(dt.datetime(2026, 11, 25, 9, 20, tzinfo=IST))
        self.assertTrue(ready['readiness']['calendarReady'])
        self.assertTrue(ready['readiness']['canRequestStart'])
        holiday = self.calendar_snapshot(dt.datetime(2026, 11, 24, 10, 0, tzinfo=IST))
        self.assertFalse(holiday['readiness']['calendarReady'])
        self.assertFalse(holiday['readiness']['canRequestStart'])
        self.assertTrue(any('marked closed' in note for note in holiday['attention']))

    def test_stale_or_unlisted_calendar_disables_start_with_a_reason(self):
        stale = self.calendar_snapshot(dt.datetime(2027, 1, 20, 10, 0, tzinfo=IST))
        self.assertFalse(stale['readiness']['canRequestStart'])
        self.assertTrue(any('cannot be used' in note and 'stale' in note for note in stale['attention']))
        unlisted = self.calendar_snapshot(dt.datetime(2026, 12, 2, 10, 0, tzinfo=IST), dict(SAMPLE, availableAt='2026-12-01T00:00:00+05:30'))
        self.assertFalse(unlisted['readiness']['calendarReady'])

    def test_no_calendar_in_the_selection_leaves_start_readiness_unchanged(self):
        result = session_snapshot(self.engine, dict(enabled=False), INTENDED_PROFILE, connected=True, storage_approved=True)
        self.assertIsNone(result['readiness']['calendarReady'])
        self.assertTrue(result['readiness']['canRequestStart'])

    def test_arming_steps_are_ordered_and_name_the_next_action(self):
        weekday = dt.datetime(2026, 11, 25, 9, 20, tzinfo=IST)
        ready = session_snapshot(self.engine, dict(enabled=False, calendar=SAMPLE), INTENDED_PROFILE,
                                 connected=True, storage_approved=True, now=weekday)
        self.assertEqual([step['key'] for step in ready['arming']['steps']], ['login', 'retention', 'calendar'])
        self.assertTrue(ready['arming']['ready'])
        self.assertEqual(ready['arming']['nextStep'], 'Press Start paper trading.')
        blocked = session_snapshot(self.engine, dict(enabled=False, calendar=SAMPLE), INTENDED_PROFILE,
                                   connected=False, storage_approved=False, now=weekday)
        self.assertFalse(blocked['arming']['ready'])
        self.assertIn('Connect Zerodha', blocked['arming']['nextStep'])     # first undone step wins
        self.assertEqual([s['done'] for s in blocked['arming']['steps']], [False, False, True])

    def test_holiday_step_names_the_next_open_session_and_stale_step_says_refresh(self):
        holiday = self.calendar_snapshot(dt.datetime(2026, 11, 24, 10, 0, tzinfo=IST))
        todo = next(s for s in holiday['arming']['steps'] if s['key'] == 'calendar')['todo']
        self.assertIn('2026-11-25', todo)
        self.assertTrue(any('2026-11-25' in note for note in holiday['attention']))
        stale = self.calendar_snapshot(dt.datetime(2027, 1, 20, 10, 0, tzinfo=IST))
        self.assertIn('30 days old', next(s for s in stale['arming']['steps'] if s['key'] == 'calendar')['todo'])
        last = self.calendar_snapshot(dt.datetime(2026, 11, 28, 10, 0, tzinfo=IST))   # past the listed window
        self.assertFalse(last['arming']['ready'])

    def test_no_calendar_means_two_steps_and_no_calendar_claim(self):
        result = session_snapshot(self.engine, dict(enabled=False), INTENDED_PROFILE, connected=True, storage_approved=False)
        self.assertEqual([s['key'] for s in result['arming']['steps']], ['login', 'retention'])

