"""Attributed NSE EQ session calendar checks that fail closed. No network access.

The calendar is an owner-supplied attestation, not exchange verification. This module only
validates what the manifest explicitly says: a listed date, a recognised session shape, a
recent `availableAt`, and a square-off candle that completes before the close. It never
infers a holiday or an opening from the weekday, and it refuses special sessions the paper
engine does not support. Refreshing the manifest from its attributed `source` (and checking
the source's terms of use) is a manual owner step.
"""
import datetime as dt
import hashlib
import json

from market_contract import session_for
from research import timestamp

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MAX_AGE_DAYS = 30
MAX_SESSIONS = 400
OPEN = dt.time(9, 15)
CLOSES = (dt.time(15, 15), dt.time(15, 30))
CANDLE = dt.timedelta(minutes=5)


class CalendarError(ValueError):
    """The calendar cannot be relied on; processing must not start."""


class ClosedDay(CalendarError):
    """The calendar explicitly marks the date as closed."""


def fingerprint(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False, default=str).encode()).hexdigest()


def validate(manifest, as_of, *, max_age_days=MAX_AGE_DAYS, min_runway_days=0, strict_sessions=True):
    """strict_sessions=False leaves special sessions to be blocked at processing time (paper_worker)."""
    if not isinstance(manifest, dict):
        raise CalendarError('Calendar manifest must be an object.')
    version = manifest.get('version')
    if not isinstance(version, str) or not version.strip() or len(version) > 100:
        raise CalendarError('A versioned calendar is required.')
    sessions = manifest.get('sessions')
    if not isinstance(sessions, dict) or not 1 <= len(sessions) <= MAX_SESSIONS:
        raise CalendarError('Calendar must list between 1 and %d explicit dates.' % MAX_SESSIONS)
    try:
        now = timestamp(as_of)
        available = timestamp(manifest.get('availableAt', ''))
    except (ValueError, TypeError, OverflowError):
        raise CalendarError('Calendar availability time is invalid.') from None
    if available > now:
        raise CalendarError('Calendar was not yet available at this time.')
    if now - available > dt.timedelta(days=max_age_days):
        raise CalendarError('Calendar is stale (older than %d days); refresh it from its source.' % max_age_days)
    today = now.astimezone(IST).date()
    dates, runway = [], 0
    for key in sessions:
        try:
            date = dt.date.fromisoformat(key)
            planned = session_for(manifest, date=key, as_of=now.isoformat())
        except (ValueError, TypeError) as error:
            raise CalendarError('Invalid calendar entry: %s' % error) from None
        dates.append(date)
        if not planned['open']:
            continue
        start, end = timestamp(planned['start']).astimezone(IST), timestamp(planned['end']).astimezone(IST)
        if strict_sessions and (date.weekday() >= 5 or start.time() != OPEN or end.time() not in CLOSES):
            raise CalendarError('Special or unsupported session on %s; the paper engine does not support it.' % key)
        if date >= today:
            runway += 1
    if runway < min_runway_days:
        raise CalendarError('Calendar runway is %d trading days, below the required %d.' % (runway, min_runway_days))
    return dict(valid=True, version=version, source=manifest['source'], availableAt=manifest['availableAt'],
                fingerprint=fingerprint(manifest), firstDate=min(dates).isoformat(), lastDate=max(dates).isoformat(),
                runwayTradingDays=runway)


def require_trading_day(manifest, as_of, *, square_off, max_age_days=MAX_AGE_DAYS, strict_sessions=True):
    """The validated session for today (IST), with the square-off instant derived from its close."""
    info = validate(manifest, as_of, max_age_days=max_age_days, strict_sessions=strict_sessions)
    now = timestamp(as_of)
    # research.timestamp() already yields IST; the explicit conversion keeps the intent obvious.
    today = now.astimezone(IST).date().isoformat()
    if today not in manifest['sessions']:
        raise CalendarError('Today (%s) is not listed in the calendar; do not infer market open.' % today)
    session = session_for(manifest, date=today, as_of=now.isoformat())
    if not session['open']:
        raise ClosedDay('The calendar marks %s as closed.' % today)
    try:
        exit_time = dt.time.fromisoformat(square_off)
    except (ValueError, TypeError):
        raise CalendarError('Square-off time is invalid.') from None
    close = timestamp(session['end']).astimezone(IST)
    exit_at = dt.datetime.combine(close.date(), exit_time, IST)
    if exit_at + CANDLE >= close:
        raise CalendarError('Square-off candle must complete strictly before the calendar close.')
    return dict(date=today, start=session['start'], end=session['end'], squareOffAt=exit_at.isoformat(),
                version=info['version'], source=info['source'], fingerprint=info['fingerprint'])
