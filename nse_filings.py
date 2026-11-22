"""NSE filing links from official RSS; no document download or text inference."""
import hashlib
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

HOSTS = frozenset(('nsearchives.nseindia.com', 'archives.nseindia.com',
                   'www.nseindia.com', 'www.nseindia.in'))


def safe_filing_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    if any(c.isspace() or not c.isprintable() for c in value) or '\\' in value:
        return None
    try:
        parts = urlsplit(value)
        if (parts.scheme != 'https' or parts.hostname not in HOSTS
                or parts.username is not None or parts.password is not None
                or parts.port not in (None, 443)
                or not parts.path.lower().endswith('.pdf')):
            return None
        return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, parts.query, ''))
    except ValueError:
        return None


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'a' and len(self.urls) < 20:
            self.urls.extend(value for key, value in attrs if key.lower() == 'href')


def filing_links(node, primary):
    links = Links()
    links.feed((node.findtext('description') or '')[:20000])
    candidates = [primary] + [row.get('url') for row in node.findall('enclosure')[:20]] + links.urls
    return list(dict.fromkeys(url for value in candidates
                              if (url := safe_filing_url(value))))[:10]


def document_type(summary):
    text = summary.casefold()
    for label, terms in (
        ('Financial results', ('financial results', 'quarterly results')),
        ('Annual report', ('annual report',)),
        ('Board meeting outcome', ('outcome of board meeting', 'board meeting outcome')),
        ('Board meeting notice', ('board meeting',)),
        ('Corporate action', ('dividend', 'buyback', 'bonus', 'stock split', 'rights issue')),
        ('Shareholding disclosure', ('shareholding', 'regulation 31')),
        ('Exchange filing', ())):
        if not terms or any(term in text for term in terms):
            return label


def filing_metadata(urls, summary, published, available):
    return [dict(id=hashlib.sha256(url.encode()).hexdigest(), url=url, format='PDF',
                 documentType=document_type(summary), publishedAt=published,
                 availableAt=available, contentStatus='linked-not-downloaded',
                 executionAllowed=False)
            for value in urls if (url := safe_filing_url(value))]
