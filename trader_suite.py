"""Import-first trader tools. No broker calls; no automated live execution."""
import datetime as dt
import math
import random
import statistics
import secrets
from research import timestamp, validate_rows

TOOLS={'scanner','news','entry','exit','timemachine','risk','budget','broker','alerts','analyst','pelosi'}

def number(data,key,minimum=0):
    value=data.get(key)
    if isinstance(value,bool):raise ValueError(key+' must be numeric.')
    try:value=float(value)
    except (ValueError,TypeError):raise ValueError('Enter '+key+'.') from None
    if not math.isfinite(value) or value<minimum:raise ValueError(key+' is outside its allowed range.')
    return value

def plan(data):
    entry=number(data,'entry',.01);stop=number(data,'stop',.01);target=number(data,'target',.01)
    if not stop<entry<target:raise ValueError('Long-only plan requires stop < entry < target.')
    budget=number(data,'budget',.01);risk=number(data,'maxLoss',.01)
    fees=number(data,'costBps');slip=number(data,'slippageBps')
    if max(fees,slip)>1000:raise ValueError('Costs/slippage must not exceed 1,000 bps.')
    buy=entry*(1+slip/10000);sell=stop*(1-slip/10000)
    per_unit=buy-sell+(buy+sell)*fees/10000
    quantity=math.floor(min(budget/(buy*(1+fees/10000)),risk/per_unit))
    return dict(quantity=quantity,entry=entry,stop=stop,target=target,estimatedStopLoss=quantity*per_unit,
                estimatedCapital=quantity*buy*(1+fees/10000),riskPerUnit=per_unit,
                grossRewardRisk=(target-entry)/(entry-stop),
                caveat='Illustrative long-only sizing. Stop gaps and unavailable fills can exceed maxLoss. Costs are user assumptions, not verified taxes.')

def risk_check(data):
    result=plan(data)
    exposure=number(data,'exposure');pending=number(data,'pendingExposure');limit=number(data,'maxExposure',.01)
    loss=number(data,'dailyLoss');loss_limit=number(data,'dailyLossLimit',.01)
    reasons=[]
    if result['quantity']<1:reasons.append('Budget or loss limit cannot fund one unit.')
    if exposure+pending+result['estimatedCapital']>limit:reasons.append('Total exposure exceeds limit.')
    if loss>=loss_limit:reasons.append('Daily loss threshold reached.')
    result.update(allowed=not reasons,reasons=reasons,scope='User-entered snapshot only; not broker-reconciled.')
    return result

def series(data):
    if data.get('permitted') is not True:raise ValueError('Confirm permission to use imported data for this analysis.')
    universe=data.get('candles',{})
    if not isinstance(universe,dict) or not 1<=len(universe)<=2000:raise ValueError('Provide a candles object with 1–2,000 symbols.')
    if sum(len(r) for r in universe.values() if isinstance(r,list))>100000:raise ValueError('Limit imports to 100,000 bars per request.')
    cutoff=timestamp(data.get('asOf',''))
    result={}
    for symbol,rows in universe.items():
        if not isinstance(rows,list):raise ValueError('Candles must be lists.')
        valid=validate_rows(rows,cutoff)
        if any(timestamp(r['date']).minute%5 or timestamp(r['date']).second or not dt.time(9,15)<=timestamp(r['date']).time().replace(tzinfo=None)<=dt.time(15,25) for r in valid):
            raise ValueError('Use five-minute NSE-session candle start timestamps, 09:15–15:25 IST.')
        result[str(symbol)[:40]]=[r for r in valid if timestamp(r['date'])+dt.timedelta(minutes=5)<=cutoff]
    return result

def signals(rows):
    if len(rows)<4:return []
    last=rows[-1];prev=rows[-2];day=timestamp(last['date']).date()
    today=[r for r in rows if timestamp(r['date']).date()==day]
    if any(timestamp(b['date'])-timestamp(a['date'])!=dt.timedelta(minutes=5) for a,b in zip(today,today[1:])):return []
    rows=today
    found=[]
    # Require the actual 09:15/20/25 opening bars, not merely the first rows imported.
    opening=[r for r in today if timestamp(r['date']).strftime('%H:%M') in ('09:15','09:20','09:25')]
    if len(opening)==3 and timestamp(last['date']).strftime('%H:%M')>='09:30':
        level=max(float(r['high']) for r in opening)
        if float(prev['close'])<=level<float(last['close']):found.append('opening-range breakout')
    if len(rows)>=21:
        closes=[float(r['close']) for r in rows]
        changes=[b-a for a,b in zip(closes[-15:-1],closes[-14:])]
        gain=sum(max(x,0) for x in changes)/14;loss=sum(max(-x,0) for x in changes)/14
        rsi=100 if loss==0 and gain else (50 if loss==gain==0 else 100-100/(1+gain/loss))
        if rsi<35 and closes[-1]>closes[-2]:found.append('oversold bounce heuristic')
        pole=closes[-7]/closes[-12]-1
        consolidation=rows[-6:-1];upper=max(float(r['high']) for r in consolidation);lower=min(float(r['low']) for r in consolidation)
        if pole>.03 and (upper-lower)/lower<.03 and closes[-2]<=upper<closes[-1]:found.append('bull flag heuristic')
    return found

def scan(data):
    universe=series(data);items=[]
    for symbol,rows in universe.items():
        hits=signals(rows)
        if hits:items.append(dict(symbol=symbol,setups=hits,bar=rows[-1]['date'],close=rows[-1]['close']))
    return dict(matches=items,scanned=len(universe),status='Matches found' if items else 'No qualifying setups',
                rules='Five-minute completed bars only. ORB: first 15-minute high crossed by close. Flag: >3% pole, <3% five-bar range breakout. Bounce: simple 14-change RSI <35 with higher close.',
                limitations='Descriptive unvalidated heuristics; no calendar, spread, event or corporate-action checks. Imported snapshot, not a continuous scan.')

def time_machine(data):
    universe=series(data)
    if len(universe)!=1:raise ValueError('Time Machine takes exactly one symbol per request.')
    symbol,rows=next(iter(universe.items()))
    if not 30<=len(rows)<=2000:raise ValueError('Use 30–2,000 bars for replay.')
    p=plan(data);raw_horizon=number(data,'horizon',1)
    if raw_horizon!=int(raw_horizon):raise ValueError('Horizon must be a whole number of bars.')
    horizon=int(raw_horizon)
    if horizon>100:raise ValueError('Horizon must be 1–100 bars.')
    returns=[float(b['close'])/float(a['close'])-1 for a,b in zip(rows,rows[1:])]
    rng=random.Random(42);outcomes=[];stop_pct=p['stop']/p['entry']-1;target_pct=p['target']/p['entry']-1
    cost=(number(data,'costBps')+number(data,'slippageBps'))/10000
    for _ in range(10000):
        value=1
        for _ in range(horizon):
            value*=1+rng.choice(returns)
            if value-1<=stop_pct or value-1>=target_pct:break
        outcomes.append((value*(1-cost)-(1+cost))*p['entry']*p['quantity'])
    outcomes.sort();events=[]
    for i in range(20,len(rows)-horizon):
        hits=signals(rows[:i+1])
        if hits:
            opening=float(rows[i+1]['open']);closing=float(rows[i+horizon]['close'])
            events.append(dict(signalAt=rows[i]['date'],setups=hits,nextOpen=opening,grossForwardReturnPct=100*(closing/opening-1)))
    return dict(symbol=symbol,sessions=10000,seed=42,horizonBars=horizon,p05=outcomes[499],median=outcomes[4999],p95=outcomes[9499],worstSample=outcomes[0],sampleLossFraction=sum(v<0 for v in outcomes)/10000,
                historicalMatches=events,limitations='IID bootstrap of imported bar returns, not every possible outcome or a calibrated forecast. Thresholds checked at sampled closes; no intrabar fill model. Historical matches use next open and fixed-horizon gross return, not stop/target execution. In-sample descriptive replay; no independent holdout.')

def records(data):
    if data.get('permitted') is not True:raise ValueError('Confirm permission for the imported records.')
    rows=data.get('records',[])
    if not isinstance(rows,list) or len(rows)>5000 or any(not isinstance(r,dict) for r in rows):raise ValueError('Supply at most 5,000 record objects.')
    return rows

def news(data):
    watch={s.strip().upper() for s in str(data.get('watchlist','')).split(',') if s.strip()}
    output=[];seen=set()
    for r in records(data):
        title=str(r.get('title',''));url=str(r.get('url',''));published=str(r.get('publishedAt',''))
        if not url.startswith('https://') or not title or not published:raise ValueError('Each news record needs title, HTTPS url and publishedAt.')
        timestamp(published)
        symbols=r.get('symbols',[])
        if not isinstance(symbols,list):raise ValueError('News symbols must be a list.')
        hits=sorted(watch.intersection(str(s).upper() for s in symbols))
        if hits and url not in seen:
            seen.add(url);output.append(dict(title=title,url=url,publishedAt=published,watchMatches=hits,
                categories=[word for word in ('earnings','merger','dividend','guidance','order','regulatory') if word in title.lower()]))
    return dict(items=sorted(output,key=lambda r:timestamp(r['publishedAt']),reverse=True),status='Imported records only; live feed disconnected',caveat='Keyword categories do not establish why a stock moved. Symbol mapping must be supplied.')

def earnings(data):
    result=[]
    for r in records(data):
        if not str(r.get('source','')).startswith('https://') or not r.get('metric') or not r.get('unit') or not r.get('period') or not r.get('priorPeriod'):raise ValueError('Metrics require source URL, metric, unit, period and priorPeriod.')
        timestamp(r.get('publishedAt',''))
        current=number(r,'current',-1e15);previous=number(r,'previous',-1e15)
        result.append(dict(metric=r['metric'],unit=r['unit'],period=r['period'],priorPeriod=r['priorPeriod'],current=current,previous=previous,change=current-previous,
            changePct=100*(current-previous)/abs(previous) if previous else None,source=r['source'],publishedAt=r['publishedAt']))
    return dict(metrics=result,status='Structured filing comparison; no automatic PDF extraction',caveat='Confirm matching units, accounting basis and comparable periods. Negative-base percentage uses absolute denominator. No investment recommendation.')

def disclosures(data):
    output=[];seen=set()
    for r in records(data):
        needed=('filingId','filer','owner','asset','transactionDate','filedAt','amountRange','source')
        if any(not r.get(k) for k in needed):raise ValueError('Disclosure requires '+', '.join(needed))
        filed=timestamp(r['filedAt']);trans=dt.date.fromisoformat(r['transactionDate'])
        if trans>filed.date():raise ValueError('Transaction date cannot follow filing date.')
        if not str(r['source']).startswith('https://'):raise ValueError('Use an HTTPS disclosure source.')
        key=(r['filingId'],r['asset'],r['transactionDate'],r['owner'])
        if key in seen:continue
        seen.add(key);output.append({**{k:r[k] for k in needed},'filingLagDays':(filed.date()-trans).days})
    return dict(records=output,status='Imported U.S. disclosure records; no continuous filing feed',caveat='Filing time is not trade time; owner may be a spouse. Amounts are reported ranges. No inference of wrongdoing or future returns.')

def dispatch(tool,data):
    if tool in ('scanner','entry'):return scan(data)
    if tool in ('exit','budget'):return plan(data)
    if tool in ('risk','broker'):return risk_check(data)
    if tool=='timemachine':return time_machine(data)
    if tool=='news':return news(data)
    if tool=='analyst':return earnings(data)
    if tool=='pelosi':return disclosures(data)
    if tool=='alerts':
        price=number(data,'price',.01);threshold=number(data,'threshold',.01)
        direction=data.get('direction')
        if direction not in ('above','below'):raise ValueError('Direction must be above or below.')
        return dict(triggered=price>=threshold if direction=='above' else price<=threshold,price=price,threshold=threshold,source='Imported/manual observation',live=False)
    raise ValueError('Unknown trader tool.')
