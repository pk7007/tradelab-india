import sqlite3
import unittest

import entry_gate
import lineage_store as store
from test_lineage_store import task, T, LATER

DOMAINS = entry_gate.REQUIRED_DOMAINS


def chain(db, **overrides):
    parent = None
    for domain in DOMAINS:
        spec = overrides.get(domain, {})
        store.record(db, task(domain, parent, **spec), now=LATER)
        parent = domain + '-id'
    return parent


class EntryGateTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        store.ensure_schema(self.db)

    def check(self, final, at=LATER):
        return entry_gate.check_entry(self.db, final, at)

    def test_complete_reviewed_chain_is_allowed_and_reports_lineage(self):
        result = self.check(chain(self.db))
        self.assertTrue(result['allowed'], result)
        self.assertEqual(result['lineage'], [d + '-id' for d in DOMAINS])

    def test_failed_upstream_review_blocks_new_entry_and_names_domain(self):
        final = chain(self.db, **{'technical-indicators': dict(state='blocked', reason='Required handoff review failed.')})
        result = self.check(final)
        self.assertFalse(result['allowed'])
        self.assertTrue(any('technical-indicators' in r for r in result['reasons']))

    def test_evidence_available_after_decision_time_blocks(self):
        final = chain(self.db, **{'historical-candles': dict(available='2026-01-02T10:05:00+05:30')})
        result = self.check(final)
        self.assertFalse(result['allowed'])
        self.assertTrue(any('after the decision' in r for r in result['reasons']))

    def test_observed_after_available_blocks(self):
        final = chain(self.db, **{'instrument-reference': dict(observed='2026-01-02T10:00:10+05:30', available=T)})
        self.assertFalse(self.check(final)['allowed'])

    def test_missing_required_domain_blocks(self):
        store.record(self.db, task('instrument-reference'), now=LATER)
        store.record(self.db, task('trade-risk', 'instrument-reference-id'), now=LATER)
        result = self.check('trade-risk-id')
        self.assertFalse(result['allowed'])
        self.assertTrue(any('position-sizing' in r and 'missing' in r for r in result['reasons']))

    def test_optional_research_missing_never_blocks_but_gap_in_chain_does(self):
        self.assertTrue(self.check(chain(self.db))['allowed'])  # no news/fundamental task exists at all
        store.record(self.db, task('trade-risk', 'ghost-id', task_id='orphan'), now=LATER)
        result = self.check('orphan')
        self.assertFalse(result['allowed'])
        self.assertTrue(any('lineage' in r.lower() for r in result['reasons']))

    def test_unknown_final_task_blocks(self):
        self.assertFalse(self.check('nope')['allowed'])
        self.assertFalse(self.check(None)['allowed'])

    def test_quarantined_domain_blocks_even_when_current_task_reviewed(self):
        for n in range(3):
            store.record(self.db, task('position-sizing', state='blocked', task_id='old%d' % n,
                                       reason='Required handoff review failed.'), now=LATER)
        result = self.check(chain(self.db))
        self.assertFalse(result['allowed'])
        self.assertTrue(any('quarantined' in r for r in result['reasons']))

    def test_superseded_failure_is_replaced_by_repaired_revision(self):
        failing = dict(state='blocked', reason='Required handoff review failed.')
        final = chain(self.db, **{'position-sizing': failing})
        self.assertFalse(self.check(final)['allowed'])
        store.repair(self.db, task('position-sizing', 'technical-indicators-id'), reason='repaired', now=LATER)
        self.assertTrue(self.check(final)['allowed'])

    def test_transient_failure_retried_successfully_allows_entry_again(self):
        failing = dict(state='blocked', reason='Required handoff review failed.')
        final = chain(self.db, **{'trade-risk': failing})
        self.assertFalse(self.check(final)['allowed'])
        final = chain(self.db)  # same inputs, review now passes
        self.assertTrue(self.check(final)['allowed'])

    def test_quarantine_of_one_account_does_not_block_another(self):
        for n in range(3):
            store.record(self.db, dict(task('position-sizing', state='blocked', task_id='old%d' % n,
                reason='Required handoff review failed.'), accountId='other'), now=LATER)
        self.assertTrue(self.check(chain(self.db))['allowed'])

    def test_gate_has_no_exit_api(self):
        self.assertFalse(hasattr(entry_gate, 'check_exit'))
        self.assertIn('never', entry_gate.__doc__.lower())
        self.assertIn('exit', entry_gate.__doc__.lower())


if __name__ == '__main__':
    unittest.main()
