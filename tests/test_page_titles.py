import re
import unittest
from pathlib import Path

import page_titles

WEB = Path(__file__).resolve().parents[1] / 'web'


class PageTitleTests(unittest.TestCase):
    def test_shared_portal_template_gets_a_unique_title_per_route(self):
        template = (WEB / 'portal.html').read_text(encoding='utf-8')
        titles = {}
        for route in ('/auto-trading', '/intraday', '/long-term', '/'):
            page = page_titles.apply(template, route)
            titles[route] = re.search(r'<title>(.*?)</title>', page).group(1)
            self.assertEqual(len(re.findall(r'<title>', page)), 1)
        self.assertEqual(len({titles['/auto-trading'], titles['/intraday'], titles['/long-term']}), 3)
        self.assertNotEqual(titles['/intraday'], titles['/long-term'])
        self.assertNotEqual(titles['/auto-trading'], titles['/long-term'])
        self.assertTrue(all('TradeLab' in title for title in titles.values()))

    def test_other_routes_and_text_are_left_alone_and_titles_are_escaped(self):
        page = '<head><title>Original</title></head><body>x</body>'
        self.assertEqual(page_titles.apply(page, '/advanced'), page)
        self.assertEqual(page_titles.apply(page, '/nope'), page)
        self.assertIn('<body>x</body>', page_titles.apply(page, '/intraday'))

    def test_every_html_page_has_a_skip_link_target_and_a_main_id(self):
        for name in ('portal.html', 'index.html', 'paper.html', 'evaluation.html', 'trader.html'):
            text = (WEB / name).read_text(encoding='utf-8')
            self.assertIn('href="#main"', text, name)
            self.assertRegex(text, r'<main id="main"', name)

    def test_icon_only_navigation_has_text_labels(self):
        text = (WEB / 'index.html').read_text(encoding='utf-8')
        buttons = re.findall(r'<button class="nav-item[^>]*>', text)
        self.assertTrue(buttons)
        for button in buttons:
            self.assertRegex(button, r'title="[^"]+"')
            self.assertRegex(button, r'aria-label="[^"]+"')


if __name__ == '__main__':
    unittest.main()
