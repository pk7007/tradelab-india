"""Cached dashboard adapter for NewsAgent; publisher text stays in memory."""
import datetime as dt
import threading
import time
from news_agent import NewsAgent


class DashboardNews:
    def __init__(self,path,agent=None):
        self.agent=agent if agent is not None else NewsAgent(path)
        self.lock=threading.Lock();self.checked=None;self.items={};self.result={}

    def status(self,instruments=()):
        with self.lock:
            if self.checked is None or time.monotonic()-self.checked>=300:
                result=self.agent.poll_once()
                self.checked=time.monotonic();self.result=result
                healthy={s['source'] for s in result['sources'] if s['status']=='fetched'}
                cutoff=dt.datetime.now(dt.timezone.utc)-dt.timedelta(hours=24)
                self.items={k:v for k,v in self.items.items() if v['source'] in healthy and dt.datetime.fromisoformat(v['publishedAt'])>=cutoff}
                for item in result.get('currentItems',result['items']):
                    if item['source'] in healthy:self.items[item['id']]=item
            names={}
            for item in instruments:
                if item.get('exchange')=='NSE' and item.get('instrument_type')=='EQ':
                    names.setdefault(str(item.get('name','')).strip().casefold(),set()).add(item.get('tradingsymbol'))
            items=[]
            for original in sorted(self.items.values(),key=lambda x:x['publishedAt'],reverse=True)[:100]:
                item=dict(original)
                symbols=names.get(item['title'].casefold(),set()) if item['source']=='nse' else set()
                item['symbols']=sorted(s for s in symbols if isinstance(s,str)) if len(symbols)==1 else []
                item.update(availableAt=item['receivedAt'],description=item['summary'],mapping='Exact NSE company-name mapping' if item['symbols'] else 'Unmapped editorial context; no symbol inferred')
                items.append(item)
            healthy=any(s['status']=='fetched' for s in self.result.get('sources',[]))
            return dict(items=items,source='News agent · NSE / ET / Google RSS',sources=self.result.get('sources',[]),
                        status='fetched' if healthy else 'unavailable',partial=self.result.get('status')=='partial',stale=not healthy,
                        lastSuccess=max((s['checkedAt'] for s in self.result.get('sources',[]) if s['status']=='fetched'),default=None),
                        pollSeconds=300,executionAllowed=False,
                        scope='Personal RSS context only. No complete coverage, full articles, external AI or order authority.')
