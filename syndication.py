"""Private syndication cache and revision handling. No model or trading authority.

Transport is injected: no undocumented article endpoint is assumed. An updated
revision invalidates old content until a sufficiently new full item arrives.
"""
from contextlib import contextmanager
import datetime as dt
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time

UTC = dt.timezone.utc


def stamp(value):
    if not isinstance(value,str): raise ValueError('A zoned timestamp is required.')
    result=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None: raise ValueError('A zoned timestamp is required.')
    return result.astimezone(UTC)


def identity(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',value):
        raise ValueError('Invalid article identity.')
    return value


class RateLimiter:
    def __init__(self, interval=1.0):
        if isinstance(interval,bool) or not isinstance(interval,(int,float)) or not math.isfinite(interval) or interval<1: raise ValueError('At most one request per second.')
        self.interval=interval;self.last=None;self.lock=threading.Lock()

    def wait(self):
        with self.lock:
            if self.last is not None: time.sleep(max(0,self.interval-(time.monotonic()-self.last)))
            self.last=time.monotonic()


class SyndicationCache:
    def __init__(self,path,transport,clock=lambda:dt.datetime.now(UTC),limiter=None):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.transport=transport;self.clock=clock;self.limiter=limiter or RateLimiter()
        self.lock=threading.RLock()
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS mc_articles(id TEXT PRIMARY KEY,updated TEXT NOT NULL,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS mc_revisions(id TEXT PRIMARY KEY,status TEXT NOT NULL,event_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS mc_state(name TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS mc_articles_updated ON mc_articles(updated);''')

    @contextmanager
    def db(self, timeout=10):
        db=sqlite3.connect(self.path,timeout=timeout)
        try:
            db.execute('PRAGMA secure_delete=ON')
            db.execute('PRAGMA journal_mode=DELETE')
            with db: yield db
        finally: db.close()

    @staticmethod
    def state(db,key):
        row=db.execute('SELECT value FROM mc_state WHERE name=?',(key,)).fetchone()
        return row[0] if row else None

    @staticmethod
    def save_state(db,key,value):
        db.execute('INSERT OR REPLACE INTO mc_state VALUES(?,?)',(key,value))

    def get(self,endpoint,since):
        self.limiter.wait()
        result=self.transport(endpoint,dict(since=since,**({'limit':50} if endpoint=='/feeds/news' else {})))
        if not isinstance(result,dict): raise ValueError('Invalid provider response.')
        return result

    def poll(self,endpoint):
        if endpoint not in ('/feeds/news','/feeds/revisions'): raise ValueError('Unsupported feed.')
        with self.lock:
            now=self.clock()
            with self.db() as db:
                previous=self.state(db,endpoint)
            # Revision service only promises a 48-hour window. Never retain
            # potentially uncorrected content across an unobservable outage.
            self.expire_if_unobserved(now)
            since=previous or (now-dt.timedelta(hours=48)).isoformat()
            if endpoint=='/feeds/revisions':
                with self.db() as db: self.save_state(db,'revisions_pending','true')
            payload=self.get(endpoint,since)
            now=self.clock()
            cursor=stamp(payload.get('cursor'))
            if cursor>now or (previous and cursor<stamp(previous)):
                raise ValueError('Future or regressive cursor.')
            key='items' if endpoint=='/feeds/news' else 'revisions'
            rows=payload.get(key)
            if not isinstance(rows,list) or len(rows)>1000: raise ValueError('Invalid bounded feed page.')
            # Validation and mutations share a transaction with cursor commit.
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                if self.state(db,endpoint)!=previous:
                    raise ValueError('Concurrent feed sync changed cursor; retry from committed state.')
                for row in rows:
                    if not isinstance(row,dict): raise ValueError('Invalid feed record.')
                    art=identity(row.get('article_id'));status=row.get('status')
                    if endpoint=='/feeds/revisions' or status=='retracted':
                        at=stamp(row.get('event_timestamp') or row.get('retracted_at') or row.get('updated_at'))
                        if at>now: raise ValueError('Future revision.')
                        self.revise(db,art,status,at)
                    else:
                        self.store(db,row,now)
                self.save_state(db,endpoint,cursor.isoformat())
                if endpoint=='/feeds/revisions':
                    # The contract has no documented exhaustion marker. A full
                    # page may hide pending retractions, so never certify it as
                    # a completed revision sweep without provider pagination.
                    if len(rows)<50:
                        self.save_state(db,'revisions_success',now.isoformat())
                        self.save_state(db,'revisions_pending','false')
            return dict(processed=len(rows),cursor=cursor.isoformat(),fullPage=len(rows)>=50,
                        executionAllowed=False)

    def revise(self,db,art,status,at):
        if status not in ('updated','retracted'): raise ValueError('Unknown revision state.')
        old=db.execute('SELECT status,event_at FROM mc_revisions WHERE id=?',(art,)).fetchone()
        # Retraction is permanent until a separately specified reinstatement
        # protocol exists. Older updates cannot resurrect a withdrawn article.
        if old and (old[0]=='retracted' or (status!='retracted' and stamp(old[1])>at)): return
        if status=='updated':
            current=db.execute('SELECT updated FROM mc_articles WHERE id=?',(art,)).fetchone()
            if current and stamp(current[0])>=at:
                # Inclusive revision cursors can repeat an event after its full
                # corrected record has already arrived. Do not delete that
                # valid replacement and wait forever for another copy.
                db.execute('INSERT OR REPLACE INTO mc_revisions VALUES(?,?,?)',(art,status,at.isoformat()))
                return
        db.execute('DELETE FROM mc_articles WHERE id=?',(art,))
        db.execute('INSERT OR REPLACE INTO mc_revisions VALUES(?,?,?)',(art,status,at.isoformat()))

    def store(self,db,row,now):
        art=identity(row.get('article_id'))
        if row.get('status') not in ('published','updated'): raise ValueError('Unknown article state.')
        published=stamp(row.get('published_at'));updated=stamp(row.get('updated_at'))
        if not published<=updated<=now: raise ValueError('Invalid article timing.')
        tickers=row.get('tickers')
        if not isinstance(tickers,list) or len(tickers)>100 or any(not isinstance(s,str) or not re.fullmatch(r'[A-Z0-9&-]{1,30}',s) for s in tickers):
            raise ValueError('Invalid exact symbols.')
        for field in ('headline','summary','body'):
            value=row.get(field,'')
            if not isinstance(value,str) or len(value)>200000: raise ValueError('Invalid article text.')
        if not row.get('headline'): raise ValueError('Headline required.')
        revision=db.execute('SELECT status,event_at FROM mc_revisions WHERE id=?',(art,)).fetchone()
        if revision and (revision[0]=='retracted' or updated<stamp(revision[1])): return
        old=db.execute('SELECT updated FROM mc_articles WHERE id=?',(art,)).fetchone()
        if old and stamp(old[0])>updated: return
        clean={k:row.get(k,'') for k in ('article_id','status','published_at','updated_at','category','tickers','headline','summary','body')}
        clean.update(ingested_at=now.isoformat(),sentiment_score=None)
        db.execute('INSERT OR REPLACE INTO mc_articles VALUES(?,?,?)',(art,updated.isoformat(),json.dumps(clean,allow_nan=False)))

    def expire_if_unobserved(self,now=None, *, timeout=10):
        now=now or self.clock()
        with self.db(timeout=timeout) as db:
            last=self.state(db,'revisions_success')
            if self.state(db,'revisions_pending')=='true' or not last or now-stamp(last)>=dt.timedelta(hours=6):
                db.execute('DELETE FROM mc_articles')
                return True
        return False

    def articles(self, *, timeout=10, limit=None):
        if limit is not None and (type(limit) is not int or not 1 <= limit <= 1000):
            raise ValueError('Article limit must be between one and one thousand.')
        with self.lock:
            if self.expire_if_unobserved(timeout=timeout): return []
            with self.db(timeout=timeout) as db:
                query = 'SELECT body FROM mc_articles ORDER BY updated DESC'
                rows = db.execute(query + ' LIMIT ?', (limit,)) if limit is not None else db.execute(query)
                return [json.loads(r[0]) for r in rows]

    def sync_once(self):
        # Fail closed: revisions must succeed before ingestion or delivery.
        revisions=self.poll('/feeds/revisions')
        news=self.poll('/feeds/news')
        return dict(revisions=revisions,news=news,articles=len(self.articles()),executionAllowed=False)
