import sqlite3
import unittest

import lineage_store as store

T = '2026-01-02T10:00:00+05:30'
LATER = '2026-01-02T10:00:20+05:30'


def task(domain, parent=None, *, state='reviewed', task_id=None, available=T, observed=T, reason=None, input_hash='h'):
    out = dict(taskId=task_id or domain + '-id', domain=domain, accountId='acct', session='2026-01-02',
               inputHash=input_hash + domain, availableAt=available, observedAt=observed,
               source='local:paper-entry', sourceVersion='strategy-v1', parents=[parent] if parent else [], state=state,
               capability=domain + '.analysis', reviewer=domain + '.independent-review')
    if state == 'reviewed':
        out.update(outputHash='o' + domain, verdictHash='v' + domain)
    if reason:
        out['reason'] = reason
    return out


class LineageStoreTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        store.ensure_schema(self.db)

    def test_record_keeps_source_times_input_version_and_parents(self):
        store.record(self.db, task('a'), now=LATER)
        store.record(self.db, task('b', 'a-id'), now=LATER)
        row = store.latest(self.db, 'b-id')
        self.assertEqual((row['source'], row['observed_at'], row['available_at'], row['revision']),
                         ('local:paper-entry', T, T, 1))
        self.assertEqual(row['input_hash'], 'hb')
        self.assertEqual(row['source_version'], 'strategy-v1')
        self.assertEqual(row['parents'], ['a-id'])
        self.assertEqual(row['state'], 'reviewed')

    def test_record_is_idempotent_and_immutable_per_revision(self):
        store.record(self.db, task('a'), now=LATER)
        store.record(self.db, task('a'), now=LATER)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM lineage_tasks').fetchone()[0], 1)
        with self.assertRaises(ValueError):
            store.record(self.db, task('a', input_hash='changed'), now=LATER)

    def test_repair_creates_new_revision_and_keeps_history(self):
        store.record(self.db, task('a', state='blocked', reason='Required handoff review failed.'), now=LATER)
        store.repair(self.db, task('a', input_hash='fixed'), reason='re-reviewed', now=LATER)
        self.assertEqual(store.latest(self.db, 'a-id')['revision'], 2)
        self.assertEqual(store.latest(self.db, 'a-id')['state'], 'reviewed')
        rows = self.db.execute('SELECT revision,state FROM lineage_tasks WHERE task_id=? ORDER BY revision', ('a-id',)).fetchall()
        self.assertEqual([tuple(r) for r in rows], [(1, 'superseded'), (2, 'reviewed')])
        with self.assertRaises(ValueError):
            store.repair(self.db, task('zzz'), reason='nothing to repair', now=LATER)

    def test_review_failure_is_classified_as_defect_not_upstream_skip(self):
        store.record(self.db, task('a', state='blocked', reason='Required handoff review failed.'), now=LATER)
        store.record(self.db, task('b', 'a-id', state='blocked', reason='Required input or upstream decision did not pass.'), now=LATER)
        self.assertEqual(store.latest(self.db, 'a-id')['state'], 'failed')
        self.assertEqual(store.latest(self.db, 'b-id')['state'], 'blocked')

    def test_chain_returns_upstream_in_order_and_flags_gaps_and_cycles(self):
        store.record(self.db, task('a'), now=LATER)
        store.record(self.db, task('b', 'a-id'), now=LATER)
        store.record(self.db, task('c', 'b-id'), now=LATER)
        self.assertEqual([r['task_id'] for r in store.chain(self.db, 'c-id')], ['a-id', 'b-id', 'c-id'])
        store.record(self.db, task('d', 'missing-id'), now=LATER)
        with self.assertRaises(store.LineageGap):
            store.chain(self.db, 'd-id')
        store.record(self.db, task('x', 'y-id'), now=LATER)
        store.record(self.db, task('y', 'x-id'), now=LATER)
        with self.assertRaises(store.LineageGap):
            store.chain(self.db, 'x-id')

    def test_quarantine_after_repeated_defects_and_release_after_clean_probation_keeping_history(self):
        def add(n, state):
            store.record(self.db, task('trade-risk', state=state, task_id='t%d' % n,
                reason='Required handoff review failed.' if state == 'blocked' else None), now=LATER)
        for n in range(3):
            add(n, 'blocked')
        self.assertTrue(store.quarantined(self.db, 'trade-risk', account='acct'))
        add(3, 'reviewed'); add(4, 'reviewed')
        self.assertTrue(store.quarantined(self.db, 'trade-risk', account='acct'))
        add(5, 'reviewed')
        self.assertFalse(store.quarantined(self.db, 'trade-risk', account='acct'))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM lineage_tasks').fetchone()[0], 6)
        self.assertFalse(store.quarantined(self.db, 'position-sizing', account='acct'))

    def test_retry_with_changed_outcome_becomes_a_repair_revision(self):
        store.record(self.db, task('a', state='blocked', reason='Required handoff review failed.'), now=LATER)
        self.assertEqual(store.latest(self.db, 'a-id')['state'], 'failed')
        store.record(self.db, task('a'), now=LATER)  # same input, now reviewed
        row = store.latest(self.db, 'a-id')
        self.assertEqual((row['revision'], row['state']), (2, 'reviewed'))
        store.record(self.db, task('a'), now=LATER)  # identical again: no new revision
        self.assertEqual(store.latest(self.db, 'a-id')['revision'], 2)
        states = [r[0] for r in self.db.execute('SELECT state FROM lineage_tasks ORDER BY revision')]
        self.assertEqual(states, ['superseded', 'reviewed'])

    def test_schema_creation_does_not_end_the_callers_transaction(self):
        db = sqlite3.connect(':memory:', isolation_level=None)
        db.row_factory = sqlite3.Row
        store.ensure_schema(db)
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE side(x)')
        store.ensure_schema(db)  # must be a plain no-op inside the open transaction
        self.assertTrue(db.in_transaction)
        store.record(db, task('a'), now=LATER)
        db.execute('ROLLBACK')
        self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='side'").fetchone())
        self.assertEqual(db.execute('SELECT COUNT(*) FROM lineage_tasks').fetchone()[0], 0)

    def test_quarantine_is_per_account_and_ignores_upstream_skips(self):
        for n in range(3):
            store.record(self.db, task('trade-risk', state='blocked', task_id='o%d' % n,
                                       reason='Required handoff review failed.'), now=LATER)
        self.assertTrue(store.quarantined(self.db, 'trade-risk', account='acct'))
        self.assertFalse(store.quarantined(self.db, 'trade-risk', account='other'))
        for n in range(5):  # upstream skips are neither defects nor passes
            store.record(self.db, task('trade-risk', state='blocked', task_id='s%d' % n,
                                       reason='Required input or upstream decision did not pass.'), now=LATER)
        self.assertTrue(store.quarantined(self.db, 'trade-risk', account='acct'))

    def test_flaky_domain_that_fails_then_passes_on_retry_still_accumulates_toward_quarantine(self):
        for n in range(3):
            tid = 'flaky%d' % n
            store.record(self.db, task('trade-risk', state='blocked', task_id=tid,
                                       reason='Required handoff review failed.'), now=LATER)
            store.record(self.db, task('trade-risk', task_id=tid), now=LATER)  # retry passes -> repair revision
        self.assertTrue(store.quarantined(self.db, 'trade-risk', account='acct'))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM lineage_tasks WHERE prior_state='failed'").fetchone()[0], 3)

    def test_record_handoffs_persists_every_task_of_a_handoff(self):
        handoffs = dict(tasks=[task('a'), task('b', 'a-id')], finalTaskId='b-id')
        store.record_handoffs(self.db, handoffs, now=LATER)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM lineage_tasks').fetchone()[0], 2)
        with self.assertRaises(ValueError):
            store.record(self.db, dict(task('q'), availableAt='not-a-time'), now=LATER)


if __name__ == '__main__':
    unittest.main()
