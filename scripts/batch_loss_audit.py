"""Independent fill accounting and immutable, offline batch re-verification.

Never connects to a broker or writes an existing account. Output contains private
trade evidence and must be stored outside the repository.
"""
import argparse
from collections import Counter, defaultdict
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import random
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intraday_evaluation import evaluate_intraday
from strategy_contract import target_long

VERSION = 'loss-audit-v1'


def current_tariff_counterfactual(fills):
    """2026-11-20 published NSE equity-intraday tariff, fixed fills only.

    Excludes rounding/contract-note aggregation, API subscriptions, penalties,
    dealer square-off and actual historic tariff changes. Not actual charges.
    """
    total=0.0
    for fill in fills:
        value=fill['quantity']*fill['price']
        brokerage=min(20.0,value*.0003)
        exchange=value*.0000307
        sebi=value*.000001
        gst=.18*(brokerage+exchange+sebi)
        stt=value*.00025 if fill['side']=='SELL' else 0.0
        stamp=value*.00003 if fill['side']=='BUY' else 0.0
        total+=brokerage+exchange+sebi+gst+stt+stamp
    return total


def churn(trades, by_day):
    counts = Counter()
    examples = []
    previous = None
    for trade in trades:
        stamp = dt.datetime.fromisoformat(trade['entry'])
        signal = (stamp-dt.timedelta(minutes=5)).isoformat()
        day = by_day[trade['entry'][:10]]
        closes = [r['close'] for r in day if r['date'] <= signal]
        if len(closes) == 20:
            counts['firstEligibleWindow'] += 1
        elif len(closes) > 20:
            counts['freshCrossover' if not target_long(closes[:-1]) else 'bullishStateWithoutFreshCross'] += 1
        if previous and previous['exit'][:10] == trade['entry'][:10]:
            counts['sameSessionReentry'] += 1
            counts['after:'+previous['reason']] += 1
            if len(examples)<5:
                examples.append(dict(previousExit=previous['exit'],entry=trade['entry'],
                                     priorReason=previous['reason'],netPnl=trade['net']))
        previous=trade
    return dict(counts=dict(counts),examples=examples,
                note='Crossover checked before entry. Same-day reentries are descriptive, not proof of causation.')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def accounting(fills, config):
    """Group partial sells until flat; never join episodes or round cents early."""
    quantity = 0
    basis = fees = slipped_gross = raw_gross = turnover = 0.0
    trades = []
    current = None
    for index, fill in enumerate(fills):
        units, price, fee = fill['quantity'], fill['price'], fill['fee']
        if type(units) is not int or units <= 0 or fill['side'] not in ('BUY', 'SELL'):
            raise ValueError('Invalid fill contract')
        buy = fill['side'] == 'BUY'
        raw = price / (1 + config['slippageBps']/10000 * (1 if buy else -1))
        if abs(fee - units*price*config['costBps']/10000) > 1e-7:
            raise ValueError('Fee inconsistency')
        if buy:
            if not quantity:
                current = dict(entry=fill['bar'], entryIndex=index, quantity=0,
                               fees=0.0, gross=0.0, rawGross=0.0, turnover=0.0)
            quantity += units
            basis += units*price+fee
            current['quantity'] += units
        elif units > quantity:
            raise ValueError('Sell exceeds owned shares')
        else:
            quantity -= units
        sign = -1 if buy else 1
        fees += fee
        slipped_gross += sign*units*price
        raw_gross += sign*units*raw
        turnover += units*price
        current['fees'] += fee
        current['gross'] += sign*units*price
        current['rawGross'] += sign*units*raw
        current['turnover'] += units*price
        if not buy:
            basis *= quantity/(quantity+units)
            if not quantity:
                current.update(exit=fill['bar'], reason=fill.get('reason','unspecified'))
                current['net'] = current['gross']-current['fees']
                current['slippage'] = current['rawGross']-current['gross']
                current['holdingMinutes'] = (dt.datetime.fromisoformat(current['exit'])-
                                             dt.datetime.fromisoformat(current['entry'])).total_seconds()/60
                trades.append(current)
                current = None
    return dict(trades=trades, openQuantity=quantity, remainingBasis=basis,
                cashDelta=slipped_gross-fees, fees=fees, grossPricePnl=raw_gross,
                modeledSlippage=raw_gross-slipped_gross, turnover=turnover)


def metrics(trades):
    pnl = [t['net'] for t in trades]
    wins = [v for v in pnl if v > 0]
    losses = [v for v in pnl if v < 0]
    days = defaultdict(list)
    for t in trades:
        days[t['entry'][:10]].append(t['net'])
    lower = upper = None
    if len(days) >= 10:
        rng = random.Random(2031)
        clusters = list(days.values())
        samples = []
        for _ in range(2000):
            selected = rng.choices(clusters, k=len(clusters))
            samples.append(sum(map(sum, selected))/sum(map(len, selected)))
        samples.sort()
        lower, upper = samples[49], samples[1949]
    def grouped(key):
        buckets = defaultdict(list)
        for t in trades:
            buckets[key(t)].append(t['net'])
        return {k:dict(trades=len(v), netPnl=sum(v), expectancy=statistics.mean(v))
                for k,v in sorted(buckets.items())}
    return dict(completedTrades=len(pnl), netPnl=sum(pnl),
                grossPricePnl=sum(t['rawGross'] for t in trades),
                modeledSlippage=sum(t['slippage'] for t in trades),
                explicitFees=sum(t['fees'] for t in trades),
                winRatePct=100*len(wins)/len(pnl) if pnl else None,
                expectancy=statistics.mean(pnl) if pnl else None,
                profitFactor=sum(wins)/-sum(losses) if losses else None,
                averageWin=statistics.mean(wins) if wins else None,
                averageLoss=statistics.mean(losses) if losses else None,
                meanHoldingMinutes=statistics.mean(t['holdingMinutes'] for t in trades) if trades else None,
                turnover=sum(t['turnover'] for t in trades),
                expectancySessionBootstrap95=[lower,upper],
                uncertaintyLimit='Descriptive session bootstrap; no serial or selection correction. Not a promotion test.',
                byYear=grouped(lambda t:t['entry'][:4]),
                byEntryHour=grouped(lambda t:t['entry'][11:13]),
                byExitReason=grouped(lambda t:t['reason']))


def run(original, csv_path, output):
    original, csv_path, output = Path(original), Path(csv_path), Path(output)
    policy = json.loads((original/'policy.json').read_text(encoding='utf-8'))
    summary = json.loads((original/'summary.json').read_text(encoding='utf-8'))
    records = [json.loads(line) for line in (original/'trials.jsonl').read_text(encoding='utf-8').splitlines()]
    if digest(csv_path) != policy['dataSha256']:
        raise ValueError('Original CSV fingerprint mismatch')
    output.mkdir(parents=True, exist_ok=False)
    with csv_path.open(encoding='utf-8', newline='') as handle:
        rows = [dict(date=r['date'], **{k:float(r[k]) for k in ('open','high','low','close','volume')})
                for r in csv.DictReader(handle)]
    by_day = defaultdict(list)
    for row in rows:
        by_day[row['date'][:10]].append(row)
    valid = sorted(set(by_day)-set(summary['excludedSessions']))
    validation, final = valid[-60:-20], valid[-20:]
    # Frozen before running any new comparison. This deliberately does not
    # call historical unused ranges independent after future evidence was seen.
    candidates = [dict(name='entry-12', changes={'entryEnd':'12:00'}),
                  dict(name='entry-13', changes={'entryEnd':'13:00'}),
                  dict(name='entry-13-early-exit', changes={'entryEnd':'13:00','squareOff':'15:05'})]
    registration = dict(version=VERSION, createdAt=dt.datetime.now(dt.timezone.utc).isoformat(),
                        implementationSha256=digest(__file__),
                        sourceHashes={p.name:digest(p) for p in original.iterdir() if p.is_file()},
                        csvSha256=digest(csv_path), baseline=policy['baseline'], candidates=candidates,
                        validationSessions=validation, consumedFinalSessions=final,
                        finalEvaluation='Blocked: previous final exposed; current calendar model cannot safely replay the newer CAS sessions.',
                        rule='Exploratory comparisons only; no promotion, no active account changes.',
                        hypothesis='Reduce time exposed and turnover; fewer trades can miss trends. Exit remains next modeled open.',
                        selection='No candidate selected for promotion; all results retained.')
    (output/'registration.json').write_text(json.dumps(registration,indent=2),encoding='utf-8')
    comparisons = []
    development_trades = []
    unique = set()
    corrected = []
    for index,record in enumerate(records):
        variant = record.get('variant','baseline')
        changes = next(v['changes'] for v in policy['variants'] if v['name']==variant)
        config = dict(policy['baseline'],**changes)
        audit = accounting(record['fills'],config)
        result = metrics(audit['trades'])
        result.update(stage=record['stage'], variant=variant, episode=index,
                      maxDrawdownPct=record['maxDrawdownPct'], openQuantity=audit['openQuantity'],
                      ledgerMatches=record['ledgerMatches'], reportedCompleted=record['completedTrades'],
                      reportedNet=config['capital']*record['returnPct']/100)
        result['churn'] = churn(audit['trades'],by_day)
        result['currentTariffFixedFillCounterfactual'] = dict(
            asOf='2026-11-20',source='https://zerodha.com/charges/',
            estimatedFees=current_tariff_counterfactual(record['fills']),
            netPnl=result['netPnl']+audit['fees']-current_tariff_counterfactual(record['fills']) if not audit['openQuantity'] else None,
            limitations='Current tariff on frozen fills, not historical actuals or a resized strategy replay; excludes rounding, API subscription and incident charges.')
        result['sessions'] = (record.get('start'),record.get('end')) if record['stage']=='development' else (
            (validation[0],validation[-1]) if record['stage']=='validation' else (final[0],final[-1]))
        result['accountingMatches'] = (result['completedTrades']==record['completedTrades'] and
            abs(audit['fees']-record['fees'])<1e-6 and audit['openQuantity']==record['openQuantity'] and
            (audit['openQuantity']!=0 or abs(result['netPnl']-result['reportedNet'])<1e-6))
        comparisons.append(result)
        if record['stage']=='development':
            for trade in audit['trades']:
                entry=(index,trade['entryIndex'],trade['entry'])
                if entry in unique: raise ValueError('Duplicate entry sequence')
                unique.add(entry)
            development_trades += audit['trades']
            days=[d for d in valid if record['start']<=d<=record['end']]
        elif record['stage']=='validation': days=validation
        else: days=final
        report=evaluate_intraday(dict(permitted=True, config=config,
                                      bars=[r for d in days for r in by_day[d]]))
        replayed=accounting(report['fills'],config)
        corrected.append(dict(stage=record['stage'],variant=variant,episode=index,
                              identicalFills=report['fills']==record['fills'],
                              fingerprintMatches=report['fingerprint']==record['fingerprint'],
                              **metrics(replayed['trades']),maxDrawdownPct=report['maxDrawdownPct'],
                              ledgerMatches=report['ledgerMatches'],openQuantity=report['openQuantity']))
        print(json.dumps(dict(verified=index+1,of=len(records))),flush=True)
    exploratory=[]
    baseline=policy['baseline']
    for candidate in candidates+[
            dict(name='baseline-half-costs',changes={'costBps':5,'slippageBps':2.5}),
            dict(name='baseline-double-costs',changes={'costBps':20,'slippageBps':10})]:
        config=dict(baseline,**candidate['changes'])
        report=evaluate_intraday(dict(permitted=True,config=config,bars=[r for d in validation for r in by_day[d]]))
        exploratory.append(dict(name=candidate['name'],changes=candidate['changes'],
                                **metrics(accounting(report['fills'],config)['trades']),
                                maxDrawdownPct=report['maxDrawdownPct'],ledgerMatches=report['ledgerMatches'],
                                openQuantity=report['openQuantity'],fingerprint=report['fingerprint'],promotionAllowed=False))
    findings=dict(version=VERSION,originalComparisons=comparisons,correctedFrozenReplays=corrected,
                  development=metrics(development_trades),uniqueEntries=len(unique),
                  developmentChurn=churn(development_trades,by_day),
                  episodes=sum(r['stage']=='development' for r in records),
                  exploratory=exploratory,allAccountingMatches=all(r['accountingMatches'] for r in comparisons),
                  allFrozenFillsIdentical=all(r['identicalFills'] for r in corrected),
                  promotionAllowed=False,realOrdersEnabled=False)
    (output/'audit.json').write_text(json.dumps(findings,indent=2),encoding='utf-8')
    return findings


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original',required=True);p.add_argument('--csv',required=True);p.add_argument('--output',required=True)
    args=p.parse_args(); result=run(args.original,args.csv,args.output)
    print(json.dumps({k:v for k,v in result.items() if k not in ('originalComparisons','correctedFrozenReplays','exploratory')},indent=2))
