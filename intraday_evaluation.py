"""Replay the exact versioned paper engine, never a separately tuned fill model."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from paper import PaperEngine


def evaluate_intraday(request):
    if not isinstance(request, dict) or request.get('permitted') is not True:
        raise ValueError('Explicit permission for temporary local replay is required.')
    config = request.get('config')
    rows = request.get('bars')
    if not isinstance(config, dict) or config.get('strategy') != 'intraday-v1':
        raise ValueError('Supply a versioned intraday-v1 account configuration.')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20000:
        raise ValueError('Supply 1–20,000 completed candles.')
    fingerprint = hashlib.sha256(json.dumps([config, rows],sort_keys=True,allow_nan=False).encode()).hexdigest()
    with TemporaryDirectory() as folder:
        engine = PaperEngine(Path(folder)/'replay.sqlite')
        identity = engine.create(dict(config,permitted=True))['id']
        engine.control(identity,'start')
        for offset in range(0,len(rows),1000):
            engine.ingest(identity,rows[offset:offset+1000],True)
        with engine.db() as db:
            state = engine.load(db,identity)
            events = [json.loads(row[0]) for row in db.execute('SELECT body FROM events WHERE account=? ORDER BY seq',(identity,))]
        verified = engine.reconcile(identity)
        capital = state['config']['capital']
        equity = [capital] + [e['equity'] for e in events if e['type']=='bar']
        peak = equity[0]; drawdown = 0
        for value in equity:
            peak = max(peak,value);drawdown = max(drawdown,1-value/peak)
        return dict(protocol='intraday-v1',fingerprint=fingerprint,source=config.get('source'),
                    finalEquity=state['equity'],returnPct=100*(state['equity']/capital-1),
                    maxDrawdownPct=100*drawdown,fees=state['fees'],realized=state['realized'],
                    openQuantity=state['quantity'],pending=state['pending'],ledgerMatches=verified['matches'],
                    fills=[e for e in events if e['type']=='fill'],
                    decisions=[e for e in events if e['type'] not in ('bar','created','fill')],
                    holdoutIndependent=False,promotionAllowed=False,
                    limitations=['Same engine and sizing as paper, but candle fills are modeled.',
                                 'No independent holdout, point-in-time universe or validated exchange calendar.',
                                 'Unclosed exposure remains marked; no final liquidation is fabricated.',
                                 'No benchmark or future profitability established by this replay.'])
