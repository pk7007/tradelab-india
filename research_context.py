"""Attach current permitted news without leaking future information into replay."""
import datetime as dt
import hashlib
import json
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
                record = {k:item[k] for k in ('title','url','publishedAt','availableAt','symbols')}
                record.update(id=item.get('id'), source=item.get('source', 'news'))
                eligible.append(record)
            except (KeyError,ValueError,TypeError): continue
    values['records']=records+eligible
    return values,dict(source=feed.get('source','NSE RSS'),attached=len(eligible),stale=bool(feed.get('stale')),
                       lastSuccess=feed.get('lastSuccess'),scope='Context only; no trade authority. Unmapped, future and older-than-24-hour items excluded.')


def evidence_references(records, symbol):
    """Bounded provenance for the journal, without editorial text or source URLs."""
    references = {}
    for record in records:
        if symbol not in record['symbols']:
            continue
        identity = dict(id=record.get('id'), source=record.get('source', 'news'),
                        publishedAt=record['publishedAt'], availableAt=record['availableAt'], symbol=symbol)
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        source = identity['source'] if identity['source'] in ('moneycontrol', 'nse', 'et', 'google') else 'news'
        references[fingerprint] = dict(inputHash=fingerprint, symbol=symbol, source=source,
            publishedAt=identity['publishedAt'], availableAt=identity['availableAt'])
        if len(references) >= 100:
            break
    return list(references.values())
