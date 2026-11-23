"""Gate for NEW paper entries only, driven by the durable lineage store.

A failed, missing, late or quarantined required input blocks a new entry. This
module has no exit path on purpose: protective exits, square-off, exposure
reporting and ledger reconciliation never call it and are never gated by
research or review availability. Optional research that is absent is not an
input here and never blocks anything.
"""
import lineage_store as store
from research import timestamp

REQUIRED_DOMAINS = ('instrument-reference', 'historical-candles', 'technical-indicators',
                    'position-sizing', 'trade-risk')


def check_entry(db, final_task_id, decision_time, required=REQUIRED_DOMAINS):
    blocked = lambda *reasons: dict(allowed=False, reasons=list(reasons), lineage=[])
    try:
        decided = timestamp(decision_time)
        rows = store.chain(db, final_task_id)
    except store.LineageGap as error:
        return blocked(str(error))
    except (ValueError, TypeError, OverflowError):
        return blocked('Lineage unavailable or decision time invalid.')
    reasons = []
    latest = {}
    for row in rows:
        latest[row['domain']] = row
        if row['state'] != 'reviewed':
            reasons.append('%s did not pass review (%s).' % (row['domain'], row['state']))
        available = timestamp(row['available_at'])
        if available > decided:
            reasons.append('%s evidence became available after the decision time.' % row['domain'])
        if row['observed_at'] and timestamp(row['observed_at']) > available:
            reasons.append('%s was observed after it was available.' % row['domain'])
    account = rows[-1]['account'] if rows else None
    for domain in required:
        if domain not in latest:
            reasons.append('Required %s evidence is missing from the lineage.' % domain)
        elif store.quarantined(db, domain, account=account):
            reasons.append('%s is quarantined after repeated review defects.' % domain)
    return dict(allowed=not reasons, reasons=reasons, lineage=[row['task_id'] for row in rows])
