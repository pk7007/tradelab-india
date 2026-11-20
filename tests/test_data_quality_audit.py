"""Synthetic audit regression fixtures; no licensed market data."""
import unittest

from scripts.data_quality_audit import audit_rows, expected_starts, session_spec


def candles(day, cas=None):
    return [dict(date=stamp.isoformat(), open=100, high=102, low=99, close=101, volume=10)
            for stamp in expected_starts(day, session_spec(day, cas)[0])]


class DataQualityAuditTests(unittest.TestCase):
    def test_cas_is_explicit_and_date_sensitive(self):
        before = audit_rows(candles("2026-07-31"), "2026-08-03")
        after = audit_rows(candles("2026-08-03", "2026-08-03"), "2026-08-03")
        self.assertEqual(before["rows"], 75)
        self.assertEqual(after["rows"], 72)
        self.assertEqual(after["completeSessions"], 1)
        self.assertEqual(after["legacyExcludedClassification"], {"cas_cts": 1})
        self.assertEqual(audit_rows(candles("2026-08-03", "2026-08-03"))["missingBars"], 3)

    def test_all_nine_special_sessions_have_exact_windows(self):
        counts = {"2023-11-12":12, "2024-01-20":75, "2024-03-02":21,
                  "2024-05-18":21, "2024-11-01":12, "2025-02-01":75,
                  "2025-10-21":12, "2026-02-01":75, "2026-11-08":11}
        for day, count in counts.items():
            with self.subTest(day=day):
                report = audit_rows(candles(day, "2026-08-03"), "2026-08-03")
                self.assertEqual(report["rows"], count)
                self.assertEqual(report["completeSessions"], 1)
                self.assertEqual(report["missingBars"], 0)
                self.assertEqual(report["unexpectedBars"], 0)

    def test_missing_duplicate_and_unexpected_are_distinct(self):
        rows = candles("2026-07-31")
        rows.pop(1)
        rows.append(dict(rows[-1]))
        rows.append(dict(rows[-1], date="2026-07-31T15:30:00+05:30"))
        report = audit_rows(rows)
        self.assertEqual(report["missingBars"], 1)
        self.assertEqual(report["unexpectedBars"], 1)
        self.assertEqual(report["rowIssues"]["duplicate_timestamp"], 1)
        self.assertEqual(report["completeSessions"], 0)

    def test_malformed_zero_nonfinite_and_ohlc_are_reported(self):
        rows = candles("2026-07-31")[:5]
        rows[0]["volume"] = 0
        rows[1]["close"] = "nan"
        rows[2]["high"] = 1
        rows[3]["open"] = "bad"
        rows[4]["date"] = "2026-07-31T09:35:00"
        issues = audit_rows(rows)["rowIssues"]
        self.assertEqual(issues, dict(zero_volume=1, nonfinite_numeric=1,
                                     invalid_ohlc=1, malformed_numeric=1, malformed_timestamp=1))

    def test_unknown_weekend_is_not_invented_as_session(self):
        report = audit_rows([dict(date="2026-11-14T09:15:00+05:30", open=1, high=1, low=1, close=1, volume=1)])
        self.assertEqual(report["sessions"][0]["kind"], "unverified_weekend")
        self.assertEqual(report["completeSessions"], 0)


if __name__ == "__main__":
    unittest.main()
