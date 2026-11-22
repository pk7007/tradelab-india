"""Bounded deterministic evidence review for one managed paper BUY."""
import copy
import datetime as dt
import hashlib
import json
import queue
import threading

from research import timestamp
from strategy_contract import target_long

VERSION = 'paper-entry-review-v1'
IDENTITIES = ('service:paper-selection-v1', 'service:paper-research-v1', 'service:paper-risk-v1')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False,separators=(',', ':')).encode()).hexdigest()


def evaluate(evidence):
    """Price-only strategy, with mandatory mapping, availability and risk evidence."""
    now=timestamp(evidence['reviewedAt'])
    complete=timestamp(evidence['signalAt'])+dt.timedelta(minutes=5)
    received=timestamp(evidence['receivedAt'])
    selection=(evidence['selectionValid'] and evidence['authorized'] and evidence['ownerValid']
               and complete<=received<=now and 0<=(now-complete).total_seconds()<=90
               and evidence.get('postReviewValid',True))
    research=target_long(evidence['closes']) and evidence.get('requiredNewsAvailable',True)
    risk=evidence['maxQuantity']>0 and not evidence['entriesPaused'] and not evidence['riskHalted']
    checks=[dict(identity=IDENTITIES[0],status='eligible' if selection else 'temporarily-blocked',
                 reason='Mapped selected instrument and fresh completed inputs.' if selection else 'Selection, freshness, authorization or ownership evidence unavailable.'),
            dict(identity=IDENTITIES[1],status='eligible' if research else 'skip',
                 reason='Frozen completed-close SMA condition holds; news is advisory.' if research else 'Required strategy evidence does not support entry.'),
            dict(identity=IDENTITIES[2],status='eligible' if risk else 'skip',
                 reason='Whole shares fit modeled cash, costs, exposure, liquidity and remaining risk.' if risk else 'No permitted whole-share entry fits current risk controls.')]
    failed=next((row for row in checks if row['status']!='eligible'),None)
    return dict(status=failed['status'] if failed else 'eligible',reason=failed['reason'] if failed else 'All automatic paper entry checks passed.',
                maxQuantity=evidence['maxQuantity'] if not failed else 0,reviewers=checks)


class EntryReviewer:
    """A custom reviewer gets one daemon slot and a bounded response deadline."""
    def __init__(self, handler=None, timeout=.1):
        self.handler=handler
        self.timeout=timeout
        self.thread=None

    def review(self, evidence):
        if self.handler is None:
            return evaluate(evidence)
        if self.thread and self.thread.is_alive():
            raise TimeoutError('Entry reviewer is still busy.')
        replies=queue.Queue(maxsize=1)
        def run():
            try:
                replies.put((True,self.handler(copy.deepcopy(evidence))))
            except Exception:
                replies.put((False,None))
        self.thread=threading.Thread(target=run,name='paper-entry-review',daemon=True)
        self.thread.start()
        try:
            okay,result=replies.get(timeout=self.timeout)
        except queue.Empty:
            raise TimeoutError('Entry reviewer deadline exceeded.') from None
        if not okay:
            raise ValueError('Entry reviewer failed.')
        return result
