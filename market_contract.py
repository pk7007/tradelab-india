"""Provider-neutral observation checks; source verification remains external."""
import datetime as dt
import math
import re
from urllib.parse import urlsplit
from research import timestamp


def validate_quote(record, *, instrument, as_of, max_age_seconds):
    if not isinstance(instrument,str) or not re.fullmatch(r'NSE:[A-Z0-9&-]{1,30}',instrument):
        raise ValueError('Verified NSE instrument mapping required.')
    if not isinstance(record,dict) or record.get('instrument') != instrument:
        raise ValueError('Exact mapped instrument is required.')
    if not isinstance(record.get('provider'),str) or not record['provider'].strip():
        raise ValueError('Provider attribution is required.')
    now=timestamp(as_of)
    if isinstance(max_age_seconds,bool) or not isinstance(max_age_seconds,(int,float)) or not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
        raise ValueError('Specify a positive freshness budget.')
    for key in ('exchangeAt','receivedAt'):
        at=timestamp(record.get(key,''))
        if not 0 <= (now-at).total_seconds() <= max_age_seconds:
            raise ValueError('Stale or future '+key)
    if timestamp(record['exchangeAt']) > timestamp(record['receivedAt']):
        raise ValueError('Exchange observation cannot follow receipt.')
    for key in ('bid','ask'):
        value=record.get(key)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('Positive finite bid/ask required.')
    if record['ask'] < record['bid']:
        raise ValueError('Crossed quote.')
    return dict(record)


def session_for(manifest, *, date, as_of):
    """Explicit session manifest, never infer a holiday from a weekday."""
    if not isinstance(manifest,dict) or manifest.get('exchange') != 'NSE' or manifest.get('segment') != 'EQ':
        raise ValueError('NSE EQ calendar attribution required.')
    source=manifest.get('source','')
    parsed=urlsplit(source) if isinstance(source,str) else None
    if not parsed or parsed.scheme!='https' or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError('Calendar source reference required.')
    if timestamp(manifest.get('availableAt','')) > timestamp(as_of):
        raise ValueError('Calendar was unavailable at the cutoff.')
    day=dt.date.fromisoformat(date).isoformat()
    sessions=manifest.get('sessions')
    if not isinstance(sessions,dict) or day not in sessions:
        raise ValueError('Session unknown; do not infer market open.')
    session=sessions[day]
    if session is None:
        return dict(open=False,date=day,source=source,verified=False)
    if not isinstance(session,dict): raise ValueError('Invalid session.')
    start,end=timestamp(session.get('open','')),timestamp(session.get('close',''))
    if start.date().isoformat()!=day or end.date().isoformat()!=day or start>=end:
        raise ValueError('Invalid session bounds.')
    return dict(open=True,date=day,start=start.isoformat(),end=end.isoformat(),source=source,verified=False)
