"""Personal portal settings and import-only research. No broker authority."""
from contextlib import closing
import json
import math
from pathlib import Path
import re
import sqlite3
from trader_suite import scan, risk_check, news
from research import timestamp


class Portal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS portal_settings (id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL)')
            db.execute('INSERT OR IGNORE INTO portal_settings VALUES(1,?)', (json.dumps(dict(capital=1000,maxLoss=25,dailyLossLimit=100,revision=1,watchlist=[])),))

    def status(self):
        with closing(sqlite3.connect(self.path)) as db:
            body = json.loads(db.execute('SELECT body FROM portal_settings WHERE id=1').fetchone()[0])
        watchlist = body.pop('watchlist')
        return dict(settings=body,watchlist=watchlist,liveEnabled=False,newsConnected=False,aiConnected=False,
                    scope='Imported research snapshots and independent paper accounts. No live dispatch.')

    def update(self, values):
        clean = {}
        for key in ('capital','maxLoss','dailyLossLimit'):
            value = values.get(key)
            if isinstance(value,bool): raise ValueError('Invalid '+key)
            try: value = float(value)
            except (TypeError,ValueError): raise ValueError('Specify '+key) from None
            if not math.isfinite(value) or not 0 < value <= 1e12: raise ValueError('Invalid '+key)
            clean[key] = value
        if not clean['maxLoss'] <= clean['dailyLossLimit'] <= clean['capital']:
            raise ValueError('Per-trade loss <= daily loss <= capital required.')
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            old = json.loads(db.execute('SELECT body FROM portal_settings WHERE id=1').fetchone()[0])
            clean.update(revision=old['revision']+1,watchlist=old['watchlist'])
            db.execute('UPDATE portal_settings SET body=? WHERE id=1',(json.dumps(clean),))
        return self.status()

    def research(self, values):
        if values.get('horizon') == 'long-term':
            watchlist = values.get('watchlist',self.status()['watchlist'])
            if not isinstance(watchlist,list) or len(watchlist)>50 or any(not isinstance(s,str) or not re.fullmatch(r'[A-Z0-9&-]{1,30}',s) for s in watchlist):
                raise ValueError('Use at most 50 exact uppercase symbols.')
            watchlist = list(dict.fromkeys(watchlist))
            with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                body=json.loads(db.execute('SELECT body FROM portal_settings WHERE id=1').fetchone()[0]);body['watchlist']=watchlist
                db.execute('UPDATE portal_settings SET body=? WHERE id=1',(json.dumps(body),))
            from fundamental_research import research_long_term
            return research_long_term(values, watchlist)
        if values.get('horizon') != 'intraday': raise ValueError('Choose intraday or long-term.')
        universe=values.get('candles',{})
        if not isinstance(universe,dict) or any(not isinstance(s,str) or not re.fullmatch(r'[A-Z0-9&-]{1,30}',s) for s in universe):
            raise ValueError('Use exact uppercase NSE equity symbols.')
        if not isinstance(values.get('plans',{}),dict): raise ValueError('Plans must be an object by symbol.')
        result=scan(values);settings=self.status()['settings'];candidates=[];excluded=list(result['excluded'])
        for match in result['matches']:
            symbol=match['symbol'];proposal=values.get('plans',{}).get(symbol)
            visible=[r for r in universe[symbol] if timestamp(r['date']) <= timestamp(match['bar'])]
            if not visible or any(float(r['volume']) <= 0 for r in visible):
                excluded.append(dict(symbol=symbol,reason='Zero-volume observations do not support an executable setup.'));continue
            if not isinstance(proposal,dict):
                excluded.append(dict(symbol=symbol,reason='Setup found; explicit entry, stop, target and cost assumptions are missing.'));continue
            # Risk observations are mandatory: zero is never inferred from missing account data.
            snapshot={k:values.get(k) for k in ('dailyLoss','exposure','pendingExposure')}
            checked=risk_check(dict(proposal,**snapshot,budget=settings['capital'],maxLoss=settings['maxLoss'],dailyLossLimit=settings['dailyLossLimit'],maxExposure=settings['capital']))
            if not checked['allowed']:
                excluded.append(dict(symbol=symbol,reason='; '.join(checked['reasons'])));continue
            articles=news(dict(permitted=values.get('permitted'),records=values.get('records',[]),watchlist=symbol,asOf=values['asOf']))['items']
            # Preserve original information-availability evidence removed by the
            # legacy display adapter, and visibly distinguish older news.
            for article in articles:
                sources=[r for r in values.get('records',[]) if r.get('url')==article['url'] and r.get('publishedAt')==article['publishedAt']
                         and timestamp(r.get('availableAt') or r['publishedAt']) <= timestamp(values['asOf'])]
                article['availableAt']=sources[-1].get('availableAt',article['publishedAt']) if sources else article['publishedAt']
                article['ageSeconds']=(timestamp(values['asOf'])-timestamp(article['availableAt'])).total_seconds()
                article['freshness']='Older than one day' if article['ageSeconds']>86400 else 'Within one day of snapshot'
            candidates.append(dict(**match,exchange='NSE',observationAt=match['bar'],source='Imported snapshot',live=False,
                plan=checked,news=articles,evidence='Unvalidated setup heuristic; no executable liquidity or verified continuous news feed.',
                entryCondition='User-supplied plan requires a new validated observation before any execution.',
                missing=['Verified executable liquidity','Continuous news feed','Exchange calendar'],autoEligible=False))
        candidates.sort(key=lambda x:(-len(x['setups']),x['symbol']))
        return dict(status='Research candidates' if candidates else 'No qualifying trade',candidates=candidates[:5],excluded=excluded,
                    live=False,asOf=values['asOf'],ranking='Setup count, then symbol; descriptive ranking, not predicted profit.',limits=settings)
