"""Offline cost attribution and five-bar shadow outcomes on an invented tape."""
import datetime as dt
import json
import math
from pathlib import Path
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evaluation import demo_request, evaluate
from paper import PaperEngine
from research import IST, timestamp


def shadow(db, identity, config):
    bars=[json.loads(row[0]) for row in db.execute('SELECT body FROM bars WHERE account=? ORDER BY stamp',(identity,))]
    dates={bar['date']:i for i,bar in enumerate(bars)}
    fee=config['costBps']/10000
    slip=config['slippageBps']/10000
    results=[]
    for row in db.execute('SELECT body FROM events WHERE account=? ORDER BY seq',(identity,)):
        event=json.loads(row[0])
        if event['type'] not in ('rejected','skipped') or event.get('side')!='BUY':
            continue
        i=dates[event['signalAt']]
        future=bars[i+1:i+6]
        outcome=None
        if len(future)==5 and timestamp(future[-1]['date'])-timestamp(event['signalAt'])==dt.timedelta(minutes=25):
            cost=future[0]['open']*(1+slip)*(1+fee)
            proceeds=future[-1]['close']*(1-slip)*(1-fee)
            outcome=round(config['units']*(proceeds-cost),4)
        results.append(dict(signalAt=event['signalAt'],decisionAt=event.get('bar',event['signalAt']),
                            reason=event['reason'],hypotheticalFiveBarPnl=outcome))
    return results


def run():
    attribution=[]
    for fee,slip in ((0,0),(0,5),(10,5),(20,10)):
        h=evaluate(dict(demo_request(),costBps=fee,slippageBps=slip))['holdout']
        attribution.append(dict(feeBps=fee,slippageBps=slip,strategyPct=h['strategy']['returnPct'],
                                benchmarkPct=h['benchmark']['returnPct'],differencePoints=h['excessReturnPct']))
    with tempfile.TemporaryDirectory() as folder:
        engine=PaperEngine(Path(folder)/'audit.sqlite')
        config=dict(symbol='FIXTURE',source='synthetic',provider='Invented oscillating prices',
                    adjustment='None',permitted=True,capital=10000,units=10,maxExposure=1,
                    dailyLossLimit=100,costBps=10,slippageBps=5)
        identity=engine.create(config)['id']
        engine.control(identity,'start')
        start=dt.datetime(2026,1,2,9,15,tzinfo=IST)
        rows=[]
        opening=100
        for i in range(75):
            close=100+4*math.sin(i/4)
            rows.append(dict(date=(start+dt.timedelta(minutes=i*5)).isoformat(),open=opening,
                             low=min(opening,close)-.01,high=max(opening,close)+.01,close=close,volume=10000))
            opening=close
        account=engine.ingest(identity,rows,True)['account']
        with engine.db() as db:
            opportunities=shadow(db,identity,config)
        outcomes=[r['hypotheticalFiveBarPnl'] for r in opportunities if r['hypotheticalFiveBarPnl'] is not None]
        return dict(source='synthetic',holdout=attribution,shadow=opportunities,
                    shadowWins=sum(x>0 for x in outcomes),shadowLosses=sum(x<0 for x in outcomes),
                    incomplete=len(opportunities)-len(outcomes),actualPaperEquity=account['equity'])

if __name__=='__main__':
    print(json.dumps(run(),indent=2))
