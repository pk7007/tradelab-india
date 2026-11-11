"""Exercise two real TradeLab server processes with one temporary paper database."""
from contextlib import contextmanager
from datetime import datetime, timedelta
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
BOOT = """from app import Handler, LocalServer
with LocalServer(('127.0.0.1',0),Handler) as server:
    print(server.server_port,flush=True)
    server.serve_forever()
"""

@contextmanager
def server(folder):
    env = dict(os.environ, TRADELAB_PAPER_DB=str(folder/'fixture.sqlite'),
               TRADELAB_AUTOMATION_DB=str(folder/'automation.sqlite'),
               TRADELAB_DATA_DIR=str(folder/'data'), TRADELAB_ENABLE_LIVE_ORDERS='false',
               KITE_API_KEY='', KITE_API_SECRET='')
    p = subprocess.Popen([sys.executable,'-c',BOOT],cwd=ROOT,env=env,stdout=subprocess.PIPE,text=True)
    try:
        root = 'http://127.0.0.1:'+str(int(p.stdout.readline().strip()))
        client = request.build_opener(request.ProxyHandler({}),request.HTTPCookieProcessor(CookieJar()))
        with client.open(root+'/trader-paper',timeout=5) as response:
            token=re.search(r'name="csrf-token" content="([^"]+)"',response.read().decode()).group(1)
        def post(endpoint,**data):
            headers={'Content-Type':'application/json','Origin':root,'X-CSRF-Token':token}
            with client.open(request.Request(root+'/api/trader/paper-'+endpoint,json.dumps(data).encode(),headers),timeout=10) as response:
                return json.load(response)
        yield post
    finally:
        p.terminate(); p.wait(timeout=10); p.stdout.close()

def run():
    t=datetime.fromisoformat('2026-01-02T09:15:00+05:30')
    bars=[dict(date=(t+timedelta(minutes=5*i)).isoformat(),open=100+i,high=101+i,low=99+i,close=100+i,volume=10000) for i in range(23)]
    with TemporaryDirectory() as tmp:
        folder=Path(tmp)
        with server(folder) as api:
            acct=api('create',symbol='DEMO',provider='Generated fixture',adjustment='None',source='synthetic',permitted=True,
                     capital=10000,units=10,maxExposure=5000,dailyLossLimit=500,costBps=10,slippageBps=5)['id']
            feed=api('fixture-connect',id=acct)
            params=dict(id=acct,instrument=feed['instrument'],permitted=True)
            api('control',id=acct,action='start')
            before=api('fixture-bars',**params,bars=bars[:20])['account']
            assert before['pending']['side']=='BUY' and before['quantity']==0
            api('fixture-disconnect',id=acct)
        with server(folder) as api:
            restarted=api('state')['accounts'][0]
            assert restarted['pending']==before['pending'] and restarted['status']=='paused' and restarted['feed']['status']=='disconnected'
            api('fixture-connect',id=acct);api('control',id=acct,action='start')
            try:api('fixture-bars',**params,bars=bars[21:22])
            except error.HTTPError as exc:
                assert exc.code==400
                gap=json.load(exc)['error']
                assert 'Missing five-minute' in gap
            else:raise AssertionError('Gap accepted')
            assert api('state')['accounts'][0]['feed']['lastError']==gap
            recovery=api('fixture-bars',**params,bars=bars[18:])
            replay=api('fixture-bars',**params,bars=bars[18:])
            s=api('state')['accounts'][0]
            check=api('reconcile',id=acct)
            assert recovery['duplicates']==2 and replay['processed']==0 and check['fills']==1
            assert check['matches'] and check['quantity']==10 and abs(check['cash']-8798.1994)<1e-6
            assert abs(s['equity']-(check['cash']+check['quantity']*122))<1e-6
            return dict(mode='fixture replay', source=feed['source'], instrument=feed['instrument'],
                        restartStatus=restarted['status'], restoredIntent=before['pending'], gapRejected=gap,
                        overlapSkipped=recovery['duplicates'], retransmissionSkipped=replay['duplicates'],
                        reconstructed=check, dashboardEquity=s['equity'],realized=s['realized'],
                        lastExchangeBar=s['lastBar'],lastReceipt=s['feed']['received'],liveOrders=0)

if __name__=='__main__':
    print(json.dumps(run(),indent=2))
