"""Read-only supervision helpers: report paper exposure, raise incidents, check for phantom fills.

Nothing here places an order, changes a limit, logs in, or arms anything. It only reads the paper
ledger and writes the local incident inbox, so a failure here can never stop exits, square-off,
exposure reporting or reconciliation (callers treat it as best effort).
"""
import json
import logging

LOG = logging.getLogger(__name__)
EXPOSED_KEY = 'paper:exposed'
LOGIN_KEY = 'paper:token-loss'


def exposure_report(engine):
    """Accounts that still hold a modelled position or a pending order."""
    report = []
    with engine.db() as db:
        for row in db.execute('SELECT body FROM accounts').fetchall():
            account = json.loads(row[0])
            if account.get('quantity') or account.get('pending'):
                reconciled = engine.reconcile_in(db, account)
                report.append(dict(accountId=account['id'], symbol=account['config'].get('symbol'),
                                   quantity=account.get('quantity') or 0,
                                   pendingSide=(account.get('pending') or {}).get('side'),
                                   lastBar=account.get('lastBar'), squareOff=account['config'].get('squareOff'),
                                   reconciled=bool(reconciled['matches'])))
    return report


def observe_exposure(alerts, engine, *, now=None):
    """Keep a critical incident open while any paper exposure exists; resolve it when flat."""
    report = exposure_report(engine)
    names = ', '.join('%s x%s' % (r['symbol'], r['quantity']) for r in report)[:300]
    alerts.observe(EXPOSED_KEY, 'Open paper exposure (%s). Protective exits need accepted candles: reconnect '
                   'Zerodha and re-arm recovery, then review the ledger.' % names if report else 'No open paper exposure.',
                   bool(report), severity='critical', now=now)
    return report


def phantom_fills(engine, account_id):
    """Ledger fills that have no accepted candle behind them (there should be none)."""
    with engine.db() as db:
        accepted = {row[0] for row in db.execute('SELECT stamp FROM bars WHERE account=?', (account_id,))}
        fills = [json.loads(row[0]) for row in db.execute('SELECT body FROM events WHERE account=? ORDER BY seq', (account_id,))]
    return [event for event in fills if event.get('type') == 'fill' and event.get('bar') not in accepted]


def startup_scan(alerts, engine):
    """At process start, leave a durable incident if exposure survived a restart. Never raises."""
    try:
        return bool(observe_exposure(alerts, engine))
    except Exception as error:
        LOG.warning('Startup exposure scan failed (%s); check the ledger manually.', type(error).__name__)
        return False
