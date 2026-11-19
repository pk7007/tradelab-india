"""Attach current permitted news without leaking future information into replay."""
import datetime as dt
from research import timestamp


def attach_announcements(request,feed):
    values=dict(request)
    cutoff=timestamp(values.get('asOf',''))
    records=values.get('records',[])
    if not isinstance(records,list): raise ValueError('Research records must be a list.')
    eligible=[]
    if not feed.get('stale') and feed.get('status')=='fetched':
        for item in feed.get('items',[]):
            try:
                published=timestamp(item['publishedAt']);available=timestamp(item['availableAt'])
                if not item.get('symbols') or max(published,available)>cutoff: continue
                if cutoff-published>dt.timedelta(hours=24): continue
                eligible.append({k:item[k] for k in ('title','url','publishedAt','availableAt','symbols')})
            except (KeyError,ValueError,TypeError): continue
    values['records']=records+eligible
    return values,dict(source=feed.get('source','NSE RSS'),attached=len(eligible),stale=bool(feed.get('stale')),
                       lastSuccess=feed.get('lastSuccess'),scope='Context only; no trade authority. Unmapped, future and older-than-24-hour items excluded.')
