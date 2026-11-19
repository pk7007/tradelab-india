"""Bounded, cached official NSE RSS reader. No articles or broker orders fetched."""
import datetime as dt
from email.utils import parsedate_to_datetime
import hashlib
import re
import threading
import time
import urllib.request
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from research import IST

FEED='https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml'


def parse_feed(raw, received):
    if len(raw)>3_000_000 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Unsupported or oversized feed.')
    root=ET.fromstring(raw)
    if root.tag!='rss': raise ValueError('Expected RSS feed.')
    items=[];seen=set()
    for node in root.findall('./channel/item')[:1000]:
        title=(node.findtext('title') or '').strip()[:500]
        url=(node.findtext('link') or '').strip()
        try:
            p=urlsplit(url)
            if p.scheme!='https' or p.hostname not in ('nsearchives.nseindia.com','www.nseindia.com','www.nseindia.in') or p.username is not None or p.password is not None or p.port not in (None,443): continue
        except ValueError: continue
        try:
            stamp=(node.findtext('pubDate') or '').strip()
            try: published=dt.datetime.strptime(stamp,'%d-%b-%Y %H:%M:%S').replace(tzinfo=IST)
            except ValueError: published=parsedate_to_datetime(stamp)
            if published.tzinfo is None or published>received: continue
        except (ValueError,TypeError,OverflowError): continue
        published=published.astimezone(IST)
        identity=hashlib.sha256((url+'|'+published.isoformat()).encode()).hexdigest()
        if not title or identity in seen: continue
        seen.add(identity)
        description=re.sub('<[^>]+>',' ',node.findtext('description') or '')[:2000]
        items.append(dict(id=identity,title=title,description=description,url=url,publishedAt=published.isoformat(),
                          receivedAt=received.isoformat(),availableAt=received.isoformat(),symbols=[]))
    return sorted(items,key=lambda r:r['publishedAt'],reverse=True)


class Announcements:
    def __init__(self):
        self.lock=threading.Lock();self.at=None;self.checked=0;self.items=[];self.error=None;self.first_seen={}

    def status(self, instruments=()):
        with self.lock:
            if not self.checked or time.monotonic()-self.checked>=300:
                self.checked=time.monotonic()
                try:
                    req=urllib.request.Request(FEED,headers={'User-Agent':'TradeLabIndia/1.0 personal RSS reader','Accept':'application/rss+xml,application/xml'})
                    with urllib.request.urlopen(req,timeout=15) as response:
                        if response.url!=FEED: raise ValueError('Unexpected feed redirect.')
                        raw=response.read(3_000_001)
                    received=dt.datetime.now(dt.timezone.utc)
                    items=parse_feed(raw,received)
                    for item in items:
                        item['availableAt']=self.first_seen.get(item['id'],received.isoformat())
                    self.first_seen={item['id']:item['availableAt'] for item in items}
                    self.items=items;self.at=received.isoformat();self.error=None
                except Exception:
                    self.error='NSE feed unavailable or invalid. No fresh announcements confirmed; retry after five minutes.'
            names={}
            for instrument in instruments:
                if instrument.get('exchange')!='NSE' or instrument.get('instrument_type')!='EQ': continue
                name=str(instrument.get('name','')).strip().casefold()
                symbol=instrument.get('tradingsymbol')
                if name and isinstance(symbol,str) and re.fullmatch(r'[A-Z0-9&-]{1,30}',symbol): names.setdefault(name,set()).add(symbol)
            items=[]
            for original in self.items[:100]:
                item=dict(original)
                symbols=names.get(item['title'].casefold(),set())
                item['symbols']=sorted(s for s in symbols if isinstance(s,str)) if len(symbols)==1 else []
                item['mapping']='Exact instrument-name match' if item['symbols'] else 'Unmapped company; no symbol inferred'
                items.append(item)
            return dict(items=items,source=FEED,lastSuccess=self.at,status='unavailable' if self.error else 'fetched',
                        error=self.error,stale=bool(self.error),pollSeconds=300,executionAllowed=False,
                        scope='RSS summaries only; no full articles, historical archive, or order triggers. First-seen times reset on restart.')
