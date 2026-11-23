"""Bounded CAS calendar repair experiment; no broker/account mutations.

Registers the latest twenty normal sessions before validation comparisons and
leaves them unopened when candidates fail. All results remain research-only.
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.batch_loss_audit import accounting, churn, metrics
from scripts.data_quality_audit import audit_rows, CAS_SOURCE
from intraday_evaluation import evaluate_intraday


def run(csv_path, original, destination):
    csv_path,original,destination=Path(csv_path),Path(original),Path(destination)
    baseline=json.loads((original/'policy.json').read_text(encoding='utf-8'))['baseline']
    with csv_path.open(encoding='utf-8',newline='') as file:
        rows=[dict(date=r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume')})
              for r in csv.DictReader(file)]
    quality=audit_rows(rows,'2026-08-03')
    if quality['rowIssues'] or quality['missingBars'] or quality['unexpectedBars']:
        raise ValueError('Quality issues require review')
    # Explicit instrument binding, not a rule for arbitrary NSE equities.
    metadata=json.loads(csv_path.with_suffix('.json').read_text(encoding='utf-8'))
    if metadata['instrument']['instrument_token']!=408065 or metadata['symbol']!='INFY':
        raise ValueError('This bounded experiment requires the verified INFY dataset')
    dates=[s['date'] for s in quality['sessions'] if s['kind']=='cas_cts' and s['complete']]
    if len(dates)<60:raise ValueError('Need sixty complete normal CAS sessions')
    validation,final=dates[-60:-20],dates[-20:]
    by_day={d:[r for r in rows if r['date'][:10]==d] for d in dates}
    def subset(days):return [r for d in days for r in by_day[d]]
    calendar=dict(exchange='NSE',segment='EQ',version='infy-cas-cts-research-v1',source=CAS_SOURCE,
                  availableAt='2026-08-03T00:00:00+05:30',sessions={
                      d:dict(open=d+'T09:15:00+05:30',close=d+'T15:15:00+05:30') for d in dates})
    calendar['holidaySource']='https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf'
    # Complete the evaluated range using the published holiday list. An absent
    # weekday in the price file is never silently classified as a holiday.
    holiday_dates={'2026-09-14','2026-10-02','2026-10-20'}
    day=dt.date.fromisoformat(validation[0])
    while day<=dt.date.fromisoformat(validation[-1]):
        key=day.isoformat()
        if key not in calendar['sessions']:
            if day.weekday()>=5 or key in holiday_dates:
                calendar['sessions'][key]=None
            else:
                raise ValueError('Unknown absent weekday requires calendar review')
        day+=dt.timedelta(days=1)
    candidates=[dict(name='entry-12',changes={'entryEnd':'12:00'}),
                dict(name='entry-13',changes={'entryEnd':'13:00'}),
                dict(name='entry-13-early-exit',changes={'entryEnd':'13:00','squareOff':'15:05'})]
    # A named calendar repair changes ONLY this isolated comparison's square-off.
    # Never relabel the original 15:15 account configuration as repaired results.
    safe_baseline=dict(baseline,squareOff='15:10')
    final_hash=hashlib.sha256(json.dumps(subset(final),sort_keys=True).encode()).hexdigest()
    destination.mkdir(parents=True,exist_ok=False)
    registration=dict(createdAt=dt.datetime.now(dt.timezone.utc).isoformat(),
                      version='cas-research-v1',scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      dataSha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                      baseline=safe_baseline,originalBaseline=baseline,calendar=calendar,
                      candidates=candidates,validationDates=validation,reservedDates=final,reservedSha256=final_hash,
                      comparisons=3,maxDrawdownPct=10,minTrades=30,
                      gate='Positive expectancy, lower bootstrap bound, minimum sample, drawdown, ledger, flat exposure and positive stress required. Multiple comparisons remain exploratory; no automatic reserve access or promotion.',
                      selection='Highest validation net outcome, then lower drawdown; do not open reserve if any financial gate fails.',
                      provenance='Price-file shape audited previously; no CAS strategy outcomes evaluated before this registration. This is not blind external verification.',
                      originalFinalConsumed=True,promotionAllowed=False)
    (destination/'registration.json').write_text(json.dumps(registration,indent=2),encoding='utf-8')
    results=[]
    for candidate in [dict(name='calendar-baseline',changes={})]+candidates:
        config=dict(safe_baseline,**candidate['changes'])
        report=evaluate_intraday(dict(permitted=True,config=config,bars=subset(validation),calendar=calendar))
        trades=accounting(report['fills'],config)['trades']
        result=dict(name=candidate['name'],config=config,**metrics(trades),
                    returnPct=report['returnPct'],maxDrawdownPct=report['maxDrawdownPct'],
                    ledgerMatches=report['ledgerMatches'],openQuantity=report['openQuantity'],
                    fingerprint=report['fingerprint'],churn=churn(trades,by_day))
        results.append(result)
    chosen=max(results[1:],key=lambda r:(r['netPnl'],-r['maxDrawdownPct']))
    stress_config=dict(chosen['config'],costBps=20,slippageBps=10)
    stress=evaluate_intraday(dict(permitted=True,config=stress_config,bars=subset(validation),calendar=calendar))
    stress_metrics=metrics(accounting(stress['fills'],stress_config)['trades'])
    stress_metrics.update(maxDrawdownPct=stress['maxDrawdownPct'],
                          ledgerMatches=stress['ledgerMatches'],openQuantity=stress['openQuantity'])
    financial_pass=(chosen['expectancy'] or 0)>0 and (chosen['expectancySessionBootstrap95'][0] or 0)>0 and chosen['maxDrawdownPct']<=10 and chosen['completedTrades']>=30 and (stress_metrics['expectancy'] or 0)>0 and chosen['ledgerMatches'] and stress['ledgerMatches'] and chosen['openQuantity']==0 and stress['openQuantity']==0 and stress['maxDrawdownPct']<=10
    # This offline utility deliberately has no route for opening/promoting final
    # evidence: an independent reviewer and executable forward evidence are absent.
    result=dict(registration=registration,validation=results,chosenForReview=chosen['name'],
                stress=stress_metrics,financialGatesPassed=financial_pass,
                reservedOpened=False,reservedState='sealed-not-evaluated',promotionAllowed=False,
                benchmark='Calendar-repaired identical strategy plus zero-return idle-cash comparator',
                limitations=['OHLC fills are retrospective','Corporate actions not independently verified',
                             'No real executable forward minimum','Validation exploratory; three related comparisons',
                             'No reserve result or profitability claim; no live activation'])
    (destination/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(dict(validation=[{k:r[k] for k in ('name','completedTrades','grossPricePnl','explicitFees','modeledSlippage','netPnl','maxDrawdownPct')} for r in results],chosen=chosen['name'],reservedOpened=False,promotionAllowed=False),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--csv',required=True);p.add_argument('--original',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();run(a.csv,a.original,a.output)
