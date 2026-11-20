"""Legacy 75-bar research protocol; calendar changes require explicit review.

Use batch_loss_audit.py to reproduce the frozen original and
cas_research_batch.py for the bounded, calendar-aware INFY comparison.
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intraday_evaluation import evaluate_intraday


def replay(config, rows):
    result = evaluate_intraday(dict(permitted=True, config=config, bars=rows))
    quantity = 0
    trades = 0
    for fill in result['fills']:
        quantity += fill['quantity'] if fill['side'] == 'BUY' else -fill['quantity']
        if fill['side'] == 'SELL' and quantity == 0:
            trades += 1
    return dict(completedTrades=trades, returnPct=result['returnPct'],
                maxDrawdownPct=result['maxDrawdownPct'], fees=result['fees'],
                openQuantity=result['openQuantity'], ledgerMatches=result['ledgerMatches'],
                fingerprint=result['fingerprint'], fills=result['fills'])


def run(csv_path, config, destination, target=1000):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    variants = [dict(name='baseline', changes={}),
                dict(name='target-1.5', changes={'targetMultiple': 1.5}),
                dict(name='target-2.5', changes={'targetMultiple': 2.5}),
                dict(name='stop-0.75', changes={'stopDistancePct': .75}),
                dict(name='entry-13.30', changes={'entryEnd': '13:30'})]
    policy = dict(targetCompletedTrades=target, baseline=config, variants=variants,
                  partition='Last20 sessions sealed holdout; preceding40 validation; earlier development',
                  episodeSessions=20, episodeStartingCapital=config['capital'],
                  accountPolicy='Each trial episode starts with independent simulated capital.',
                  dataSha256=hashlib.sha256(Path(csv_path).read_bytes()).hexdigest(),
                  createdAt=dt.datetime.now(dt.timezone.utc).isoformat(),
                  source='Kite historical CSV', promotionAllowed=False)
    (destination / 'policy.json').write_text(json.dumps(policy, indent=2), encoding='utf-8')
    with Path(csv_path).open(encoding='utf-8', newline='') as handle:
        rows = [dict(date=row['date'], **{key: float(row[key]) for key in ('open','high','low','close','volume')})
                for row in csv.DictReader(handle)]
    dates = sorted({row['date'][:10] for row in rows})
    if len(dates) < 80:
        raise ValueError('At least80 historical sessions required.')
    by_date = {date: [] for date in dates}
    for row in rows:
        by_date[row['date'][:10]].append(row)
    # The original run silently excluded every shorter CTS session, shifting
    # its final window backwards. Never repeat that selection unnoticed.
    for date, day in by_date.items():
        if date >= '2026-08-03' and dt.date.fromisoformat(date).weekday() < 5 and len(day) == 72:
            expected72 = [(dt.datetime.fromisoformat(date+'T09:15:00+05:30') + dt.timedelta(minutes=5*i)).isoformat() for i in range(72)]
            if [row['date'] for row in day] == expected72:
                raise ValueError('Complete 72-bar session detected: legacy 75-bar partition is unsafe. Review the instrument calendar and use the calendar-aware research workflow.')
    # Special sessions and incomplete days cannot satisfy the current replay contract.
    valid = []
    excluded = []
    for date in dates:
        day = by_date[date]
        expected = [(dt.datetime.fromisoformat(date+'T09:15:00+05:30') + dt.timedelta(minutes=5*i)).isoformat() for i in range(75)]
        if [row['date'] for row in day] == expected and dt.date.fromisoformat(date).weekday() < 5:
            valid.append(date)
        else:
            excluded.append(date)
    if len(valid) < 80:
        raise ValueError('Fewer than80 complete normal sessions remain after quality checks.')
    development, validation, holdout = valid[:-60], valid[-60:-20], valid[-20:]
    def bars(days):
        return [row for date in days for row in by_date[date]]
    completed = 0
    trials = []
    with (destination / 'trials.jsonl').open('w', encoding='utf-8') as log:
        for variant in variants:
            for offset in range(0, len(development), 20):
                days = development[offset:offset+20]
                if len(days) < 20:
                    continue
                result = replay(dict(config, **variant['changes']), bars(days))
                completed += result['completedTrades']
                record = dict(stage='development', variant=variant['name'], start=days[0], end=days[-1], **result)
                log.write(json.dumps(record)+'\n'); log.flush()
                trials.append({key:value for key,value in record.items() if key!='fills'})
                print(json.dumps(dict(completedTrades=completed, variant=variant['name'], through=days[-1])), flush=True)
                if completed >= target:
                    break
            if completed >= target:
                break
        comparisons = []
        for variant in variants:
            result = replay(dict(config, **variant['changes']), bars(validation))
            comparisons.append(dict(variant=variant['name'], **{key:value for key,value in result.items() if key!='fills'}))
            log.write(json.dumps(dict(stage='validation', variant=variant['name'], **result))+'\n')
        chosen = max(comparisons, key=lambda item:(item['returnPct'], -item['maxDrawdownPct']))
        changes = next(item['changes'] for item in variants if item['name'] == chosen['variant'])
        final_baseline = replay(config, bars(holdout))
        final_candidate = replay(dict(config, **changes), bars(holdout))
        log.write(json.dumps(dict(stage='sealed-final-baseline', **final_baseline))+'\n')
        log.write(json.dumps(dict(stage='sealed-final-candidate', variant=chosen['variant'], **final_candidate))+'\n')
    summary = dict(target=target, developmentCompletedTrades=completed,
                   targetReached=completed>=target, developmentEpisodes=len(trials),
                   rawSessions=len(dates), usableSessions=len(valid), excludedSessions=excluded,
                   validation=comparisons, selected=chosen['variant'],
                   holdoutStart=holdout[0], holdoutEnd=holdout[-1],
                   finalBaseline={key:value for key,value in final_baseline.items() if key!='fills'},
                   finalCandidate={key:value for key,value in final_candidate.items() if key!='fills'},
                   promotionAllowed=False,
                   limitations=['Historical modeled OHLC fills', 'Repeated dates across strategy trials are not independent market opportunities',
                                'Capital resets to10000 for each20-session trial episode',
                                'No verified corporate-action adjustment or point-in-time universe',
                                'Real forward-trade minimum and full promotion gates must still pass'])
    (destination / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', type=Path, required=True)
    parser.add_argument('--paper-db', type=Path, required=True)
    parser.add_argument('--account', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target', type=int, default=1000)
    args = parser.parse_args()
    with sqlite3.connect(args.paper_db.resolve().as_uri()+'?mode=ro', uri=True) as db:
        row = db.execute('SELECT body FROM accounts WHERE id=?',(args.account,)).fetchone()
        if row is None:
            raise SystemExit('Configured paper account not found.')
        config = json.loads(row[0])['config']
    print(json.dumps(run(args.csv, config, args.output, args.target), indent=2))
