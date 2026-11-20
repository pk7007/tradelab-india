import unittest
import csv
import datetime as dt
from pathlib import Path
import tempfile

from intraday_evaluation import evaluate_intraday
from test_intraday_paper import CONFIG, bars
from scripts.paper_research_batch import run


class CalendarEvidenceTests(unittest.TestCase):
    def test_legacy_runner_cannot_silently_discard_complete_72_bar_days(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'fixture.csv'
            day=dt.date(2026,8,3)
            days=0
            with source.open('w',newline='',encoding='utf-8') as handle:
                writer=csv.DictWriter(handle,fieldnames=['date','open','high','low','close','volume'])
                writer.writeheader()
                while days<80:
                    if day.weekday()<5:
                        for row in bars(72):
                            writer.writerow(dict(row,date=day.isoformat()+row['date'][10:]))
                        days+=1
                    day+=dt.timedelta(days=1)
            with self.assertRaisesRegex(ValueError,'legacy 75-bar partition is unsafe'):
                run(source,CONFIG,Path(folder)/'result')

    def test_calendar_changes_fingerprint_even_with_same_fills(self):
        calendar=dict(exchange='NSE',segment='EQ',version='fixture-v1',
                      source='https://example.invalid/sessions',availableAt='2026-01-01T00:00:00+05:30',
                      sessions={'2026-01-02':dict(open='2026-01-02T09:15:00+05:30',close='2026-01-02T15:30:00+05:30')})
        request=dict(permitted=True,config=CONFIG,bars=bars(23),calendar=calendar)
        first=evaluate_intraday(request)
        second=evaluate_intraday(dict(request,calendar=dict(calendar,version='fixture-v2')))
        self.assertEqual(first['fills'],second['fills'])
        self.assertNotEqual(first['fingerprint'],second['fingerprint'])
        self.assertNotEqual(first['calendarFingerprint'],second['calendarFingerprint'])
        self.assertEqual(len(first['implementationHashes']),4)
