import copy
import json
import unittest
from pathlib import Path

import trading_calendar as cal

ROOT = Path(__file__).resolve().parents[1]
NOW = '2026-11-23T10:00:00+05:30'


def day(date, open_='09:15:00', close='15:15:00'):
    return dict(open='%sT%s+05:30' % (date, open_), close='%sT%s+05:30' % (date, close))


def manifest(**overrides):
    base = dict(exchange='NSE', segment='EQ', version='nse-eq-test-v1', source='https://example.invalid/calendar',
                availableAt='2026-11-20T15:05:00+05:30',
                sessions={'2026-11-23': day('2026-11-23'), '2026-11-24': None,
                          '2026-11-25': day('2026-11-25'), '2026-11-26': day('2026-11-26')})
    base.update(overrides)
    return base


class ValidateTests(unittest.TestCase):
    def test_valid_manifest_reports_source_version_fingerprint_and_runway(self):
        result = cal.validate(manifest(), NOW)
        self.assertEqual((result['version'], result['source']), ('nse-eq-test-v1', 'https://example.invalid/calendar'))
        self.assertEqual(result['firstDate'], '2026-11-23')
        self.assertEqual(result['lastDate'], '2026-11-26')
        self.assertEqual(result['runwayTradingDays'], 3)
        self.assertRegex(result['fingerprint'], r'^[0-9a-f]{64}$')
        self.assertEqual(result['fingerprint'], cal.fingerprint(manifest()))
        self.assertNotEqual(result['fingerprint'], cal.fingerprint(manifest(version='nse-eq-test-v2')))

    def test_repo_sample_calendar_is_valid_for_its_window(self):
        sample = json.loads((ROOT / 'docs' / 'infy-paper-calendar-2026-11-20.json').read_text())
        self.assertEqual(cal.validate(sample, NOW)['lastDate'], '2026-11-27')

    def test_missing_or_blank_or_huge_version_is_refused(self):
        for version in (None, '', '   ', 'v' * 101, 5):
            with self.assertRaises(cal.CalendarError, msg=repr(version)):
                cal.validate(manifest(version=version), NOW)

    def test_bad_source_or_attribution_is_refused(self):
        for bad in (dict(source='http://example.invalid/c'), dict(source=''), dict(exchange='BSE'), dict(segment='FO')):
            with self.assertRaises(cal.CalendarError, msg=str(bad)):
                cal.validate(manifest(**bad), NOW)
        with self.assertRaises(cal.CalendarError):
            cal.validate('not a dict', NOW)

    def test_stale_calendar_fails_closed_and_age_limit_is_configurable(self):
        old = manifest(availableAt='2026-09-01T00:00:00+05:30')
        with self.assertRaisesRegex(cal.CalendarError, 'stale'):
            cal.validate(old, NOW)
        self.assertTrue(cal.validate(old, NOW, max_age_days=120)['version'])

    def test_calendar_not_yet_available_is_refused(self):
        with self.assertRaises(cal.CalendarError):
            cal.validate(manifest(availableAt='2026-11-23T11:00:00+05:30'), NOW)

    def test_empty_oversized_or_invalid_sessions_are_refused(self):
        for sessions in ({}, None, [], {'not-a-date': None}, {'2026-11-23': 'open'},
                         {'2026-11-23': day('2026-11-24')}):
            with self.assertRaises(cal.CalendarError, msg=str(sessions)):
                cal.validate(manifest(sessions=sessions), NOW)
        big = {('2027-%02d-%02d' % (m, d)): None for m in range(1, 13) for d in range(1, 29)}
        big.update({('2028-%02d-%02d' % (m, d)): None for m in range(1, 13) for d in range(1, 29)})
        with self.assertRaises(cal.CalendarError):
            cal.validate(manifest(sessions=big), NOW)

    def test_special_sessions_and_weekend_openings_are_unsupported(self):
        for sessions in ({'2026-11-21': day('2026-11-21')},                       # Saturday session
                         {'2026-11-23': day('2026-11-23', open_='18:15:00', close='19:15:00')},  # muhurat-style
                         {'2026-11-23': day('2026-11-23', close='13:00:00')},      # unsupported close
                         {'2026-11-23': day('2026-11-23', open_='09:30:00')}):
            with self.assertRaisesRegex(cal.CalendarError, 'unsupported'):
                cal.validate(manifest(sessions=sessions), NOW)

    def test_minimum_runway_is_enforced_when_requested(self):
        self.assertTrue(cal.validate(manifest(), NOW, min_runway_days=3))
        with self.assertRaisesRegex(cal.CalendarError, 'runway'):
            cal.validate(manifest(), NOW, min_runway_days=4)

    def test_validation_does_not_mutate_the_manifest(self):
        data = manifest()
        before = copy.deepcopy(data)
        cal.validate(data, NOW)
        self.assertEqual(data, before)


class TradingDayTests(unittest.TestCase):
    def test_listed_open_day_returns_session_and_square_off_time(self):
        result = cal.require_trading_day(manifest(), NOW, square_off='15:05')
        self.assertEqual(result['date'], '2026-11-23')
        self.assertEqual(result['squareOffAt'], '2026-11-23T15:05:00+05:30')
        self.assertEqual(result['end'], '2026-11-23T15:15:00+05:30')
        self.assertEqual((result['version'], result['source']), ('nse-eq-test-v1', 'https://example.invalid/calendar'))

    def test_unlisted_date_refuses_to_start(self):
        with self.assertRaisesRegex(cal.CalendarError, 'not listed'):
            cal.require_trading_day(manifest(), '2026-11-30T10:00:00+05:30', square_off='15:05')

    def test_closed_or_holiday_date_yields_no_processing(self):
        with self.assertRaises(cal.ClosedDay):
            cal.require_trading_day(manifest(), '2026-11-24T10:00:00+05:30', square_off='15:05')
        self.assertTrue(issubclass(cal.ClosedDay, cal.CalendarError))

    def test_square_off_must_complete_strictly_before_the_calendar_close(self):
        with self.assertRaisesRegex(cal.CalendarError, '(?i)square-off'):
            cal.require_trading_day(manifest(), NOW, square_off='15:10')   # +5 minute candle reaches 15:15
        self.assertTrue(cal.require_trading_day(manifest(), NOW, square_off='15:09'))
        with self.assertRaises(cal.CalendarError):
            cal.require_trading_day(manifest(), NOW, square_off='bad')

    def test_square_off_moves_with_the_calendar_close(self):
        short = manifest(sessions={'2026-11-23': day('2026-11-23', close='15:30:00')})
        self.assertEqual(cal.require_trading_day(short, NOW, square_off='15:20')['end'], '2026-11-23T15:30:00+05:30')
        with self.assertRaises(cal.CalendarError):
            cal.require_trading_day(manifest(), NOW, square_off='15:20')

    def test_ist_date_not_utc_date_drives_today_and_runway(self):
        # 20:00 UTC on 22 Nov is 01:30 IST on 23 Nov: 23 Nov is today's session.
        utc_before_midnight = '2026-11-22T20:00:00+00:00'
        self.assertEqual(cal.require_trading_day(manifest(), utc_before_midnight, square_off='15:05')['date'], '2026-11-23')
        # 20:00 UTC on 23 Nov is 01:30 IST on 24 Nov, a holiday; 23 Nov no longer counts toward runway.
        later = '2026-11-23T20:00:00+00:00'
        with self.assertRaises(cal.ClosedDay):
            cal.require_trading_day(manifest(), later, square_off='15:05')
        self.assertEqual(cal.validate(manifest(), later)['runwayTradingDays'], 2)

    def test_stale_calendar_blocks_even_a_listed_day(self):
        with self.assertRaises(cal.CalendarError):
            cal.require_trading_day(manifest(availableAt='2026-09-01T00:00:00+05:30'), NOW, square_off='15:05')


class NextOpenDateTests(unittest.TestCase):
    def test_next_open_date_skips_holidays_and_past_dates(self):
        self.assertEqual(cal.next_open_date(manifest(), '2026-11-23T10:00:00+05:30'), '2026-11-25')
        self.assertEqual(cal.next_open_date(manifest(), '2026-11-24T10:00:00+05:30'), '2026-11-25')
        self.assertIsNone(cal.next_open_date(manifest(), '2026-11-26T10:00:00+05:30'))
        self.assertIsNone(cal.next_open_date(None, NOW))
        self.assertIsNone(cal.next_open_date(dict(sessions={'bad': None, '2026-11-30': None}), NOW))

    def test_unlisted_message_tells_the_owner_what_to_add(self):
        with self.assertRaisesRegex(cal.CalendarError, 'not listed.*Add it'):
            cal.require_trading_day(manifest(), '2026-11-30T10:00:00+05:30', square_off='15:05')


if __name__ == '__main__':
    unittest.main()
