import unittest
from unittest import mock

from scripts import weekly_digest

SOURCE = dict(name="Demo", feed_url="https://example.com/feed.xml", category="Test")
ENTITY_FEED = b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title><link>https://example.com/1</link></item></channel></rss>'


class WeeklyDigestSafetyTests(unittest.TestCase):
    def test_feed_with_doctype_or_entities_is_rejected(self):
        with self.assertRaises(ValueError):
            weekly_digest.parse_feed(ENTITY_FEED, SOURCE)

    def test_non_https_feed_url_is_never_opened(self):
        with mock.patch.object(weekly_digest.urllib.request, "urlopen") as opener:
            with self.assertRaises(ValueError):
                weekly_digest.fetch(dict(SOURCE, feed_url="file:///etc/passwd"))
        opener.assert_not_called()

    def test_non_utf8_and_case_variants_are_rejected(self):
        body = '<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title></item></channel></rss>'
        entity_only = '<rss><!ENTITY a "b"></rss>'
        cases = [body.encode("utf-16"), body.encode("utf-16-le"), body.encode("utf-16-be"), body.replace("DOCTYPE", "doctype").encode(),
                 entity_only.encode(), entity_only.lower().encode(), b"<rss>\x00</rss>", b"<rss>\xff\xfe</rss>"]
        for raw in cases:
            with self.subTest(raw=raw[:20]):
                with self.assertRaises(ValueError):
                    weekly_digest.parse_feed(raw, SOURCE)

    def test_valid_feed_still_parses(self):
        raw = b'<?xml version="1.0" encoding="UTF-8"?><rss><channel><item><title>T</title><link>https://example.com/1</link></item></channel></rss>'
        self.assertEqual(len(weekly_digest.parse_feed(raw, SOURCE)), 1)

    def test_non_https_final_url_is_rejected(self):
        class Response:
            url = "http://example.com/feed.xml"
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size): return b"<rss/>"
        with mock.patch.object(weekly_digest.urllib.request, "urlopen", return_value=Response()):
            with self.assertRaises(ValueError):
                weekly_digest.fetch(SOURCE)


if __name__ == "__main__":
    unittest.main()
