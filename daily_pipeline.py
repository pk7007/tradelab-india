"""Daily selection pipeline: validate inputs, classify each scan, and record it with lineage.

Every scan becomes a chain of lineage tasks (universe -> quotes -> candles -> selection) and one log
row, so a selection or abstention can be traced to the inputs it used and when they were available.
Bad data BLOCKS selection for that scan; a clean scan with no qualifying stock is an ABSTENTION (a
normal, logged outcome). This module only decides whether the existing selector may allocate a
new paper account; it never touches exits, square-off, reconciliation, limits or any broker call.

The thresholds below are conservative floors, not calibrated against live data.
"""
import hashlib
import json

from research import timestamp

VERSION = 'daily-pipeline-v1'
SOURCE = 'local:auto-selector'
ACCOUNT = 'auto-selection'
MIN_FRESH_QUOTE_FRACTION = 0.2    # a fraction of the universe...
MAX_REQUIRED_FRESH_QUOTES = 25    # ...capped, so a ~2000-name universe with a thin stale tail is not misread as dead
MAX_BAD_CANDLE_FRACTION = 0.5     # more than this many bad series blocks selection
QUOTE_DATA_FAULTS = ('Quote timestamp is stale or future.', 'Quote missing or malformed.')
# Reasons rank_candidates() raises. auto_selector imports these constants so the text cannot drift, and a
# test fails if rank_candidates raises a reason that is not classified here.
REASON_SIGNAL = 'Shared SMA condition is false.'
REASON_LIQUIDITY = 'No modeled liquidity.'
REASON_NO_SHARE = 'Costs, cash or volume exclude a whole share.'
LEGITIMATE_CANDLE_EXCLUSIONS = (REASON_SIGNAL, REASON_LIQUIDITY, REASON_NO_SHARE)
CANDLE_DATA_FAULTS = ('Twenty completed session candles required.', 'Session opening history missing.',
                      'Candle gap.', 'Latest completed candle is stale.')
UPSTREAM = 'Required input or upstream decision did not pass.'


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, allow_nan=False,
                                     separators=(',', ':')).encode()).hexdigest()


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS daily_selection_log(
        seq INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, decision TEXT NOT NULL, selected TEXT,
        reasons TEXT NOT NULL, final_task_id TEXT, inputs TEXT NOT NULL, optional TEXT NOT NULL,
        recorded_at TEXT NOT NULL)''')


def assess_scan(*, day, now, symbols, quote_excluded, quote_observed_at, candles, ranked, excluded,
                candle_observed_at, optional_events=None):
    """Classify one scan. Returns decision ('selected'|'abstain'|'blocked'), reasons and lineage tasks."""
    try:
        scanned = timestamp(now)
        quoted = timestamp(quote_observed_at) if quote_observed_at else scanned
        bar = timestamp(candle_observed_at) if candle_observed_at else scanned
    except (ValueError, TypeError, OverflowError):
        raise ValueError('Scan timestamps are invalid.') from None
    if not isinstance(symbols, (list, tuple)) or not all(isinstance(s, str) for s in symbols):
        raise ValueError('Symbols must be a list of names.')
    symbols = sorted(symbols)
    quote_faults = [e for e in quote_excluded if e.get('reason') in QUOTE_DATA_FAULTS]
    candle_faults = [e for e in excluded if e.get('reason') not in LEGITIMATE_CANDLE_EXCLUSIONS]
    fresh = len(symbols) - len(quote_faults)

    stages = []   # (domain, observed, input summary, failure reason or None)
    stages.append(('instrument-reference', scanned, dict(count=len(symbols), symbolsDigest=_digest(symbols)),
                   None if symbols else 'Instrument universe is empty.'))
    needed = max(1, min(MIN_FRESH_QUOTE_FRACTION * len(symbols), MAX_REQUIRED_FRESH_QUOTES))
    quote_problem = None
    if quoted > scanned:
        quote_problem = 'A quote observation is dated after the scan; the feed clock is wrong.'
    elif symbols and fresh < needed:
        quote_problem = 'Only %d of %d quotes were usable (need %d); the quote feed looks stale or broken.' % (
            fresh, len(symbols), needed)
    stages.append(('quote-observations', quoted, dict(symbols=len(symbols), faults=len(quote_faults), fresh=fresh),
                   quote_problem))
    candle_problem = None
    if bar > scanned:
        candle_problem = 'A candle observation is dated after the scan; the data clock is wrong.'
    elif candles and len(candle_faults) > MAX_BAD_CANDLE_FRACTION * len(candles):
        candle_problem = '%d of %d candle series failed data checks.' % (len(candle_faults), len(candles))
    stages.append(('historical-candles', bar, dict(series=len(candles), faults=len(candle_faults),
                   lastBars=_digest({s: (rows[-1].get('date') if rows else None) for s, rows in sorted(candles.items())})),
                   candle_problem))

    tasks, parent, reasons, failed = [], None, [], False
    for domain, observed, summary, problem in stages:
        failed = failed or problem is not None
        if problem:
            reasons.append(problem)
        tasks.append(_task(day, domain, observed, max(observed, scanned), summary, parent, 'blocked' if failed else 'reviewed',
                           problem or (UPSTREAM if failed else None)))
        parent = tasks[-1]['taskId']
    selected = None if failed or not ranked else ranked[0]['symbol']
    if failed:
        decision = 'blocked'
    elif selected:
        decision = 'selected'
    else:
        decision = 'abstain'
        reasons.append('No qualifying stock: %d candidates ranked, %d excluded.' % (len(ranked), len(excluded)))
    tasks.append(_task(day, 'selection', scanned, scanned, dict(decision=decision, selected=selected,
                       ranked=[r['symbol'] for r in ranked[:5]]), parent, 'blocked' if failed else 'reviewed',
                       UPSTREAM if failed else None))
    optional = []
    if optional_events is not None:
        optional.append(dict(domain='event-entity-mapping', status=str(optional_events.get('status')),
                             attached=int(optional_events.get('attached') or 0), availableAt=scanned.isoformat(),
                             note='Advisory only; it never gates selection.'))
    return dict(decision=decision, selected=selected, reasons=reasons, tasks=tasks, optional=optional,
                finalTaskId=tasks[-1]['taskId'], day=day, now=scanned.isoformat())


def _task(day, domain, observed, available, summary, parent, state, reason):
    input_hash = _digest(dict(domain=domain, day=day, summary=summary))
    task = dict(taskId=_digest(dict(input=input_hash, parent=parent, version=VERSION)), domain=domain,
                accountId=ACCOUNT, session=day, inputHash=input_hash, outputHash=_digest(dict(state=state)),
                availableAt=available.isoformat(), observedAt=observed.isoformat(), source=SOURCE,
                sourceVersion=VERSION, parents=[parent] if parent else [], state=state)
    if reason:
        task['reason'] = reason
    return task


def record_scan(db, scan):
    """Persist the lineage and one log row inside the caller's transaction."""
    import lineage_store
    for task in scan['tasks']:
        lineage_store.record(db, task, now=scan['now'])
    refs = [dict(domain=t['domain'], taskId=t['taskId'], state=t['state'], inputHash=t['inputHash'],
                 observedAt=t['observedAt'], availableAt=t['availableAt']) for t in scan['tasks']]
    db.execute('''INSERT INTO daily_selection_log(day,decision,selected,reasons,final_task_id,inputs,optional,recorded_at)
                  VALUES(?,?,?,?,?,?,?,?)''',
               (scan['day'], scan['decision'], scan['selected'], json.dumps(scan['reasons']), scan['finalTaskId'],
                json.dumps(refs), json.dumps(scan['optional']), scan['now']))
