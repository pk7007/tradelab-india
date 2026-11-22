import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from paper import PaperEngine
from strategy_lab import StrategyLab, encoded, metrics
from test_intraday_paper import CONFIG, bars


def historical_sessions(count=60):
    rows = []
    day = dt.date(2025, 1, 2)
    while count:
        if day.weekday() < 5:
            session = bars(75)
            for row in session:
                row['date'] = day.isoformat() + row['date'][10:]
            rows.extend(session)
            count -= 1
        day += dt.timedelta(days=1)
    return rows


class StrategyLabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paper = PaperEngine(Path(self.temp.name) / 'paper.sqlite')
        self.account = self.paper.create(CONFIG)['id']
        self.lab = StrategyLab(Path(self.temp.name) / 'lab.sqlite', self.paper)
        self.request = dict(hypothesis='Earlier exit may reduce modeled loss', accountId=self.account,
                            baselineConfig=CONFIG, criteria=dict(maxDrawdownPct=10),
                            provenance=dict(datasetId='fixture', datasetVersion='1', source='generated fixture',
                                            corporateActions='synthetic none', universe='DEMO', benchmark='frozen SMA baseline'))
        self.hypothesis = self.lab.register(self.request)['id']

    def test_connected_paper_engine_does_not_claim_automatic_promotion_readiness(self):
        status = self.lab.status()
        self.assertTrue(status['paperEngineConnected'])
        self.assertFalse(status['automaticPromotionReady'])
        self.assertIn('quote paper observations', status['promotionBlocker'])
        disconnected = StrategyLab(Path(self.temp.name) / 'disconnected.sqlite').status()
        self.assertFalse(disconnected['paperEngineConnected'])
        self.assertFalse(disconnected['automaticPromotionReady'])

    def test_registration_is_persistent_and_immutable(self):
        before = self.lab.status()['hypotheses'][0]
        self.assertEqual(before, StrategyLab(self.lab.path).status()['hypotheses'][0])
        self.assertEqual(before['policyDetails']['maxCandidates'], 5)

    def test_risk_and_capital_are_not_tunable(self):
        for changes in (dict(maxLoss=100), dict(capital=10000), dict(participationPct=100), {}):
            with self.assertRaises(ValueError):
                self.lab.add_candidate(self.hypothesis, changes)

    def test_candidate_search_budget_is_enforced(self):
        for multiple in range(1, 6):
            self.lab.add_candidate(self.hypothesis, dict(targetMultiple=multiple))
        with self.assertRaises(ValueError):
            self.lab.add_candidate(self.hypothesis, dict(targetMultiple=6))

    def test_insufficient_history_never_opens_holdout(self):
        candidate = self.lab.add_candidate(self.hypothesis, dict(targetMultiple=3))['id']
        with self.assertRaises(ValueError):
            self.lab.evaluate(self.hypothesis, candidate, bars(), True)
        self.assertEqual(self.lab.status()['evaluations'], [])

    def test_complete_replay_rejects_identical_baseline_and_seals_partition(self):
        candidate = self.lab.add_candidate(self.hypothesis, dict(targetMultiple=2))['id']
        rows = historical_sessions()
        result = self.lab.evaluate(self.hypothesis, candidate, rows, True)
        self.assertEqual(result['state'], 'rejected')
        self.assertFalse(result['gates']['baselineImprovement'])
        self.assertFalse(result['promotionAllowed'])
        self.assertEqual(set(result['scenarios']), {'gap', 'low-liquidity', 'rejected', 'latency-cost'})
        self.assertTrue(result['candidate']['ledgerMatches'])
        with self.assertRaisesRegex(ValueError, 'already opened'):
            self.lab.evaluate(self.hypothesis, candidate, rows, True)
        with self.assertRaises(ValueError):
            self.lab.promote(self.hypothesis, candidate)
        with self.assertRaisesRegex(ValueError, 'frozen'):
            self.lab.add_candidate(self.hypothesis, dict(targetMultiple=4))

    def test_partial_fills_are_combined_into_costed_roundtrip(self):
        report = dict(fills=[dict(side='BUY', quantity=2, price=100, fee=1),
                             dict(side='SELL', quantity=1, price=105, fee=.5),
                             dict(side='SELL', quantity=1, price=110, fee=.5)],
                      returnPct=1, maxDrawdownPct=0, fees=2, openQuantity=0, pending=None, ledgerMatches=True)
        result = metrics(report)
        self.assertEqual(result['completedTrades'], 1)
        self.assertEqual(result['netExpectancy'], 13)
        self.assertIsNone(result['bootstrapLower95'])

    def test_rollback_preserves_account_and_records_history(self):
        # Seed a previously committed promotion to exercise rollback transaction.
        with self.paper.db() as db:
            account = self.paper.load(db, self.account)
            previous = dict(account['config'])
            account['config']['strategyRevision'] = 'fixture-revision'
            promoted = dict(account['config'])
            self.paper.save(db, account, dict(type='strategy-promoted', previousConfig=previous, config=promoted))
        with self.lab.db() as db:
            db.execute('INSERT INTO paper_promotions VALUES(?,?,?,?,?,?,?,0)',
                       ('fixture', '2025-01-02', self.account, self.hypothesis, 'fixture-revision', encoded(previous), encoded(promoted)))
        result = self.lab.rollback(self.account, 'Fixture restoration')
        self.assertEqual(result['state'], 'rolled-back')
        with self.paper.db() as db:
            self.assertEqual(self.paper.load(db, self.account)['config'], previous)
        self.assertTrue(self.paper.reconcile(self.account)['matches'])
        with self.assertRaises(ValueError):
            self.lab.rollback(self.account, 'Duplicate rollback')

    def test_active_ingestion_blocks_version_changes(self):
        self.paper.control(self.account, 'start')
        with self.lab.db() as db:
            self.lab.attach_paper(db)
            with self.assertRaisesRegex(ValueError, 'Pause ingestion'):
                self.lab.check_flat(db, self.paper.load(db, self.account))

    def test_version_chain_rejects_changed_risk_limits(self):
        with self.paper.db() as db:
            account = self.paper.load(db, self.account)
            previous = dict(account['config'])
            account['config']['maxLoss'] = 100
            self.paper.save(db, account, dict(type='strategy-promoted', previousConfig=previous, config=account['config']))
        self.assertFalse(self.paper.reconcile(self.account)['matches'])

    def test_version_chain_rejects_missing_previous_config(self):
        with self.paper.db() as db:
            account = self.paper.load(db, self.account)
            account['config']['targetMultiple'] = 3
            self.paper.save(db, account, dict(type='strategy-promoted', config=account['config']))
        self.assertFalse(self.paper.reconcile(self.account)['matches'])
