"""Replay the exact versioned paper engine, never a separately tuned fill model."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from paper import PaperEngine
from strategy_contract import VERSION as SIGNAL_CONTRACT


def evaluate_intraday(request):
    if not isinstance(request, dict) or request.get('permitted') is not True:
        raise ValueError('Explicit permission for temporary local replay is required.')
    config = request.get('config')
    rows = request.get('bars')
    if not isinstance(config, dict) or config.get('strategy') != 'intraday-v1':
        raise ValueError('Supply a versioned intraday-v1 account configuration.')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20000:
        raise ValueError('Supply 1–20,000 completed candles.')
    calendar=request.get('calendar')
    evidence=[config, rows] if calendar is None else [config, rows, calendar, 'explicit-session-calendar-v1']
    fingerprint = hashlib.sha256(json.dumps(evidence,sort_keys=True,allow_nan=False).encode()).hexdigest()
    implementation_hashes={name:hashlib.sha256((Path(__file__).resolve().parent/name).read_bytes()).hexdigest()
                           for name in ('paper.py','intraday_contract.py','strategy_contract.py','intraday_evaluation.py')}
    with TemporaryDirectory() as folder:
        engine = PaperEngine(Path(folder)/'replay.sqlite')
        identity = engine.create(dict(config,permitted=True))['id']
        engine.control(identity,'start')
        for offset in range(0,len(rows),1000):
            engine.ingest(identity,rows[offset:offset+1000],True,
                          session_calendar=request.get('calendar'))
        with engine.db() as db:
            state = engine.load(db,identity)
            events = [json.loads(row[0]) for row in db.execute('SELECT body FROM events WHERE account=? ORDER BY seq',(identity,))]
        verified = engine.reconcile(identity)
        capital = state['config']['capital']
        equity = [capital] + [e['equity'] for e in events if e['type']=='bar']
        peak = equity[0]; drawdown = 0
        for value in equity:
            peak = max(peak,value);drawdown = max(drawdown,1-value/peak)
        return dict(protocol='intraday-v1',signalContract=SIGNAL_CONTRACT,
                    fingerprint=fingerprint,source=config.get('source'),
                    implementationVersion='intraday-v1-calendar-aware-20261120',implementationHashes=implementation_hashes,
                    calendarFingerprint=hashlib.sha256(json.dumps(calendar,sort_keys=True,allow_nan=False).encode()).hexdigest() if calendar is not None else None,
                    finalEquity=state['equity'],returnPct=100*(state['equity']/capital-1),
                    maxDrawdownPct=100*drawdown,fees=state['fees'],realized=state['realized'],
                    openQuantity=state['quantity'],pending=state['pending'],ledgerMatches=verified['matches'],
                    fills=[e for e in events if e['type']=='fill'],
                    decisions=[e for e in events if e['type'] not in ('bar','created','fill')],
                    holdoutIndependent=False,promotionAllowed=False,
                    executionTiming='Retrospective OHLC: prior completed-close signal, assumed next open; full-bar volume and range are only known at completion.',
                    limitations=['Same engine and sizing as paper, but candle fills are modeled.',
                                 'No independent holdout, point-in-time universe or validated exchange calendar.',
                                 'Unclosed exposure remains marked; no final liquidation is fabricated.',
                                 'No benchmark or future profitability established by this replay.'])
