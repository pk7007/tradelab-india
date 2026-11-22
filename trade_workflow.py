"""Registered, reviewed intraday entry handoffs; the paper engine owns execution."""
import math

from agent_handlers import digest, execute
from entry_review import evaluate
from strategy_contract import VERSION


def entry_handoffs(evidence, config, bar, cash, instrument, decision, handler=execute):
    baseline = evaluate(evidence)
    common = dict(source='local:paper-entry', observedAt=evidence['signalAt'],
                  availableAt=evidence['receivedAt'], symbol=evidence['symbol'])
    quantity = decision['maxQuantity']
    stages = [
        ('instrument-reference', dict(exchange=instrument.get('exchange'), instrumentToken=instrument.get('token')),
         baseline['reviewers'][0]['status'] == 'eligible'),
        ('historical-candles', {key: bar[key] for key in ('open', 'high', 'low', 'close', 'volume')},
         baseline['reviewers'][0]['status'] == 'eligible'),
        ('technical-indicators', dict(indicator=VERSION,
             value=math.fsum(evidence['closes'][-5:])/5-math.fsum(evidence['closes'][-20:])/20, period=20),
         baseline['reviewers'][1]['status'] == 'eligible'),
        ('position-sizing', dict(quantity=quantity, price=bar['close'], capital=cash),
         baseline['reviewers'][2]['status'] == 'eligible' and quantity > 0),
        ('trade-risk', dict(entry=bar['close'], stop=bar['close']*(1-config['stopDistancePct']/100),
             quantity=quantity, maxLoss=config['maxLoss']), decision['status'] == 'eligible'),
    ]
    tasks = []
    parent = None
    allowed = True
    for domain, values, gate in stages:
        record = dict(common, **values, id=domain)
        payload = dict(permitted=True, records=[record])
        fingerprint = digest(dict(input=payload, config=evidence['configHash'],
                                  account=evidence['accountId'], parent=parent,
                                  owner=evidence['workerOwner'], epoch=evidence['workerEpoch']))
        task = dict(taskId=fingerprint, inputHash=digest(payload), accountId=evidence['accountId'],
                    session=evidence['session'], domain=domain, sourceVersion=VERSION,
                    availableAt=common['availableAt'], parents=[parent] if parent else [],
                    capability=domain+'.analysis', reviewer=domain+'.independent-review',
                    state='blocked', executionAllowed=False)
        if allowed and gate:
            try:
                output = handler(task['capability'], dict(input=payload, evidenceCutoff=evidence['reviewedAt']))
                reviewed = handler(task['reviewer'], dict(
                    input=dict(payload, subject=dict(capability=task['capability'], output=output)),
                    evidenceCutoff=evidence['reviewedAt']))
                if reviewed.get('matches') is not True:
                    raise ValueError('Handoff review mismatch.')
                task.update(state='reviewed', outputHash=digest(output), verdictHash=digest(reviewed))
            except Exception:
                task['reason'] = 'Required handoff review failed.'
        else:
            task['reason'] = 'Required input or upstream decision did not pass.'
        allowed = task['state'] == 'reviewed'
        tasks.append(task)
        parent = fingerprint
    return dict(version='intraday-handoffs-v1', state='reviewed' if allowed else 'blocked',
                tasks=tasks, finalTaskId=parent, inputHash=digest(evidence),
                reviewScope='Registered evidence re-computation plus mandatory deterministic entry controls.')
