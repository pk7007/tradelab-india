"""Independent local observer survives an app stop; writes the local incident inbox."""
import argparse
import json
from pathlib import Path
import sys
import time
import uuid
from urllib import request
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from operational_alerts import OperationalAlerts, observe_service


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--database', required=True)
    args = parser.parse_args()
    parts = urlsplit(args.url)
    if (parts.scheme != 'http' or parts.hostname not in ('127.0.0.1', 'localhost')
            or parts.username or parts.password or parts.query or parts.fragment
            or parts.path != '/api/service-health' or not parts.port or not 1024 <= parts.port <= 65535):
        raise SystemExit('Only a local application health URL is allowed.')
    alerts = OperationalAlerts(args.database)
    opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
    owner = uuid.uuid4().hex
    failures = 0
    while alerts.lease(owner, time.time()):
        try:
            with opener.open(args.url, timeout=3) as response:
                raw = response.read(200001)
                if len(raw) > 200000:
                    raise ValueError('Health response too large.')
                payload = json.loads(raw)
                if payload.get('service') != 'tradelab-local':
                    raise ValueError('Unexpected health service.')
            observe_service(alerts, payload)
            failures = 0
            alerts.observe('app:unreachable', 'TradeLab is not responding. Restart the app and review paper exposure.', False)
        except Exception:
            failures += 1
            if failures >= 3:
                alerts.observe('app:unreachable', 'TradeLab is not responding. Restart the app and review paper exposure.', True, severity='critical')
        time.sleep(30)


if __name__ == '__main__':
    main()
