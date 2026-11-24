"""Read-only "arm for today" checklist. It reports; it never arms, logs in, or attests.

Every owner-only step (Zerodha login, the provider-retention attestation, the calendar the owner
supplies, and the explicit start) stays with the owner. Nothing here writes an environment variable,
a setting, or a database row, and passing the checklist authorises no order.
"""
import trading_calendar

DEFAULT_SQUARE_OFF = '15:05'
OWNER_STEPS = dict(
    login='Click Connect Zerodha in the app and sign in yourself.',
    storage='Confirm you may retain provider candles, then set KITE_DATA_STORAGE_APPROVED=true in your own .env and restart.',
    calendar='Check NSE\'s holiday list and supply or refresh an attributed calendar that lists today.')


def _item(key, label, status, detail, owner=None):
    return dict(key=key, label=label, status=status, detail=detail, ownerAction=owner if status != 'PASS' else None)


def checklist(*, environ, session, calendar, now, selector_status=None, square_off=DEFAULT_SQUARE_OFF):
    items = []
    connected = bool(isinstance(session, dict) and session.get('access_token')
                     and (session.get('profile') or {}).get('user_id'))
    items.append(_item('login', 'Zerodha login', 'PASS' if connected else 'BLOCKED',
                       'Connected for this browser session.' if connected else
                       'No broker session; tokens live only in memory and expire daily.', OWNER_STEPS['login']))
    approved = str(environ.get('KITE_DATA_STORAGE_APPROVED', 'false')).strip().lower() == 'true'
    items.append(_item('storage', 'Provider retention approval', 'PASS' if approved else 'BLOCKED',
                       'KITE_DATA_STORAGE_APPROVED is true (your own attestation).' if approved else
                       'KITE_DATA_STORAGE_APPROVED is not true.', OWNER_STEPS['storage']))
    stamp = now.isoformat()
    try:
        day = trading_calendar.require_trading_day(calendar, stamp, square_off=square_off, strict_sessions=False)
        info = trading_calendar.validate(calendar, stamp, strict_sessions=False)
        items.append(_item('calendar', 'Session calendar', 'PASS',
                           'Calendar %s lists %s as open until %s; %d trading days of runway. Attestation, not exchange verification.'
                           % (day['version'], day['date'], day['end'][11:16], info['runwayTradingDays'])))
    except trading_calendar.ClosedDay as error:
        items.append(_item('calendar', 'Session calendar', 'BLOCKED', str(error), OWNER_STEPS['calendar']))
    except (trading_calendar.CalendarError, ValueError, TypeError, AttributeError) as error:
        items.append(_item('calendar', 'Session calendar', 'FAIL', 'Calendar not usable: %s' % error,
                           OWNER_STEPS['calendar']))
    armed = bool(selector_status and selector_status.get('enabled'))
    items.append(_item('selector', 'Automatic paper selection', 'PASS',
                       'Armed for this process.' if armed else 'Disarmed (a fresh process always starts disarmed).'))
    required = [i for i in items if i['key'] != 'selector']
    return dict(ready=all(i['status'] == 'PASS' for i in required), armed=armed, items=items,
                ownerSteps=[i['ownerAction'] for i in items if i['ownerAction']],
                attestationsWrittenByCode=False, authorizesOrders=False, mode='paper-only')
