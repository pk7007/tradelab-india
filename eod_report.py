"""Read-only end-of-day and weekly paper report.

Reads the paper ledger through a read-only SQLite connection and (optionally) the incident inbox. It never constructs
the paper engine (that would pause running accounts), places no order, logs in nowhere and uses no network. A failed
check is reported as FAILED, a day without candles as NO DATA (never PASS), and no profitability is ever claimed:
the P&L is the modelled paper result of the saved fill model, not evidence of an edge.
"""
import contextlib
import datetime as dt
import json
import sqlite3
from pathlib import Path

from paper import PaperEngine

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
PNL_BASIS = 'modelled paper result at the last accepted close'
DISCLAIMER = [
    'No profitability is established or implied. The P&L below is a modelled paper result and says nothing about edge.',
    'No live-readiness is established. This report cannot authorise broker orders, strategy promotion or changed limits.',
    'Fills are modelled at the next accepted candle open with the saved cost and slippage assumptions.',
]


def _day(value):
    try:
        return dt.date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise ValueError('Day must be an ISO date (YYYY-MM-DD).') from None


def _readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5)


def _open_incidents(alerts_path):
    if not alerts_path:
        return []
    try:
        with contextlib.closing(_readonly(alerts_path)) as db:
            return [row[0] for row in db.execute('SELECT message FROM incidents WHERE resolved_at IS NULL ORDER BY first_seen')]
    except sqlite3.Error:
        return ['The incident inbox could not be read.']


def _event_day(event, stamp):
    anchor = event.get('bar') or event.get('signalAt')
    if anchor:
        return str(anchor)[:10]
    return dt.datetime.fromisoformat(stamp).astimezone(IST).date().isoformat()


def _account(db, state, day):
    config = state['config']
    events = [(row['seq'], row['at'], json.loads(row['body'])) for row in
              db.execute('SELECT seq,at,body FROM events WHERE account=? ORDER BY seq', (state['id'],))]
    stamps = {row[0]: json.loads(row[1]) for row in db.execute('SELECT stamp,body FROM bars WHERE account=?', (state['id'],))}
    equities = [(event['bar'][:10], event['equity']) for _, _, event in events if event['type'] == 'bar']
    before = [value for date, value in equities if date < day]
    today = [value for date, value in equities if date == day]
    start = before[-1] if before else config['capital']
    end = today[-1] if today else start
    fills, abstentions, notes, failures = [], [], [], []
    for _, at, event in events:
        if _event_day(event, at) != day:
            continue
        kind = event['type']
        if kind == 'fill':
            candle = stamps.get(event.get('bar'))
            raw = candle['open'] if candle else None
            side, price, quantity = event['side'], event['price'], event['quantity']
            slip = None if not raw else ((price / raw - 1) if side == 'BUY' else (1 - price / raw)) * 10000
            fills.append(dict(bar=event['bar'], side=side, quantity=quantity, price=price, fee=event['fee'], rawOpen=raw,
                              slippageBps=slip, slippageCost=None if raw is None else quantity * abs(price - raw)))
            if candle is None:
                failures.append('%s: a fill at %s has no accepted candle behind it (fill without an accepted candle).' % (config['symbol'], event['bar']))
            elif abs(slip - config.get('slippageBps', 0)) > 1e-6:
                failures.append('%s: slippage on the %s fill (%.4f bps) differs from the saved model (%s bps).'
                                % (config['symbol'], event['bar'], slip, config.get('slippageBps', 0)))
        elif kind in ('rejected', 'skipped'):
            abstentions.append(dict(kind=kind, side=event.get('side'), bar=event.get('bar') or event.get('signalAt'), reason=event.get('reason')))
        elif kind in ('restart', 'entry-review-invalidated'):
            notes.append('%s: %s' % (kind, event.get('detail') or event.get('reason') or ''))
    reconciled = bool(PaperEngine.reconcile_in(None, db, state)['matches'])
    if not reconciled:
        failures.append('%s: the ledger does not reconcile with the saved account state.' % config['symbol'])
    feed_error = (state.get('feed') or {}).get('lastError')
    if feed_error:
        failures.append('%s: the candle feed reported an error: %s' % (config['symbol'], str(feed_error)[:200]))
    last_bar_day = (state.get('lastBar') or '')[:10]
    if state.get('quantity') and config.get('overnight') is False and last_bar_day == day:
        failures.append('%s: an intraday position is still open after the last candle (square-off did not complete).' % config['symbol'])
    candles = sum(1 for date, _ in equities if date == day)
    return dict(accountId=state['id'], symbol=config['symbol'], strategy=config.get('strategy'), status=state.get('status'),
                candles=candles, quantity=state.get('quantity') or 0, equity=end, fees=sum(f['fee'] for f in fills),
                feesToDate=state.get('fees', 0), realizedToDate=state.get('realized', 0), reconciled=reconciled,
                pnl=dict(basis=PNL_BASIS, startEquity=start, endEquity=end, change=end - start),
                fills=fills, abstentions=abstentions, notes=notes, failures=failures,
                slippageCost=sum(f['slippageCost'] or 0 for f in fills)), failures


def build(db_path, day, *, alerts_path=None, alerts_required=False):
    day = _day(day)
    base = dict(day=day, accounts=[], failures=[], notes=[], claimsProfitability=False, disclaimer=list(DISCLAIMER))
    if not Path(db_path).exists():
        return dict(base, status='FAILED', failures=['Paper database not found.'])
    failures = []
    try:
        with contextlib.closing(_readonly(db_path)) as db:
            db.row_factory = sqlite3.Row
            for row in db.execute('SELECT body FROM accounts ORDER BY rowid'):
                account, found = _account(db, json.loads(row['body']), day)
                base['accounts'].append(account)
                failures.extend(found)
    except sqlite3.Error as error:
        return dict(base, status='FAILED', failures=['Paper database could not be read (%s).' % type(error).__name__])
    if alerts_path is None or not Path(alerts_path).exists():
        if alerts_required:
            failures.append('The requested incident inbox was not found, so incidents could not be checked.')
        else:
            base['notes'].append('Incident inbox not checked (no inbox file found).')
    else:
        failures.extend('Open incident: %s' % message for message in _open_incidents(alerts_path))
    base['failures'] = failures
    if failures:
        base['status'] = 'FAILED'
    elif not any(account['candles'] for account in base['accounts']):
        base['status'] = 'NO DATA'
    else:
        base['status'] = 'PASS'
    return base


def build_week(db_path, days, *, alerts_path=None, alerts_required=False):
    reports = [build(db_path, day, alerts_path=alerts_path, alerts_required=alerts_required) for day in days]
    statuses = {report['status'] for report in reports}
    status = 'FAILED' if 'FAILED' in statuses else 'PASS' if 'PASS' in statuses else 'NO DATA'
    return dict(status=status, days=reports, fillCount=sum(len(a['fills']) for r in reports for a in r['accounts']),
                abstentionCount=sum(len(a['abstentions']) for r in reports for a in r['accounts']),
                fees=sum(a['fees'] for r in reports for a in r['accounts']),
                pnlChange=sum(a['pnl']['change'] for r in reports for a in r['accounts']),
                slippageCost=sum(a['slippageCost'] for r in reports for a in r['accounts']),
                failures=sorted({f for r in reports for f in r['failures']}),
                notes=sorted({n for r in reports for n in r['notes']}),
                dayStatuses=[(r['day'], r['status']) for r in reports],
                noDataDays=sum(1 for r in reports if r['status'] == 'NO DATA'),
                failedDays=[r['day'] for r in reports if r['status'] == 'FAILED'],
                claimsProfitability=False, disclaimer=list(DISCLAIMER))


def render(report):
    lines = ['# End-of-day paper report %s' % report['day'], '', '**Status: %s**' % report['status'], '']
    lines += ['- ' + item for item in report['disclaimer']] + ['']
    if report.get('notes'):
        lines += ['## Notes', ''] + ['- ' + item for item in report['notes']] + ['']
    if report['failures']:
        lines += ['## Failures', ''] + ['- ' + item for item in report['failures']] + ['']
    for account in report['accounts']:
        lines += ['## %s (%s)' % (account['symbol'], account['status']), '',
                  '- Candles accepted: %d; position: %s share(s); reconciled: %s' % (account['candles'], account['quantity'], 'yes' if account['reconciled'] else 'NO'),
                  '- Modelled P&L (%s): %.2f (equity %.2f to %.2f)' % (account['pnl']['basis'], account['pnl']['change'], account['pnl']['startEquity'], account['pnl']['endEquity']),
                  '- Fees today: %.2f; modelled slippage cost today: %.2f' % (account['fees'], account['slippageCost'])]
        for fill in account['fills']:
            lines.append('- Fill %s %s x%s at %.4f (candle open %s, slippage %s bps, fee %.2f)' % (
                fill['bar'], fill['side'], fill['quantity'], fill['price'],
                'unknown' if fill['rawOpen'] is None else '%.4f' % fill['rawOpen'],
                'n/a' if fill['slippageBps'] is None else '%.2f' % fill['slippageBps'], fill['fee']))
        for item in account['abstentions']:
            lines.append('- Abstained (%s %s at %s): %s' % (item['kind'], item['side'], item['bar'], item['reason']))
        lines += ['- Note: ' + note for note in account['notes']] + ['']
    if not report['accounts']:
        lines += ['No paper accounts were found.', '']
    return '\n'.join(lines)


def render_week(week):
    lines = ['# Weekly paper report', '', '**Status: %s**' % week['status'], '']
    lines += ['- ' + item for item in week['disclaimer']]
    lines += ['', '- Days: %d (no data: %d); fills: %d; abstentions: %d; fees: %.2f' % (len(week['days']), week['noDataDays'], week['fillCount'], week['abstentionCount'], week['fees'])]
    lines.append('- Modelled P&L over the days with data (not evidence of edge): %.2f; modelled slippage cost: %.2f' % (week['pnlChange'], week['slippageCost']))
    lines += ['', '## Days', ''] + ['- %s: %s' % item for item in week['dayStatuses']]
    if week['failures']:
        lines += ['', '## Failures (an open incident or an unreconciled ledger repeats on every day it persists)', ''] + ['- ' + f for f in week['failures']]
    if week['notes']:
        lines += [''] + ['- Note: ' + n for n in week['notes']]
    lines.append('- Weekends and holidays count as NO DATA days.')
    return '\n'.join(lines + [''])


def write(report, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ('eod-%s.md' % report['day'])
    path.write_text(render(report), encoding='utf-8')
    return path
