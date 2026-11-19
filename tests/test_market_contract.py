import unittest
from market_contract import validate_quote,session_for


class MarketContractTests(unittest.TestCase):
    def test_recent_receipt_does_not_rescue_stale_exchange_data(self):
        quote=dict(instrument='NSE:DEMO',provider='fixture',bid=100,ask=101,exchangeAt='2026-01-02T09:30:00+05:30',receivedAt='2026-01-02T09:35:00+05:30')
        with self.assertRaisesRegex(ValueError,'exchangeAt'):
            validate_quote(quote,instrument='NSE:DEMO',as_of='2026-01-02T09:35:00+05:30',max_age_seconds=15)
        quote['exchangeAt']=quote['receivedAt']
        self.assertEqual(validate_quote(quote,instrument='NSE:DEMO',as_of=quote['receivedAt'],max_age_seconds=15)['bid'],100)
        with self.assertRaises(ValueError):
            validate_quote(dict(quote,bid=102),instrument='NSE:DEMO',as_of=quote['receivedAt'],max_age_seconds=15)

    def test_missing_calendar_day_and_late_notice_fail_closed(self):
        calendar=dict(exchange='NSE',segment='EQ',source='https://example.invalid/fixture',availableAt='2026-01-01T00:00:00+05:30',sessions={'2026-01-02':None})
        self.assertFalse(session_for(calendar,date='2026-01-02',as_of='2026-01-02T09:00:00+05:30')['open'])
        with self.assertRaises(ValueError):session_for(calendar,date='2026-01-05',as_of='2026-01-05T09:00:00+05:30')
        with self.assertRaises(ValueError):session_for(calendar,date='2026-01-02',as_of='2025-12-31T09:00:00+05:30')

    def test_unknown_mapping_and_credentialed_source_rejected(self):
        quote=dict(provider='fixture',bid=100,ask=101,exchangeAt='2026-01-02T09:30:00+05:30',receivedAt='2026-01-02T09:30:00+05:30')
        with self.assertRaises(ValueError):
            validate_quote(quote,instrument=None,as_of=quote['receivedAt'],max_age_seconds=15)
        calendar=dict(exchange='NSE',segment='EQ',source='https://user:secret@example.invalid',availableAt=quote['receivedAt'],sessions={'2026-01-02':None})
        with self.assertRaises(ValueError):session_for(calendar,date='2026-01-02',as_of=quote['receivedAt'])
