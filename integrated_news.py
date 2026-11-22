"""Connect provisioned licensed feeds to local research without copying article text."""
import datetime as dt
import threading

from syndication import SyndicationCache
from syndication_transport import FeedConfiguration, FeedTransport, configuration_status

UTC = dt.timezone.utc


class LicensedNews:
    interval = 60

    def __init__(self, settings, path, *, cache=None, clock=lambda: dt.datetime.now(UTC)):
        self.clock = clock
        self.lock = threading.Lock()
        self.poll_lock = threading.Lock()
        self.shutdown = threading.Event()
        self.thread = None
        self.cache = cache
        self.feed_url = None
        self.health = dict(source='moneycontrol', name='Moneycontrol licensed feed',
                           status='disabled', stale=True, lastSuccess=None,
                           lastAttempt=None, nextRetryAt=None, failures=0)
        if cache is None and settings.get('SYNDICATION_ENABLED', '').lower() == 'true':
            readiness = configuration_status(settings)
            self.health['status'] = readiness['status']
            if readiness['configured']:
                config = FeedConfiguration.from_mapping(settings)
                self.feed_url = config.base_url + '/feeds/news'
                try:
                    self.cache = SyndicationCache(path, FeedTransport(config), clock=clock)
                except Exception:
                    self.health['status'] = 'blocked-storage'
        elif cache is not None:
            self.health['status'] = 'awaiting-provider-verification'
        # A restarted service cannot serve potentially uncorrected cached text.
        if self.cache is not None:
            try:
                self.cache.expire_if_unobserved()
            except Exception:
                self.health['status'] = 'unavailable'

    def start(self):
        with self.lock:
            if self.cache is None or (self.thread and self.thread.is_alive()):
                return
            self.shutdown.clear()
            self.thread = threading.Thread(target=self._run, name='tradelab-licensed-news', daemon=True)
            self.thread.start()

    def stop(self):
        self.shutdown.set()
        if self.thread:
            self.thread.join(timeout=25)

    def _run(self):
        while not self.shutdown.is_set():
            try:
                self.poll_due()
            except Exception:
                with self.lock:
                    self.health.update(status='unavailable', stale=True)
            self.shutdown.wait(self.interval)

    def poll_due(self):
        if self.cache is None or not self.poll_lock.acquire(blocking=False):
            return
        try:
            now = self.clock()
            with self.lock:
                next_at = self.health['nextRetryAt']
                if next_at and dt.datetime.fromisoformat(next_at) > now:
                    return
            try:
                result = self.cache.sync_once()
                success = not result['revisions']['fullPage']
                full_news_page = result['news']['fullPage']
            except Exception:
                # Messages and provider bodies may contain licensed text or keys.
                success = False
                full_news_page = False
            self.cache.expire_if_unobserved()
            at = self.clock()
            with self.lock:
                failures = 0 if success else self.health['failures'] + 1
                self.health.update(status='fetched' if success else 'unavailable',
                    stale=not success, lastAttempt=now.isoformat(), failures=failures,
                    newsPageFull=full_news_page,
                    nextRetryAt=(at + dt.timedelta(seconds=self.interval * 2 ** min(failures, 4))).isoformat())
                if success:
                    self.health['lastSuccess'] = at.isoformat()
        finally:
            self.poll_lock.release()

    def status(self, instruments=()):
        with self.lock:
            health = dict(self.health)
        success = health['lastSuccess']
        stale = (health['status'] != 'fetched' or not success
                 or (self.clock() - dt.datetime.fromisoformat(success)).total_seconds() > 2 * self.interval)
        health['stale'] = stale
        health['collectorRunning'] = bool(self.thread and self.thread.is_alive())
        # Reads perform local expiry even when the poller is stopped. No HTTP I/O.
        articles = []
        if self.cache is not None:
            if not self.cache.lock.acquire(blocking=False):
                stale = True
                health.update(status='syncing', stale=True)
            else:
                try:
                    articles = self.cache.articles(timeout=0, limit=100)
                except Exception:
                    stale = True
                    health.update(status='unavailable', stale=True)
                finally:
                    self.cache.lock.release()
        symbols = {row.get('tradingsymbol') for row in instruments
                   if row.get('exchange') == 'NSE' and row.get('instrument_type') == 'EQ'}
        items = []
        if not stale:
            for article in articles:
                items.append(dict(id='mc:' + article['article_id'], source='moneycontrol',
                    title='Licensed provider event', summary='', description='',
                    url=self.feed_url, publishedAt=article['published_at'],
                    receivedAt=article['ingested_at'], availableAt=article['ingested_at'],
                    symbols=sorted(set(article.get('tickers', [])) & symbols),
                    mapping='Provider tag matched to current NSE equity master',
                    contentScope='Event identity and timestamps; editorial text stays in private syndication cache.'))
        return dict(items=items, sources=[health], status='unavailable' if stale else 'fetched',
                    stale=stale, lastSuccess=success, executionAllowed=False)


class IntegratedNews:
    """Shared lifecycle and snapshot API consumed by UI, research and paper workers."""
    def __init__(self, rss, licensed):
        self.rss = rss
        self.licensed = licensed

    def start(self):
        self.rss.start()
        self.licensed.start()

    def stop(self):
        self.licensed.stop()
        self.rss.stop()

    def status(self, instruments=(), *, source=None):
        result = self.rss.status(instruments, source=source)
        if source not in (None, 'moneycontrol'):
            return result
        licensed = self.licensed.status(instruments)
        if source == 'moneycontrol':
            return dict(licensed, source='Moneycontrol licensed feed', partial=False)
        sources = result['sources'] + licensed['sources']
        healthy = [row for row in sources if not row.get('stale', True)]
        result.update(items=result['items'] + licensed['items'], sources=sources,
                      status='fetched' if healthy else 'unavailable', stale=not healthy,
                      partial=0 < len(healthy) < len(sources),
                      source='Integrated research sources', executionAllowed=False)
        result['lastSuccess'] = max((row['lastSuccess'] for row in sources
                                     if row.get('lastSuccess')), default=None)
        result['collectorRunning'] = bool(result.get('collectorRunning')
                                           or licensed['sources'][0]['collectorRunning'])
        if healthy:
            result['error'] = None
        return result
