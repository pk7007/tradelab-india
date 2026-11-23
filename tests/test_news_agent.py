import datetime as dt
from pathlib import Path
import tempfile
import unittest
from xml.sax.saxutils import escape

from news_agent import FEEDS, NewsAgent, parse_et, parse_google, plain_text


NOW = dt.datetime(2026, 11, 20, 10, tzinfo=dt.timezone.utc)


def feed(title="Nifty rises as RBI holds repo rate", summary="Market update", link=None,
         date="Fri, 20 Nov 2026 09:00:00 +0000"):
    link = link or "https://economictimes.indiatimes.com/markets/stocks/news/demo.cms"
    return ("<rss><channel><item><title>" + escape(title) + "</title><description>" + escape(summary)
            + "</description><link>" + escape(link) + "</link><pubDate>" + date
            + "</pubDate></item></channel></rss>").encode()


class NewsAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "news.sqlite"
        self.raw = feed()

    def agent(self, **kwargs):
        return NewsAgent(self.path, sources=("et",), fetch=lambda url: self.raw,
                         clock=lambda: NOW, **kwargs)

    def test_restart_dedup_changed_content_and_durable_first_seen(self):
        original = self.agent().poll_once()["items"][0]
        self.assertEqual(self.agent().poll_once()["items"], [])
        self.raw = feed(summary="Corrected summary")
        later = self.agent()
        later.clock = lambda: NOW + dt.timedelta(minutes=5)
        updated = later.poll_once()["items"][0]
        self.assertEqual(updated["change"], "updated")
        self.assertEqual(updated["firstSeenAt"], original["firstSeenAt"])
        self.assertNotEqual(updated["receivedAt"], original["receivedAt"])
        self.assertFalse(updated["executionAllowed"])

    def test_watchlist_phrase_boundaries_and_market_inclusion(self):
        self.raw = feed(title="ITC announces dividend", summary="Company disclosure")
        item = self.agent(watchlist=("ITC",)).poll_once()["items"][0]
        self.assertEqual(item["textMatches"], ["itc"])
        self.assertEqual(item["categories"], ["corporate actions"])
        self.raw = feed(title="Switching services expand", summary="")
        self.assertEqual(self.agent(watchlist=("ITC",)).poll_once()["items"], [])
        self.raw = feed()
        self.assertEqual(self.agent(watchlist=("ITC",)).poll_once()["items"], [])
        self.assertEqual(len(self.agent(watchlist=("ITC",), include_market=True).poll_once()["items"]), 1)

    def test_unsafe_future_naive_and_invalid_items_skipped(self):
        for raw in (feed(link="https://evil.invalid/a"), feed(link="https://[bad"),
                    feed(link="https://user@economictimes.indiatimes.com/a"),
                    feed(date="Fri, 20 Nov 2026 11:00:00 +0000"),
                    feed(date="Fri, 20 Nov 2026 09:00:00"), feed(date="invalid")):
            self.assertEqual(parse_et(raw, NOW), [])
        for raw in (b"<!DOCTYPE rss><rss/>", b" " * 3_000_001, b"<html/>", "<rss><channel/></rss>".encode("utf-16")):
            with self.assertRaises(ValueError):
                parse_et(raw, NOW)

    def test_rss_channel_accepts_latin1_and_reports_encoding_error_name(self):
        from news_agent import rss_channel
        self.assertEqual(rss_channel('<?xml version="1.0" encoding="ISO-8859-1"?><rss><channel><title>Caf\xe9</title></channel></rss>'.encode("latin-1")).find("channel/title").text, "Caf\xe9")
        with self.assertRaises(ValueError) as caught:
            rss_channel(b'<?xml version="1.0" encoding="koi8-r"?><rss>\xe9</rss>')
        self.assertEqual(type(caught.exception).__name__, "FeedEncodingError")

    def test_old_items_filtered_and_summary_is_plain_text(self):
        self.raw = feed(date="Wed, 18 Nov 2026 09:00:00 +0000")
        self.assertEqual(self.agent().poll_once()["items"], [])
        self.raw = feed(summary="<b>RBI</b> update")
        row = self.agent().poll_once()["items"][0]
        self.assertNotIn("<b>", row["summary"])
        self.assertNotIn("\x1b", row["summary"])
        self.assertNotIn("\x1b", plain_text("test\x1b[31m", 100))

    def test_source_failure_does_not_hide_success_and_no_fake_cached_news(self):
        def fetch(url):
            if "nsearchives" in url:
                raise TimeoutError("private transport details")
            return feed()
        agent = NewsAgent(self.path, fetch=fetch, clock=lambda: NOW)
        result = agent.poll_once()
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["sources"][0]["stale"])
        self.assertNotIn("private transport details", str(result))
        self.assertEqual(len(result["items"]), 1)
        agent.fetch = lambda url: b"<invalid"
        failed = agent.poll_once()
        self.assertEqual(failed["status"], "unavailable")
        self.assertEqual(failed["items"], [])

    def test_nse_reader_used_and_duplicate_items_only_emitted_once(self):
        self.raw = feed(title="Demo Limited", summary="Dividend",
                        link="https://nsearchives.nseindia.com/corporate/demo.pdf",
                        date="20-Nov-2026 14:00:00")
        self.raw = self.raw.replace(b"</channel>", self.raw.split(b"<channel>")[1].split(b"</channel>")[0] + b"</channel>")
        agent = NewsAgent(self.path, sources=("nse",), fetch=lambda url: self.raw, clock=lambda: NOW)
        self.assertEqual(len(agent.poll_once()["items"]), 1)
        self.assertEqual(agent.poll_once()["items"], [])

    def test_state_contains_no_article_text(self):
        self.agent().poll_once()
        self.assertNotIn(b"Nifty", self.path.read_bytes())

    def test_google_source_uses_supplied_search_and_preserves_publisher(self):
        self.raw = feed(title="Reliance shares rise - Demo News",
                        summary='<a href="https://news.google.com/rss/articles/demo">Reliance shares rise</a>',
                        link="https://news.google.com/rss/articles/demo?oc=5")
        self.raw = self.raw.replace(b"</item>", b'<source url="https://example.com">Demo News</source></item>')
        requested = []

        def fetch(url):
            requested.append(url)
            return self.raw

        agent = NewsAgent(self.path, sources=("google",), fetch=fetch, clock=lambda: NOW,
                          watchlist=("Reliance",))
        item = agent.poll_once()["items"][0]
        self.assertEqual(requested, [FEEDS["google"][1]])
        self.assertIn("q=RELIANCE+stock+OR+NSE&hl=en-IN&gl=IN&ceid=IN:en", requested[0])
        self.assertEqual(item["source"], "google")
        self.assertEqual(item["publisher"], "Demo News")
        self.assertEqual(item["summary"], "Reliance shares rise")
        self.assertTrue(item["url"].startswith("https://news.google.com/"))
        self.assertEqual(agent.poll_once()["items"], [])

    def test_google_rejects_other_hosts_bad_dates_and_unsafe_xml(self):
        for raw in (feed(), feed(link="https://news.google.com.evil.invalid/a"),
                    feed(link="https://user@news.google.com/a"),
                    feed(link="https://news.google.com/a", date="invalid"),
                    feed(link="https://news.google.com/a", date="Fri, 20 Nov 2026 11:00:00 +0000")):
            self.assertEqual(parse_google(raw, NOW), [])
        for raw in (b"<!DOCTYPE rss><rss/>", b" " * 3_000_001, b"<html/>"):
            with self.assertRaises(ValueError):
                parse_google(raw, NOW)


if __name__ == "__main__":
    unittest.main()
