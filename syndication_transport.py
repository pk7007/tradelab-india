"""Opt-in licensed feed configuration and bounded HTTP transport.

This module has no environment reads, scheduler or application activation.
Callers supply provisioned settings and retain SyndicationCache rate limiting.
"""
from dataclasses import dataclass, field
import ipaddress
import json
import re
from urllib import error, request
from urllib.parse import urlencode, urlsplit

from syndication import stamp

MAX_BYTES = 3_000_000
TIMEOUT_SECONDS = 10


def credential(value):
    return (isinstance(value, str) and 1 <= len(value) <= 4096
            and all(33 <= ord(character) <= 126 for character in value)
            and not any(marker in value.casefold() for marker in
                        ('your_', 'mock_', 'placeholder', '<', '>')))


@dataclass(frozen=True)
class FeedConfiguration:
    base_url: str
    approved_host: str
    api_key: str = field(repr=False)
    client_id: str = field(repr=False)

    @classmethod
    def from_mapping(cls, settings):
        """Validate supplied settings without fetching or displaying secrets."""
        base = settings.get('SYNDICATION_BASE_URL', '')
        approved = settings.get('SYNDICATION_APPROVED_HOST', '')
        key = settings.get('SYNDICATION_API_KEY', '')
        client = settings.get('SYNDICATION_CLIENT_ID', '')
        if not all(isinstance(value, str) for value in (base, approved, key, client)):
            raise ValueError('Licensed feed settings must be text.')
        if not all((base, approved, key, client)):
            raise ValueError('Licensed feed provisioning is incomplete.')
        try:
            parts = urlsplit(base)
            hostname = parts.hostname
            valid_host = bool(hostname and re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', hostname))
            if hostname:
                try:
                    ipaddress.ip_address(hostname)
                except ValueError:
                    pass
                else:
                    valid_host = False
            if (parts.scheme != 'https' or not valid_host
                    or hostname != approved or hostname in ('localhost',)
                    or any(word in hostname for word in ('example', 'placeholder'))
                    or hostname.endswith(('.invalid', '.test'))
                    or parts.port not in (None, 443)
                    or parts.username is not None or parts.password is not None
                    or parts.query or parts.fragment or '?' in base or '#' in base
                    or not re.fullmatch(r'(?:/[A-Za-z0-9_-]+)*/?', parts.path)):
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError('Use the provisioned HTTPS URL and exact approved host.') from None
        if not credential(key) or not credential(client):
            raise ValueError('Licensed feed credentials are missing or invalid.')
        return cls(base.rstrip('/'), approved, key, client)


def configuration_status(settings):
    """Only static readiness is reported; no credentials or feed text are returned."""
    try:
        FeedConfiguration.from_mapping(settings)
    except ValueError:
        return dict(configured=False, status='blocked-configuration', connected=False,
                    executionAllowed=False)
    return dict(configured=True, status='awaiting-provider-verification', connected=False,
                executionAllowed=False)


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise error.URLError('Licensed feed redirects are disabled.')


class FeedTransport:
    def __init__(self, configuration, opener=None):
        # Validate direct dataclass construction as well as from_mapping callers.
        self.config = FeedConfiguration.from_mapping(dict(
            SYNDICATION_BASE_URL=configuration.base_url,
            SYNDICATION_APPROVED_HOST=configuration.approved_host,
            SYNDICATION_API_KEY=configuration.api_key,
            SYNDICATION_CLIENT_ID=configuration.client_id))
        self.opener = opener or request.build_opener(request.ProxyHandler({}), NoRedirect())

    def __call__(self, endpoint, params):
        if endpoint not in ('/feeds/news', '/feeds/revisions'):
            raise ValueError('Unsupported licensed feed endpoint.')
        allowed = {'since', 'limit'} if endpoint == '/feeds/news' else {'since'}
        if not isinstance(params, dict) or set(params) - allowed or 'since' not in params:
            raise ValueError('Unsupported licensed feed parameters.')
        stamp(params['since'])
        if 'limit' in params and (type(params['limit']) is not int or not 1 <= params['limit'] <= 50):
            raise ValueError('Licensed news page limit must be between one and fifty.')
        url = self.config.base_url + endpoint + '?' + urlencode(params)
        outgoing = request.Request(url, headers={
            'X-MC-Syndication-Key': self.config.api_key,
            'X-Client-ID': self.config.client_id,
            'Accept': 'application/json',
            'Accept-Encoding': 'identity',
        })
        try:
            with self.opener.open(outgoing, timeout=TIMEOUT_SECONDS) as response:
                if response.geturl() != url or response.status != 200:
                    raise ValueError('Unexpected licensed feed response.')
                raw = response.read(MAX_BYTES + 1)
        except error.HTTPError as exc:
            exc.close()
            raise ValueError('Licensed feed request failed.') from None
        except (error.URLError, OSError):
            raise ValueError('Licensed feed request failed.') from None
        if len(raw) > MAX_BYTES:
            raise ValueError('Licensed feed response exceeds the size limit.')
        try:
            payload = json.loads(raw.decode('utf-8'), parse_constant=reject_constant)
        except (ValueError, UnicodeError):
            raise ValueError('Licensed feed returned invalid JSON.') from None
        if not isinstance(payload, dict):
            raise ValueError('Licensed feed response must be an object.')
        return payload


def reject_constant(value):
    raise ValueError('Non-finite JSON number.')
