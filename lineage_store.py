"""Durable task lineage: source, observed and available times, input version, revision.

Records are append-only. A repair adds a new revision and marks the old one
superseded, so history is retained. Nothing here can place orders or change
limits; it only stores and reads evidence about upstream tasks.
"""
import json

from research import timestamp

DEFECT = 'Required handoff review failed.'
QUARANTINE_FAILURES = 3
QUARANTINE_WINDOW = 10
PROBATION_PASSES = 3
MAX_DEPTH = 64


class LineageGap(ValueError):
    """An upstream task is missing, cyclic or too deep to verify."""


def ensure_schema(db):
    """Create tables with plain execute(); executescript() would commit the caller's open transaction."""
    db.execute('''CREATE TABLE IF NOT EXISTS lineage_tasks(
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL, revision INTEGER NOT NULL, account TEXT, session TEXT,
            domain TEXT NOT NULL, source TEXT, source_version TEXT, observed_at TEXT, available_at TEXT NOT NULL,
            input_hash TEXT NOT NULL, output_hash TEXT, parents TEXT NOT NULL, state TEXT NOT NULL,
            reason TEXT, recorded_at TEXT NOT NULL, repair_reason TEXT, prior_state TEXT,
            UNIQUE(task_id, revision))''')
    db.execute('CREATE INDEX IF NOT EXISTS lineage_domain ON lineage_tasks(domain, account, seq)')


def _row(row):
    out = dict(row)
    out['parents'] = json.loads(out['parents'])
    return out


def _state(task):
    if task.get('state') == 'blocked' and task.get('reason') == DEFECT:
        return 'failed'
    if task.get('state') not in ('reviewed', 'blocked'):
        raise ValueError('Unknown task state.')
    return task['state']


def _values(task, now):
    for key in ('taskId', 'domain', 'inputHash', 'availableAt'):
        if not isinstance(task.get(key), str) or not task[key]:
            raise ValueError('Lineage task requires ' + key + '.')
    timestamp(task['availableAt'])
    if task.get('observedAt') is not None:
        timestamp(task['observedAt'])
    parents = task.get('parents', [])
    if not isinstance(parents, list) or not all(isinstance(p, str) for p in parents):
        raise ValueError('Lineage parents must be task IDs.')
    return (task['taskId'], task['domain'], task.get('accountId'), task.get('session'), task.get('source'),
            task.get('sourceVersion'), task.get('observedAt'), task['availableAt'], task['inputHash'], task.get('outputHash'),
            json.dumps(parents), _state(task), task.get('reason'), now)


def record(db, task, *, now):
    """Insert revision 1. Same content is a no-op; a changed outcome becomes a repair revision.

    The task ID is deterministic from the evidence, so a retry of the same input can legitimately
    end differently (for example after a transient handler failure). Changed inputs or parents are
    refused: a task's identity never silently changes.
    """
    values = _values(task, now)
    current = latest(db, task['taskId'])
    if current is None:
        db.execute('''INSERT INTO lineage_tasks(task_id,domain,account,session,source,source_version,observed_at,available_at,
                      input_hash,output_hash,parents,state,reason,recorded_at,revision) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)''', values)
        return 1
    if current['input_hash'] != task['inputHash'] or current['parents'] != task.get('parents', []):
        raise ValueError('Lineage revisions are immutable; use repair().')
    if current['state'] == _state(task) and current['output_hash'] == task.get('outputHash'):
        return current['revision']
    return repair(db, task, reason='re-recorded with a changed outcome', now=now)


def repair(db, task, *, reason, now):
    """Add a new revision of an existing task and supersede the previous one."""
    current = latest(db, task.get('taskId'))
    if current is None:
        raise ValueError('Nothing to repair.')
    values = _values(task, now)
    revision = current['revision'] + 1
    db.execute("UPDATE lineage_tasks SET prior_state=state, state='superseded' WHERE task_id=? AND revision=?",
               (task['taskId'], current['revision']))
    db.execute('''INSERT INTO lineage_tasks(task_id,domain,account,session,source,source_version,observed_at,available_at,
                  input_hash,output_hash,parents,state,reason,recorded_at,revision,repair_reason)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
               values + (revision, str(reason)[:200]))
    return revision


def latest(db, task_id):
    if not isinstance(task_id, str):
        return None
    row = db.execute('SELECT * FROM lineage_tasks WHERE task_id=? ORDER BY revision DESC LIMIT 1', (task_id,)).fetchone()
    return _row(row) if row else None


def record_handoffs(db, handoffs, *, now):
    for task in handoffs['tasks']:
        record(db, task, now=now)


def chain(db, final_task_id):
    """Upstream tasks (latest revisions), oldest first. Raises LineageGap if unverifiable."""
    ordered, seen = [], set()

    def visit(task_id, depth):
        if depth > MAX_DEPTH:
            raise LineageGap('Lineage is too deep to verify.')
        if task_id in seen:
            raise LineageGap('Lineage contains a cycle.')
        row = latest(db, task_id)
        if row is None:
            raise LineageGap('Lineage gap: upstream task is missing.')
        seen.add(task_id)
        for parent in row['parents']:
            visit(parent, depth + 1)
        seen.discard(task_id)
        ordered.append(row)

    visit(final_task_id, 0)
    return ordered


def quarantined(db, domain, *, account=None, failures=QUARANTINE_FAILURES, window=QUARANTINE_WINDOW,
                passes=PROBATION_PASSES):
    """Repeated review defects quarantine a domain for that account until a clean probation.

    A failure later repaired by a retry still counts as a defect (a flaky domain accumulates), and its
    repaired revision counts as one clean pass. Rows blocked because an upstream task did not pass say
    nothing about this domain and are ignored.
    """
    outcome = "CASE WHEN state='superseded' THEN prior_state ELSE state END"
    states = [r[0] for r in db.execute(
        "SELECT %s AS outcome FROM lineage_tasks WHERE domain=? AND account IS ? AND (%s) IN ('failed','reviewed') "
        "ORDER BY seq DESC LIMIT ?" % (outcome, outcome), (domain, account, window))]
    if sum(s == 'failed' for s in states) < failures:
        return False
    clean = 0
    for state in states:
        if state != 'reviewed':
            break
        clean += 1
    return clean < passes
