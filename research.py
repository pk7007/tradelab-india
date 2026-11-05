"""Research-only factors and validation utilities. No broker/order imports."""
import datetime as dt
import hashlib
import json
import math
import statistics

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
VERSION = 'momentum-baseline-v1'


def timestamp(value):
    result = dt.datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('Timezone is required.')
    return result.astimezone(IST)


def validate_rows(rows, as_of):
    """Reject rather than repair ambiguous research inputs; exclude future bars."""
    selected = []
    previous = None
    for row in rows:
        stamp = timestamp(row['date'])
        if previous is not None and stamp <= previous:
            raise ValueError('Duplicate or out-of-order timestamp.')
        previous = stamp
        if stamp > as_of:
            continue
        values = [float(row[k]) for k in ('open', 'high', 'low', 'close', 'volume')]
        o, h, l, c, v = values
        if not all(math.isfinite(x) for x in values) or min(o,h,l,c)<=0 or v<0 or l>min(o,c) or h<max(o,c):
            raise ValueError('Malformed OHLCV candle.')
        selected.append(dict(row))
    return selected


def rank_universe(universe, horizon, interval, as_of):
    cutoff = timestamp(as_of)
    if horizon not in ('intraday', 'swing', 'long-term'):
        raise ValueError('Unknown research horizon.')
    result = {'version': VERSION, 'horizon': horizon, 'asOf': cutoff.isoformat(),
              'status': 'insufficient evidence', 'candidates': [], 'excluded': [],
              'liveAutomation': False, 'validated': False,
              'formula': 'score = 100 × (latest close / close 20 completed bars earlier − 1); descending order; not a probability',
              'limitations': ['Unvalidated descriptive price ranking; not a recommendation.',
                  'No verified corporate actions, historical universe, spreads, sector data or announcement feed.',
                  'Current selected symbols introduce selection and survivorship bias.',
                  'Volume × close is an approximate turnover proxy, not executable liquidity.',
                  'No position sizes, price targets, or financial risk limits are inferred.']}
    if horizon == 'long-term':
        result['reason'] = 'Point-in-time fundamentals, valuation, governance and corporate-action data are unavailable.'
        return result
    if (horizon == 'swing' and interval != 'day') or (horizon == 'intraday' and interval != '5minute'):
        raise ValueError('Swing requires daily candles; intraday requires five-minute candles.')
    for symbol, raw in sorted(universe.items()):
        try:
            rows = validate_rows(raw, cutoff)
            # Treat daily bars as complete only on an earlier local date. Intraday
            # bars are usable only after their full five-minute interval elapsed.
            rows = [r for r in rows if (timestamp(r['date']).date()<cutoff.date() if interval=='day'
                    else timestamp(r['date'])+dt.timedelta(minutes=5)<=cutoff)]
            if horizon == 'intraday':
                rows = [r for r in rows if timestamp(r['date']).date()==cutoff.date()
                        and dt.time(9,15)<=timestamp(r['date']).time().replace(tzinfo=None)<=dt.time(15,25)]
            if len(rows)<21:
                raise ValueError('At least 21 completed candles required in the selected horizon.')
            rows = rows[-21:]
            last = timestamp(rows[-1]['date'])
            if horizon=='intraday':
                if cutoff-last>=dt.timedelta(minutes=10):
                    raise ValueError('Stale intraday data.')
                if any(timestamp(r['date']).minute%5 or timestamp(r['date']).second or timestamp(r['date']).microsecond for r in rows):
                    raise ValueError('Use candles aligned to a five-minute session boundary.')
                if any(timestamp(b['date'])-timestamp(a['date'])!=dt.timedelta(minutes=5) for a,b in zip(rows,rows[1:])):
                    raise ValueError('Missing five-minute candles.')
            elif cutoff-last>dt.timedelta(days=7):
                raise ValueError('Stale daily data; exchange-calendar completeness is unverified.')
            if any(float(r['volume'])<=0 for r in rows):
                raise ValueError('Zero-volume candles: execution evidence insufficient.')
            closes = [float(r['close']) for r in rows]
            momentum = (closes[-1]/closes[0]-1)*100
            returns = [b/a-1 for a,b in zip(closes,closes[1:])]
            vol = statistics.pstdev(returns)*100
            turnover = statistics.mean(float(r['volume'])*float(r['close']) for r in rows)
            if momentum<=0:
                raise ValueError('Non-positive momentum under this baseline; no candidate.')
            result['candidates'].append({'symbol': symbol, 'score': momentum, 'momentumPct':momentum,
                'barVolatilityPct':vol, 'meanTurnoverProxy':turnover, 'dataThrough':last.isoformat(),
                'contributions':{'20BarMomentum':momentum},
                'support':'Positive trailing 20-bar price momentum.',
                'contradictions':'Momentum may reverse; fundamentals, announcements and spreads are unverified.',
                'invalidation':'Non-positive momentum, stale/missing bars, or new contradictory information.',
                'quality':'Price-only evidence; not validated for trading.'})
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            result['excluded'].append({'symbol':symbol,'reason':str(exc)})
    result['candidates'].sort(key=lambda r:(-r['score'],r['symbol']))
    result['status']='unvalidated research candidates' if result['candidates'] else 'no qualifying candidates'
    return result


def chronological_splits(count, label_horizon, minimum_train=60, test_size=20):
    """Expanding folds, purging observations whose future label touches test."""
    if min(count,label_horizon,minimum_train,test_size)<1:
        raise ValueError('Positive split parameters required.')
    return [{'train': [0,start-label_horizon], 'test':[start,start+test_size]}
            for start in range(minimum_train+label_horizon,count-test_size+1,test_size)]


def experiment_record(config, dataset, report):
    """Fingerprint for reproducibility, not a claim of independent validation."""
    encode=lambda v:json.dumps(v,sort_keys=True,allow_nan=False,separators=(',',':')).encode()
    return {'version':VERSION, 'config':config,
            'datasetHash':hashlib.sha256(encode(dataset)).hexdigest(),
            'reportHash':hashlib.sha256(encode(report)).hexdigest(),
            'createdAt':dt.datetime.now(dt.timezone.utc).isoformat(),
            'holdoutIndependent':False, 'liveAutomation':False}


class ResearchRiskGate:
    """Offline contract for future execution adapters; cannot submit orders.

    A new instance is always disarmed. No production broker integration exists.
    """
    def __init__(self):
        self.armed = False
        self.killed = False
        self.seen = set()
        self.uncertain = set()

    def check(self, signal, *, fresh, reconciled, exposure, pending, added,
              exposure_limit, daily_loss, loss_limit):
        numbers=(exposure,pending,added,exposure_limit,daily_loss,loss_limit)
        if not all(isinstance(n,(float,int)) and math.isfinite(n) and n>=0 for n in numbers):
            return False, 'Invalid risk inputs'
        if not self.armed or self.killed: return False, 'Disarmed or killed'
        if not fresh: return False, 'Missing or stale data'
        if not reconciled or self.uncertain: return False, 'Reconciliation required'
        if signal in self.seen: return False, 'Duplicate signal'
        if loss_limit<=0 or daily_loss>=loss_limit: return False, 'Daily loss gate'
        if added<=0 or exposure+pending+added>exposure_limit: return False, 'Exposure gate'
        self.seen.add(signal)
        return True, 'Offline check passed; no order submitted'

    def kill(self, pending_ids):
        self.killed=True
        self.armed=False
        return {'cancelRequests':list(pending_ids), 'positionsClosed':False,
                'message':'Cancellation intents only; broker confirmation required.'}
