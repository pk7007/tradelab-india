import tempfile
import unittest
import uuid
from pathlib import Path

from api_rate_limits import AtomicRateLimiter, validated_policy

POLICY = dict(perSecond=3, perMinute=10, perDay=20, modificationsPerOrder=2,
              reserveSecond=1, reserveMinute=2, reserveDay=3)
T0 = 1_800_000_000.0  # fixed instant


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def rid():
    return str(uuid.uuid4())


class RateLimiterTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.clock = Clock()
        self.limiter = self.make(POLICY)

    def make(self, policy):
        return AtomicRateLimiter(Path(self.dir.name) / 'rate.sqlite', policy, clock=self.clock)

    def test_policy_validation(self):
        for bad in (None, {}, dict(POLICY, extra=1), dict(POLICY, perSecond=True),
                    dict(POLICY, perSecond=11), dict(POLICY, perMinute=0),
                    dict(POLICY, reserveSecond=3), dict(POLICY, perDay=5001)):
            with self.assertRaises(ValueError, msg=str(bad)):
                validated_policy(bad)
        self.assertEqual(validated_policy(POLICY), POLICY)

    def test_admits_until_non_emergency_budget_then_denies_with_wait(self):
        for _ in range(2):  # perSecond 3 minus reserve 1
            self.assertTrue(self.limiter.admit('acct', rid(), 'place')['allowed'])
        denied = self.limiter.admit('acct', rid(), 'place')
        self.assertFalse(denied['allowed'])
        self.assertEqual(denied['reason'], 'rate-budget-exhausted')
        self.assertGreater(denied['waitSeconds'], 0)
        self.assertFalse(denied['executionAllowed'])
        self.assertFalse(denied['complianceApproved'])

    def test_emergency_uses_reserve_but_not_beyond_hard_limit(self):
        for _ in range(2):
            self.limiter.admit('acct', rid(), 'place')
        self.assertTrue(self.limiter.admit('acct', rid(), 'cancel', emergency=True, order_id='o1')['allowed'])
        self.assertFalse(self.limiter.admit('acct', rid(), 'cancel', emergency=True, order_id='o1')['allowed'])

    def test_capacity_returns_after_window(self):
        for _ in range(2):
            self.limiter.admit('acct', rid(), 'place')
        self.clock.now += 2
        self.assertTrue(self.limiter.admit('acct', rid(), 'place')['allowed'])

    def test_duplicate_request_id_is_denied_and_not_double_counted(self):
        same = rid()
        self.assertTrue(self.limiter.admit('acct', same, 'place')['allowed'])
        again = self.limiter.admit('acct', same, 'place')
        self.assertEqual(again['reason'], 'duplicate-request-id')

    def test_modification_limit_per_order(self):
        for _ in range(2):
            self.assertTrue(self.limiter.admit('acct', rid(), 'modify', order_id='o1')['allowed'])
            self.clock.now += 2
        blocked = self.limiter.admit('acct', rid(), 'modify', order_id='o1')
        self.assertEqual(blocked['reason'], 'order-modification-limit')
        self.assertIsNone(blocked['waitSeconds'])
        self.assertTrue(self.limiter.admit('acct', rid(), 'modify', order_id='o2')['allowed'])

    def test_invalid_inputs_are_denied(self):
        cases = [(dict(account='bad acct!', request_id=rid(), kind='place'), 'missing-or-invalid-account'),
                 (dict(account='acct', request_id='nope', kind='place'), 'invalid-request-id'),
                 (dict(account='acct', request_id=rid(), kind='sell'), 'invalid-operation'),
                 (dict(account='acct', request_id=rid(), kind='place', emergency=1), 'invalid-operation'),
                 (dict(account='acct', request_id=rid(), kind='cancel'), 'missing-or-invalid-order-id'),
                 (dict(account='acct', request_id=rid(), kind='place', order_id='bad id'), 'invalid-order-id')]
        for kwargs, reason in cases:
            self.assertEqual(self.limiter.admit(**kwargs)['reason'], reason, kwargs)

    def test_clock_rollback_and_bad_clock_are_denied(self):
        self.assertTrue(self.limiter.admit('acct', rid(), 'place')['allowed'])
        self.clock.now -= 5
        self.assertEqual(self.limiter.admit('acct', rid(), 'place')['reason'], 'clock-rollback')
        for bad in (float('nan'), -1, True, 'x'):
            self.clock.now = bad
            self.assertEqual(self.limiter.admit('acct', rid(), 'place')['reason'], 'invalid-clock')

    def test_policy_change_for_existing_account_is_refused(self):
        self.limiter.admit('acct', rid(), 'place')
        looser = self.make(dict(POLICY, perSecond=5))
        self.assertEqual(looser.admit('acct', rid(), 'place')['reason'], 'account-policy-mismatch')

    def test_accounts_are_budgeted_separately(self):
        for _ in range(2):
            self.limiter.admit('a', rid(), 'place')
        self.assertTrue(self.limiter.admit('b', rid(), 'place')['allowed'])

    def test_daily_budget(self):
        total = 0
        for _ in range(40):
            self.clock.now += 7  # stay under per-second and per-minute budgets
            if self.limiter.admit('acct', rid(), 'place')['allowed']:
                total += 1
        self.assertEqual(total, 17)  # perDay 20 minus reserve 3

    def test_note_outcome_validates(self):
        permit = self.limiter.admit('acct', rid(), 'place')
        self.limiter.note_outcome('acct', permit['requestId'], 'ACK')
        with self.assertRaises(ValueError):
            self.limiter.note_outcome('acct', permit['requestId'], 'MAYBE')
        with self.assertRaises(ValueError):
            self.limiter.note_outcome('acct', rid(), 'ACK')
        with self.assertRaises(ValueError):
            self.limiter.note_outcome('acct', 'nope', 'ACK')

    def test_status_never_claims_compliance(self):
        status = self.limiter.policy_status()
        self.assertTrue(status['configured'])
        self.assertFalse(status['complianceApproved'])
        self.assertFalse(status['executionAllowed'])


if __name__ == '__main__':
    unittest.main()
