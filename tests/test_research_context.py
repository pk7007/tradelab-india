import unittest
from research_context import attach_announcements


class ContextTests(unittest.TestCase):
    def test_current_context_excludes_future_old_and_unmapped(self):
        item=dict(title='Fixture',url='https://example.invalid/a',publishedAt='2026-11-20T10:00:00+05:30',availableAt='2026-11-20T10:01:00+05:30',symbols=['TCS'])
        feed=dict(status='fetched',stale=False,items=[item,dict(item,symbols=[]),dict(item,availableAt='2026-11-21T10:00:00+05:30'),dict(item,publishedAt='2026-11-18T10:00:00+05:30')])
        request=dict(asOf='2026-11-20T10:05:00+05:30')
        values,status=attach_announcements(request,feed)
        self.assertEqual(len(values['records']),1);self.assertEqual(status['attached'],1)
        self.assertNotIn('records',request)
        values,status=attach_announcements(dict(asOf='2026-01-02T10:00:00+05:30'),feed)
        self.assertEqual(values['records'],[])

    def test_outage_does_not_attach_stale_feed(self):
        values,status=attach_announcements(dict(asOf='2026-11-20T10:05:00+05:30'),dict(status='unavailable',stale=True,items=[{}]))
        self.assertEqual(values['records'],[]);self.assertTrue(status['stale'])
