import datetime as dt
import unittest
from unittest.mock import patch
from announcements import Announcements,parse_feed


class AnnouncementTests(unittest.TestCase):
    def test_nse_dates_duplicates_future_and_unsafe_links(self):
        item='<item><title>Demo &amp; Co</title><link>{}</link><description>Dividend</description><pubDate>{}</pubDate></item>'
        valid=item.format('https://nsearchives.nseindia.com/corporate/a.pdf','19-Nov-2026 10:00:00')
        raw=('<rss><channel>'+valid+valid+item.format('https://evil.invalid/a','19-Nov-2026 10:00:00')+item.format('https://nsearchives.nseindia.com/a','20-Nov-2026 10:00:00')+'</channel></rss>').encode()
        result=parse_feed(raw,dt.datetime.fromisoformat('2026-11-19T11:00:00+05:30'))
        self.assertEqual(len(result),1);self.assertEqual(result[0]['symbols'],[])
        self.assertEqual(result[0]['publishedAt'],'2026-11-19T10:00:00+05:30')

    def test_entities_and_oversized_rejected(self):
        for raw in (b'<!DOCTYPE rss><rss/>',b' '*3_000_001):
            with self.assertRaises(ValueError):parse_feed(raw,dt.datetime.now(dt.timezone.utc))

    def test_non_utf8_declarations_and_case_variants_rejected(self):
        body='<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title></item></channel></rss>'
        entity_only='<rss><!ENTITY a "b"></rss>'
        cases=[body.encode('utf-16'),body.encode('utf-16-le'),body.encode('utf-16-be'),body.replace('DOCTYPE','doctype').encode(),entity_only.encode(),entity_only.lower().encode(),b'<rss>\x00</rss>',b'<rss>\xff\xfe</rss>']
        for raw in cases:
            with self.subTest(raw=raw[:20]):
                with self.assertRaises(ValueError):parse_feed(raw,dt.datetime.now(dt.timezone.utc))

    def test_latin1_feed_parses_and_other_encodings_are_distinct_errors(self):
        now=dt.datetime.fromisoformat('2026-11-19T11:00:00+05:30')
        item='<item><title>Caf\xe9 Ltd dividend</title><link>https://nsearchives.nseindia.com/a.pdf</link><pubDate>19-Nov-2026 10:00:00</pubDate></item>'
        for enc in ('ISO-8859-1','windows-1252'):
            raw=('<?xml version="1.0" encoding="%s"?><rss><channel>%s</channel></rss>'%(enc,item)).encode('latin-1')
            self.assertEqual(parse_feed(raw,now)[0]['title'],'Caf\xe9 Ltd dividend')
        hostile=b'<?xml version="1.0" encoding="ISO-8859-1"?><!DOCTYPE rss [<!ENTITY a "b">]><rss>\xe9</rss>'
        with self.assertRaisesRegex(ValueError,'oversized'):parse_feed(hostile,now)
        for raw in (b'<?xml version="1.0" encoding="koi8-r"?><rss>\xe9</rss>',b'<rss>\xe9</rss>',b'<?xml version="1.0" encoding="utf-8"?><rss>\xe9</rss>',
                    '<?xml version="1.0" encoding="utf-16"?><rss/>'.encode('utf-16')):
            with self.subTest(raw=raw[:30]):
                with self.assertRaisesRegex(ValueError,'encoding'):parse_feed(raw,now)

    def test_failure_cached_and_old_evidence_explicitly_stale(self):
        feed=Announcements();feed.items=[dict(id='x',title='Demo',symbols=[])];feed.at='earlier'
        with patch('announcements.urllib.request.urlopen',side_effect=TimeoutError) as fetch:
            result=feed.status();feed.status()
        self.assertEqual(fetch.call_count,1);self.assertTrue(result['stale']);self.assertFalse(result['executionAllowed'])

    def test_mapping_requires_exact_nse_equity_and_valid_symbol(self):
        feed=Announcements();feed.checked=1;feed.items=[dict(id='x',title='Demo',symbols=[])];feed.error=None
        instruments=[dict(name='Demo',tradingsymbol='DEMO',exchange='NSE',instrument_type='EQ'),dict(name='Demo',tradingsymbol='DEMOfut',exchange='NSE',instrument_type='FUT')]
        with patch('announcements.time.monotonic',return_value=2):
            self.assertEqual(feed.status(instruments)['items'][0]['symbols'],['DEMO'])
            instruments[0]['exchange']='BSE'
            self.assertEqual(feed.status(instruments)['items'][0]['symbols'],[])

    def test_malformed_link_is_skipped_and_mixed_offsets_sort_chronologically(self):
        template='<item><title>Demo</title><link>{}</link><pubDate>{}</pubDate></item>'
        raw=('<rss><channel>'+template.format('https://[bad','19-Nov-2026 10:00:00')+template.format('https://nsearchives.nseindia.com/a','Thu, 19 Nov 2026 05:00:00 +0000')+template.format('https://nsearchives.nseindia.com/b','19-Nov-2026 10:00:00')+'</channel></rss>').encode()
        rows=parse_feed(raw,dt.datetime.fromisoformat('2026-11-19T11:00:00+05:30'))
        self.assertEqual(len(rows),2);self.assertTrue(rows[0]['url'].endswith('/a'))
