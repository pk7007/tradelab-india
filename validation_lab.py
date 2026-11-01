"""Synthetic execution stress lab, intentionally disconnected from broker data."""
import math
import random
from research import experiment_record


def simulate(bars, *, capital, units, fee_bps, slippage_bps, participation, stop_pct, delay=1):
    """Explicit synthetic assumptions, fixed-unit long-only SMA(5/20).

    Next-open execution; gap stops use opening price. Intrabar stop liquidity
    uses full bar volume, an optimistic limitation. No queue/market impact model.
    """
    nums=(capital,units,fee_bps,slippage_bps,participation,stop_pct)
    if not all(math.isfinite(x) for x in nums) or capital<=0 or units<1 or int(units)!=units or not 0<=fee_bps<=100 or not 0<=slippage_bps<=100 or not 0<participation<=1 or not 0<stop_pct<1 or not isinstance(delay,int) or delay<1:
        raise ValueError('Invalid explicit simulation settings.')
    if not bars: raise ValueError('No bars.')
    cash=capital; quantity=0; entry=0; pending=None; fills=[]; equity=[]; fees=0; turnover=0; active=0; rejected=0
    round_trips=[]; basis=0; realized=0; peak=capital; max_dd=0; underwater=0; longest_underwater=0
    for i,b in enumerate(bars):
        o,h,l,c,v=[float(b[k]) for k in ('open','high','low','close','volume')]
        if not all(math.isfinite(x) for x in (o,h,l,c,v)) or min(o,h,l,c)<=0 or v<0 or l>min(o,c) or h<max(o,c):
            raise ValueError('Invalid synthetic bar.')
        capacity=int(v*participation) if not b.get('halted') else 0
        side=None; raw=o; requested=0; reason='signal'
        if quantity and l<=entry*(1-stop_pct):
            side='sell'; raw=min(o,entry*(1-stop_pct)); requested=quantity; reason='stop'; pending=None
        elif pending and pending['at']<=i:
            side=pending['side']; requested=pending['remaining']
        if side:
            if b.get('reject'):
                rejected+=1; pending=None
            else:
                fill=raw*(1+slippage_bps/10000 if side=='buy' else 1-slippage_bps/10000)
                count=min(requested,capacity)
                if side=='buy': count=min(count,int(cash/(fill*(1+fee_bps/10000))))
                else: count=min(count,quantity)
                if count:
                    fee=count*fill*fee_bps/10000
                    fees+=fee; turnover+=count*fill
                    if side=='buy':
                        entry=(entry*quantity+fill*count)/(quantity+count)
                        cash-=count*fill+fee; quantity+=count; basis+=count*fill+fee
                    else:
                        allocated=basis*count/quantity
                        pnl=count*fill-fee-allocated
                        realized+=pnl; basis-=allocated; cash+=count*fill-fee; quantity-=count
                        if quantity==0: round_trips.append(realized); realized=0; basis=0; entry=0
                    fills.append({'bar':i,'side':side,'quantity':count,'price':fill,'fee':fee,'reason':reason})
                remaining=requested-count
                pending={'at':i+1,'side':side,'remaining':remaining} if remaining else None
        value=cash+quantity*c
        if cash<-1e-7 or quantity<0: raise AssertionError('Portfolio accounting failed.')
        peak=max(peak,value); max_dd=max(max_dd,1-value/peak)
        underwater=underwater+1 if value<peak-1e-8 else 0
        longest_underwater=max(longest_underwater,underwater)
        active+=int(quantity>0); equity.append(value)
        if i>=19 and pending is None:
            recent=[float(x['close']) for x in bars[i-19:i+1]]
            positive=sum(recent[-5:])/5>sum(recent)/20
            if positive and quantity==0: pending={'at':i+delay,'side':'buy','remaining':units}
            elif not positive and quantity>0: pending={'at':i+delay,'side':'sell','remaining':quantity}
    wins=[p for p in round_trips if p>0]; losses=[p for p in round_trips if p<=0]
    changes=[b/a-1 for a,b in zip([capital]+equity[:-1],equity)]
    return {'finalEquity':equity[-1],'cash':cash,'openQuantity':quantity,
            'returnPct':100*(equity[-1]/capital-1),'maxDrawdownPct':100*max_dd,
            'longestUnderwaterBars':longest_underwater,'exposurePct':100*active/len(bars),
            'turnoverToCapital':turnover/capital,'fees':fees,'rejectedOrders':rejected,
            'completedTrades':len(round_trips),'winRatePct':100*len(wins)/len(round_trips) if round_trips else None,
            'averageWin':sum(wins)/len(wins) if wins else None,'averageLoss':sum(losses)/len(losses) if losses else None,
            'expectancy':sum(round_trips)/len(round_trips) if round_trips else None,
            'worstBarReturnPct':100*min(changes),'fills':fills,
            'benchmarkGrossReturnPct':100*(bars[-1]['close']/bars[0]['open']-1),
            'benchmarkNote':'Gross price-only buy-and-hold reference; not a matched net executable benchmark.',
            'equity':equity}


def stress_suite():
    settings=dict(capital=100000,units=10,fee_bps=10,slippage_bps=5,participation=.01,stop_pct=.05)
    rng=random.Random(721); scenarios={}
    for name in ('rising','declining','sideways','gap_crash','halted','low_liquidity','rejected','volatile'):
        bars=[]; price=100.
        for i in range(160):
            o=price
            change=.003 if name not in ('declining','sideways','volatile') else (-.004 if name=='declining' else rng.gauss(0,.003 if name=='sideways' else .06))
            if name=='gap_crash' and i==80:o*=.65
            price=max(1,o*(1+change))
            bars.append(dict(open=o,high=max(o,price)*1.002,low=min(o,price)*.998,close=price,
                             volume=100 if name=='low_liquidity' else 10000,
                             halted=name=='halted' and 30<=i<=90,reject=name=='rejected'))
        scenarios[name]=bars
    results=[]
    for name,bars in scenarios.items():
        for variant, overrides in [('base',{}),('higher_costs',dict(fee_bps=40,slippage_bps=50)),('delayed',dict(delay=3))]:
            cfg=settings|overrides; report=simulate(bars,**cfg)
            results.append({'scenario':name,'variant':variant,
                            **{k:v for k,v in report.items() if k not in ('fills','equity')},
                            'record':experiment_record(cfg,bars,report)})
    return {'label':'SYNTHETIC STRESS TESTS — not market performance', 'seed':721,'settings':settings,'results':results,
            'limitations':['Demonstration settings are not user risk limits.',
                'No tax schedule, order queue, exchange circuits, corporate actions or portfolio correlation model.',
                'Full-bar volume can overstate liquidity at the stop price.',
                'No walk-forward profitability claim or independent holdout evaluation.',
                'Loss thresholds cannot guarantee realized loss limits.'], 'liveAutomation':False}
