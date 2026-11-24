"""Unique, descriptive <title> per route for pages that share one HTML template."""
import html
import re

TITLES = {
    '/auto-trading': 'Auto Trading · TradeLab India',
    '/intraday': 'Intraday paper session · TradeLab India',
    '/long-term': 'Long-term research · TradeLab India',
}


def apply(page, route):
    title = TITLES.get(route)
    if title is None:
        return page
    return re.sub(r'<title>.*?</title>', lambda _: '<title>%s</title>' % html.escape(title), page, count=1, flags=re.S)
