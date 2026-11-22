import unittest
from unittest.mock import Mock
from urllib import error
from urllib.parse import parse_qs, urlsplit

from syndication_transport import (
    FeedConfiguration, FeedTransport, MAX_BYTES, NoRedirect, configuration_status,
)


SETTINGS = dict(SYNDICATION_BASE_URL='https://licensed.publisher.net/v1',
                SYNDICATION_APPROVED_HOST='licensed.publisher.net',
                SYNDICATION_API_KEY='fixture-secret', SYNDICATION_CLIENT_ID='fixture-client')


class FeedTransportTests(unittest.TestCase):
    def transport(self, body=b'{"items":[],"cursor":"2026-11-20T06:30:00Z"}'):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status = 200
        response.read.return_value = body
        opener = Mock()
        opener.open.side_effect = lambda req, timeout: (setattr(response, 'geturl', lambda: req.full_url) or response)
        return FeedTransport(FeedConfiguration.from_mapping(SETTINGS), opener), opener, response

    def test_headers_cursor_limit_and_bounded_read(self):
        transport, opener, response = self.transport()
        transport('/feeds/news', dict(since='2026-11-20T06:00:00Z', limit=50))
        req = opener.open.call_args.args[0]
        self.assertEqual(req.get_header('X-mc-syndication-key'), 'fixture-secret')
        self.assertEqual(req.get_header('X-client-id'), 'fixture-client')
        self.assertEqual(parse_qs(urlsplit(req.full_url).query)['since'], ['2026-11-20T06:00:00Z'])
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 10)
        response.read.assert_called_once_with(MAX_BYTES + 1)

    def test_invalid_configuration_and_redacted_readiness(self):
        invalid = ('http://licensed.publisher.net/v1',
                   'https://other.publisher.net/v1',
                   'https://user:pass@licensed.publisher.net/v1',
                   'https://licensed.publisher.net/v1?key=secret',
                   'https://licensed.publisher.net/../private',
                   'https://licensed.publisher.net/v1%2fprivate')
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(ValueError):
                FeedConfiguration.from_mapping(dict(SETTINGS, SYNDICATION_BASE_URL=url))
        for key, value in [('SYNDICATION_API_KEY', ''), ('SYNDICATION_API_KEY', 'secret\r\nX-Bad: yes'),
                           ('SYNDICATION_BASE_URL', 'https://sandbox.example-network18.internal/v1')]:
            self.assertFalse(configuration_status(dict(SETTINGS, **{key: value}))['configured'])
        status = configuration_status(SETTINGS)
        self.assertTrue(status['configured'])
        self.assertFalse(status['connected'])
        self.assertNotIn('fixture-secret', repr(status))
        self.assertNotIn('fixture-secret', repr(FeedConfiguration.from_mapping(SETTINGS)))

    def test_redirects_rejected_before_credentials_can_be_forwarded(self):
        with self.assertRaises(error.URLError):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'https://attacker.net/')
        transport, opener, _ = self.transport()
        opener.open.side_effect = error.URLError('private URL and fixture-secret')
        with self.assertRaisesRegex(ValueError, '^Licensed feed request failed.$'):
            transport('/feeds/revisions', dict(since='2026-11-20T06:00:00Z'))

    def test_bad_endpoint_parameters_and_payloads_do_not_escape_bounds(self):
        transport, opener, _ = self.transport()
        for endpoint, params in [('/feeds/news/article', {}), ('/feeds/news', {'since': 'naive'}),
                                 ('/feeds/revisions', {'since': '2026-11-20T06:00:00Z', 'limit': 50}),
                                 ('/feeds/news', {'since': '2026-11-20T06:00:00Z', 'limit': True})]:
            with self.assertRaises(ValueError):
                transport(endpoint, params)
        opener.open.assert_not_called()
        for payload in (b'[]', b'{"number":NaN}', b'invalid', b'x' * (MAX_BYTES + 1)):
            transport, _, _ = self.transport(payload)
            with self.assertRaises(ValueError):
                transport('/feeds/revisions', dict(since='2026-11-20T06:00:00Z'))
