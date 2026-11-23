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


def _short(value,limit=40):
    try: text=repr(value)
    except Exception: text='<unrepresentable>'
    return text if len(text)<=limit else text[:limit]+'...'


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
        if not all(not isinstance(n,bool) and isinstance(n,(float,int)) and math.isfinite(n) and n>=0 for n in numbers):
            return False, 'Invalid risk inputs'
        if not self.armed or self.killed: return False, 'Disarmed or killed'
        if fresh is not True: return False, 'Missing or stale data'
        if reconciled is not True or self.uncertain: return False, 'Reconciliation required'
        if signal in self.seen: return False, 'Duplicate signal'
        if loss_limit<=0 or daily_loss>=loss_limit: return False, 'Daily loss gate'
        if added<=0 or exposure+pending+added>exposure_limit: return False, 'Exposure gate'
        self.seen.add(signal)
        return True, 'Offline check passed; no order submitted'

    def kill(self, pending_ids, open_positions=None):
        """Disarm permanently and return INTENTS only; nothing is submitted.

        Never raises: the gate is always killed and disarmed, and the cancel
        list is always returned. Killing stops new entries (check() refuses
        afterwards) but does not by itself neutralise existing exposure.

        pending_ids: list/tuple/set of non-empty strings (a bare string counts
        as one id); anything else is ignored. Dropped ids are listed in
        rejectedCancelIds.

        open_positions: list of dicts with symbol, side BUY/SELL and quantity
        (finite number > 0, not bool). Valid same-symbol/same-side rows are
        merged and yield one opposite-side exit intent (intentOnly=True,
        submitted=False). Invalid rows, and symbols with conflicting sides
        (ambiguous net exit), yield no intent and are listed in
        rejectedPositions; other symbols are unaffected. A non-list argument
        yields no exits and one rejection.

        exposureStatus: UNKNOWN_NOT_FLATTENED if positions were not supplied
        or any row was rejected; NO_OPEN_POSITIONS_REPORTED for an empty list;
        FLATTEN_REQUESTED only when every row was valid and an exit intent
        exists. FLATTENED is never reported and positionsClosed stays False:
        only broker/ledger reconciliation can confirm closure.
        """
        self.killed=True
        self.armed=False
        try: cancels,bad_ids=self._clean_ids(pending_ids)
        except Exception: cancels,bad_ids=[],['<unprocessable pending_ids>']
        exits,rejected=[],[]
        status='UNKNOWN_NOT_FLATTENED'
        if open_positions is not None:
            try:
                exits,rejected=self._exit_intents(open_positions)
            except Exception:  # kill must never raise
                exits,rejected=[],[{'index':None,'symbol':None,'reason':'Unprocessable positions'}]
            if rejected: status='UNKNOWN_NOT_FLATTENED'
            elif exits: status='FLATTEN_REQUESTED'
            else: status='NO_OPEN_POSITIONS_REPORTED'
        return {'cancelRequests':cancels, 'rejectedCancelIds':bad_ids,
                'exitRequests':exits, 'rejectedPositions':rejected,
                'exposureStatus':status, 'positionsClosed':False,
                'message':'Cancellation and exit intents only; nothing submitted; '
                          'broker confirmation and reconciliation required.'}

    @staticmethod
    def _clean_ids(pending_ids):
        if pending_ids is None: return [],[]
        if isinstance(pending_ids,str): pending_ids=[pending_ids]
        if not isinstance(pending_ids,(list,tuple,set,frozenset)):
            return [],[_short(pending_ids)]
        good,bad=[],[]
        for pid in pending_ids:
            if isinstance(pid,str) and pid.strip():
                if pid not in good: good.append(pid)
            else: bad.append(_short(pid))
        return good,bad

    @staticmethod
    def _exit_intents(open_positions):
        if not isinstance(open_positions,(list,tuple)):
            return [],[{'index':None,'symbol':None,'reason':'open_positions is not a list: '+_short(open_positions)}]
        merged,sides,rejected,conflicts={},{},[],set()
        for idx,pos in enumerate(open_positions):
            reason=None
            sym=side=qty=None
            try:
                if not isinstance(pos,dict): reason='Row is not a dict: '+_short(pos)
                else:
                    sym,side,qty=pos.get('symbol'),pos.get('side'),pos.get('quantity')
                    if not isinstance(sym,str) or not sym.strip(): reason='Invalid symbol'
                    elif not isinstance(side,str) or side.strip().upper() not in ('BUY','SELL'): reason='Invalid side'
                    elif isinstance(qty,bool) or not isinstance(qty,(int,float)) or not math.isfinite(qty) or qty<=0:
                        reason='Invalid quantity'
            except Exception:  # one hostile row must not affect the others
                reason='Unprocessable row'
            if reason:
                rejected.append({'index':idx,'symbol':_short(sym) if isinstance(sym,str) else None,'reason':reason})
                continue
            sym,side=sym.strip(),side.strip().upper()
            if sides.setdefault(sym,side)!=side: conflicts.add(sym)
            merged[(sym,side)]=merged.get((sym,side),0)+qty
        overflow={sym for (sym,_),qty in merged.items() if sym not in conflicts and not math.isfinite(qty)}
        for sym in sorted(overflow):  # finite rows can still sum to inf
            rejected.append({'index':None,'symbol':sym,'reason':'Merged quantity is not finite'})
        conflicts|=overflow
        for sym in sorted(conflicts-overflow):
            rejected.append({'index':None,'symbol':sym,'reason':'Conflicting sides; net exit ambiguous'})
        exits=[{'symbol':sym,'side':'SELL' if side=='BUY' else 'BUY','quantity':qty,
                'intentOnly':True,'submitted':False}
               for (sym,side),qty in merged.items() if sym not in conflicts]
        return exits,rejected
