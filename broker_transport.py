"""Credentialed Kite HTTP policy: fixed HTTPS origin, no redirects, bounded JSON."""
import json
import urllib.parse
import urllib.request


class NoBrokerRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_json(request):
    address = request.full_url
    parsed = urllib.parse.urlsplit(address)
    if (parsed.scheme != 'https' or parsed.hostname != 'api.kite.trade'
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443) or parsed.fragment
            or not parsed.path.startswith('/') or '\\' in address
            or any(not char.isprintable() or char.isspace() for char in address)):
        raise ValueError('Broker destination is not the approved HTTPS origin.')
    opener = urllib.request.build_opener(NoBrokerRedirect())
    with opener.open(request, timeout=15) as response:
        if response.geturl() != address:
            raise ValueError('Broker response changed its destination.')
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('Broker response exceeds the supported size.')
        return json.loads(raw.decode('utf-8'))
