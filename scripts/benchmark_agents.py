"""Offline per-role timings; synthetic evidence, no broker or news requests."""
import argparse
import datetime as dt
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent_catalog import DOMAINS, RESPONSIBILITIES
from agent_handlers import NUMERIC_FIELDS, execute
from agent_service import AgentService


def sample(domain, index=0):
    row = {key: 10 if key in NUMERIC_FIELDS else 'fixture' for key in DOMAINS[domain]}
    row.update(id='fixture-' + str(index), source='fixture:agent-speed-v1',
               observedAt='2026-01-02T10:00:00+05:30',
               availableAt='2026-01-02T10:00:00+05:30')
    if domain == 'exchange-calendar':
        row.update(open='2026-01-02T09:15:00+05:30', close='2026-01-02T15:30:00+05:30')
    if domain == 'recovery-persistence':
        row['restoreVerified'] = True
    if domain == 'paper-execution':
        row['side'] = 'BUY'
    return row


def summary(values):
    ordered = sorted(values)
    return dict(medianMs=round(statistics.median(values), 4),
                p95Ms=round(ordered[math.ceil(len(ordered)*.95)-1], 4),
                maximumMs=round(max(values), 4))


def benchmark(repeats=25, records=1):
    if not 1 <= repeats <= 100 or not 1 <= records <= 1000:
        raise ValueError('Use 1-100 repetitions and 1-1000 synthetic records.')
    roles, all_times, families = [], [], {}
    for domain in DOMAINS:
        rows = [sample(domain, index) for index in range(records)]
        payload = dict(permitted=True, records=rows, maxAgeSeconds=3600, baseline=rows)
        envelope = dict(input=payload, evidenceCutoff='2026-01-02T12:00:00+05:30')
        subject = execute(domain+'.analysis', envelope)
        payload['subject'] = dict(capability=domain+'.analysis', output=subject)
        for responsibility in RESPONSIBILITIES:
            capability = domain+'.'+responsibility
            execute(capability, envelope)
            timings = []
            for _ in range(repeats):
                start = time.perf_counter_ns()
                output = execute(capability, envelope)
                timings.append((time.perf_counter_ns()-start)/1_000_000)
                if output['executionAllowed'] is not False:
                    raise ValueError('A benchmark role acquired execution authority.')
            roles.append(dict(role=capability, **summary(timings)))
            all_times.extend(timings)
            families.setdefault(domain, []).extend(timings)
    queue = []
    with tempfile.TemporaryDirectory(prefix='tradelab-agent-speed-') as folder:
        service = AgentService(Path(folder)/'agents.sqlite')
        try:
            for index in range(3):
                start = time.perf_counter_ns()
                identity = service.enqueue(dict(capability='news-ingestion.analysis',
                    input=dict(permitted=True, records=[sample('news-ingestion')]),
                    evidenceCutoff='2026-01-02T12:00:00+05:30', priority=1,
                    deadlineSeconds=60, budgetSeconds=10, idempotencyKey='speed-'+str(index)))
                if service.run_once() != identity:
                    raise ValueError('Queue benchmark did not run its task.')
                task = next(row for row in service.status()['tasks'] if row['id'] == identity)
                if task['state'] != 'review':
                    raise ValueError('Queue benchmark did not produce a reviewable result.')
                queue.append((time.perf_counter_ns()-start)/1_000_000)
        finally:
            service.stop()
    return dict(version='agent-speed-v1', measuredAt=dt.datetime.now(dt.timezone.utc).isoformat(),
        python=platform.python_version(), platform=platform.system(), roleCount=len(roles),
        repetitionsPerRole=repeats, syntheticRecordsPerCall=records,
        localHandler=summary(all_times), subprocessQueue=summary(queue),
        queueSamples=len(queue), families={key: summary(values) for key, values in families.items()},
        roles=roles, executionAllowed=False,
        limitations=['Synthetic local CPU timings; not live trading or profitability evidence.',
            'Local handler measurements exclude network, queue wait, process startup and SQLite.',
            'Queue timings include enqueue, one subprocess and result persistence, not review acceptance.',
            '512 registered roles are not 512 continuously running AI models.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'docs/agent-speed-2026-11-22.json')
    parser.add_argument('--repeats', type=int, default=25)
    parser.add_argument('--records', type=int, default=1)
    args = parser.parse_args()
    result = benchmark(args.repeats, args.records)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key not in ('roles', 'families')}, indent=2))


if __name__ == '__main__':
    main()
