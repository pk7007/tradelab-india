"""One in-process RSS collector; all dashboard and research reads use snapshots."""
import datetime as dt
import re
import threading

from announcements import FEED
from news_agent import FEEDS, NewsAgent, UTC


class DashboardNews:
    interval = 30

    def __init__(self, path, agent=None, clock=lambda: dt.datetime.now(UTC)):
        self.agent = agent if agent is not None else NewsAgent(path)
        self.clock = clock
        self.lock = threading.Lock()
        self.poll_lock = threading.Lock()
        self.shutdown = threading.Event()
        self.thread = None
        self.items = {}
        self.health = {source: dict(source=source, name=FEEDS[source][0],
                                    status='unchecked', stale=True, failures=0,
                                    lastSuccess=None, newestPublishedAt=None, nextRetryAt=None)
                       for source in self.agent.sources}

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.shutdown.clear()
            self.thread = threading.Thread(target=self._run, name='tradelab-news', daemon=True)
            self.thread.start()

    def stop(self):
        self.shutdown.set()
        if self.thread:
            self.thread.join(timeout=50)

    def _run(self):
        while not self.shutdown.is_set():
            self.poll_due()
            if self.shutdown.is_set():
                return
            with self.lock:
                next_at = min(dt.datetime.fromisoformat(s['nextRetryAt']) for s in self.health.values())
            self.shutdown.wait(max(1, min(self.interval, (next_at-self.clock()).total_seconds())))

    def poll_due(self):
        """Single flight across timer or explicit service ticks; never hold read lock over I/O."""
        if not self.poll_lock.acquire(blocking=False):
            return
        try:
            now = self.clock()
            with self.lock:
                due = [key for key,s in self.health.items() if not s['nextRetryAt']
                       or dt.datetime.fromisoformat(s['nextRetryAt']) <= now]
            for key in due:
                if self.shutdown.is_set():
                    break
                try:
                    payload = self.agent.poll_once(sources=(key,))
                    observed = next(row for row in payload['sources'] if row['source']==key)
                    rows = payload.get('currentItems', payload['items'])
                except Exception:
                    # Transport and storage exceptions can contain private paths or tokens.
                    observed = dict(status='unavailable', error='CollectionFailed')
                    rows = []
                at = self.clock()
                success = observed['status']=='fetched'
                with self.lock:
                    old = self.health[key]
                    failures = 0 if success else old['failures']+1
                    delay = max(min(3600,self.interval*2**min(failures,4)),
                                observed.get('retryAfterSeconds') or 0)
                    health = dict(old, **observed)
                    health.update(lastAttempt=now.isoformat(), checkedAt=at.isoformat(),
                                  failures=failures, stale=not success,
                                  nextRetryAt=(at+dt.timedelta(seconds=delay)).isoformat())
                    if success:
                        health.pop('error',None)
                        health.pop('retryAfterSeconds',None)
                        health['lastSuccess'] = at.isoformat()
                        current = [row for row in rows if row['source']==key]
                        if 'currentItems' in payload:
                            self.items = {k:v for k,v in self.items.items() if v['source']!=key}
                        for row in current:
                            self.items[row['id']] = row
                        health['newestPublishedAt'] = max((v['publishedAt'] for v in self.items.values()
                                                         if v['source']==key), default=None)
                    self.health[key] = health
                    cutoff = at-dt.timedelta(hours=24)
                    self.items = {k:v for k,v in self.items.items()
                                  if dt.datetime.fromisoformat(v['publishedAt']) >= cutoff}
        finally:
            self.poll_lock.release()

    def status(self, instruments=(), *, source=None):
        now = self.clock()
        with self.lock:
            sources = [dict(row) for key,row in self.health.items() if source in (None,key)]
            rows = [row for row in self.items.values() if source in (None,row['source'])]
        healthy = set()
        for s in sources:
            success = s['lastSuccess']
            overdue = success and (now-dt.datetime.fromisoformat(success)).total_seconds()>2*self.interval
            s['stale'] = s['status']!='fetched' or bool(overdue)
            s['staleReason'] = ('poll overdue' if overdue else s['status']) if s['stale'] else None
            if not s['stale']:
                healthy.add(s['source'])
        names = {}
        for instrument in instruments:
            name = str(instrument.get('name','')).strip().casefold()
            symbol = instrument.get('tradingsymbol')
            if (instrument.get('exchange')=='NSE' and instrument.get('instrument_type')=='EQ'
                    and name and isinstance(symbol,str) and re.fullmatch(r'[A-Z0-9&-]{1,30}',symbol)):
                names.setdefault(name,set()).add(symbol)
        fresh, stale = [], []
        for original in sorted(rows,key=lambda r:r['publishedAt'],reverse=True):
            if now-dt.datetime.fromisoformat(original['publishedAt'])>dt.timedelta(hours=24):
                continue
            target = fresh if original['source'] in healthy else stale
            if len(target)>=100:
                continue
            item = dict(original)
            symbols = names.get(item['title'].casefold(),set()) if item['source']=='nse' else set()
            item.update(symbols=sorted(symbols) if len(symbols)==1 else [],
                        availableAt=item.get('availableAt',item['receivedAt']),description=item['summary'],
                        mapping='Exact NSE company-name mapping' if len(symbols)==1 else
                                'Ambiguous company name' if symbols else 'Unmapped')
            target.append(item)
        coverage = {}
        for item in fresh:
            if item.get('storyKey'):
                coverage.setdefault(item['storyKey'], set()).add(item['id'])
        for item in fresh:
            if item.get('storyKey'):
                item['sourceIds'] = sorted(coverage[item['storyKey']])
        return dict(items=fresh, staleItems=stale, sources=sources, source=FEED if source=='nse' else 'News agent · RSS',
                    status='fetched' if healthy else 'unavailable', stale=not healthy,
                    partial=0<len(healthy)<len(sources), collectorRunning=bool(self.thread and self.thread.is_alive()),
                    lastSuccess=max((s['lastSuccess'] for s in sources if s['lastSuccess']),default=None),
                    error=None if healthy else 'No current source snapshot', pollSeconds=self.interval,
                    executionAllowed=False,scope='Personal RSS research context only.')
