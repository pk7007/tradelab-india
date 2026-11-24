import datetime as dt
import json
import math
import unittest
from pathlib import Path

import live_readiness as lr

ROOT = Path(__file__).resolve().parents[1]


def trades(pattern, days=None):
    """pattern: list of net P&L; one trade per day unless days given."""
    start = dt.date(2026, 1, 1)
    return [dict(day=(start + dt.timedelta(days=days[i] if days else i)).isoformat(), net=value) for i, value in enumerate(pattern)]


class PerformanceTests(unittest.TestCase):
    def test_known_series_gives_known_metrics(self):
        perf = lr.performance(trades([10, -5, 10, -5, 10, -5, 10, -5]), capital=1000)
        self.assertEqual(perf['tradeCount'], 8)
        self.assertEqual(perf['tradingDays'], 8)
        self.assertAlmostEqual(perf['netPnl'], 20)
        self.assertAlmostEqual(perf['profitFactor'], 2.0)
        self.assertAlmostEqual(perf['expectancy'], 2.5)
        self.assertAlmostEqual(perf['winRate'], 0.5)
        self.assertAlmostEqual(perf['maxDrawdown'], 5 / 1010)
        self.assertGreater(perf['sharpe'], 0)
        self.assertGreater(perf['sortino'], perf['sharpe'])

    def test_all_wins_have_no_profit_factor_not_infinity(self):
        perf = lr.performance(trades([5, 5, 5]), capital=1000)
        self.assertIsNone(perf['profitFactor'])
        self.assertIsNone(perf['sortino'])

    def test_too_little_data_leaves_ratios_unknown(self):
        perf = lr.performance(trades([5]), capital=1000)
        self.assertIsNone(perf['sharpe'])
        empty = lr.performance([], capital=1000)
        self.assertEqual(empty['tradeCount'], 0)
        self.assertIsNone(empty['expectancy'])
        self.assertIsNone(empty['maxDrawdown'])

    def test_bad_inputs_are_refused(self):
        for bad in ([dict(day='x', net=1)], [dict(day='2026-01-01', net=float('nan'))], [dict(day='2026-01-01')], 'abc'):
            with self.assertRaises(ValueError):
                lr.performance(bad, capital=1000)
        with self.assertRaises(ValueError):
            lr.performance([], capital=0)

    def test_bootstrap_interval_is_deterministic_and_straddles_zero_for_noise(self):
        noise = trades([3, -3, 2, -2, 4, -4, 1, -1, 3, -3] * 5)
        low, high = lr.bootstrap_expectancy(noise, seed=1)
        self.assertEqual((low, high), lr.bootstrap_expectancy(noise, seed=1))
        self.assertLess(low, 0)
        self.assertGreater(high, 0)
        edge = trades([5, 4, 6, -1, 5, 4, 6, -1, 5, 4] * 5)
        self.assertGreater(lr.bootstrap_expectancy(edge, seed=1)[0], 0)
        self.assertEqual(lr.bootstrap_expectancy(trades([1, 2]), seed=1), (None, None))

    def test_risk_of_ruin_rises_with_losses_and_is_a_probability(self):
        good = lr.risk_of_ruin(trades([5, 4, 6, -1] * 20), capital=1000, ruin_fraction=0.08, seed=2)
        bad = lr.risk_of_ruin(trades([-5, 4, -6, 1] * 20), capital=1000, ruin_fraction=0.08, seed=2)
        self.assertTrue(0 <= good <= bad <= 1)
        self.assertGreater(bad, 0.5)
        self.assertIsNone(lr.risk_of_ruin(trades([1]), capital=1000, ruin_fraction=0.08, seed=2))


class GateTests(unittest.TestCase):
    def passing_perf(self):
        return dict(tradeCount=600, tradingDays=600, sessions=600, sharpe=1.8, sortino=2.0, profitFactor=1.7, maxDrawdown=0.05,
                    calmar=2.0, expectancy=1.0, netPnl=400.0)

    def test_every_default_threshold_is_the_conservative_value_from_the_project_prompt(self):
        t = lr.THRESHOLDS
        self.assertEqual((t['minTrades'], t['minSharpe'], t['minSortino'], t['minProfitFactor']), (300, 1.5, 1.5, 1.5))
        self.assertEqual((t['maxDrawdown'], t['minCalmar'], t['minPaperDays'], t['minShadowDays']), (0.08, 1.0, 60, 10))

    def test_quant_criteria_pass_only_when_measured_and_met(self):
        result = lr.quant_criteria(self.passing_perf(), forward_days=70)
        self.assertTrue(all(item['status'] == 'pass' for item in result), result)
        unknown = dict(self.passing_perf(), sharpe=None)
        self.assertEqual({i['id']: i['status'] for i in lr.quant_criteria(unknown, 70)}['quant.sharpe'], 'unverified')
        worse = dict(self.passing_perf(), maxDrawdown=0.12)
        self.assertEqual({i['id']: i['status'] for i in lr.quant_criteria(worse, 70)}['quant.drawdown'], 'fail')

    def test_history_is_judged_on_elapsed_sessions_not_trade_days(self):
        status = lambda perf: {i['id']: i['status'] for i in lr.quant_criteria(perf, 70)}['quant.history']  # noqa: E731
        self.assertEqual(status(dict(self.passing_perf(), tradingDays=100, sessions=600)), 'pass')
        self.assertEqual(status(dict(self.passing_perf(), tradingDays=600, sessions=100)), 'fail')

    def test_forward_days_are_never_inferred_from_backtest_days(self):
        result = {i['id']: i['status'] for i in lr.quant_criteria(self.passing_perf(), forward_days=0)}
        self.assertNotEqual(result['quant.paper_days'], 'pass')


class ScoreTests(unittest.TestCase):
    def test_domain_weights_total_one_hundred_and_every_domain_is_covered(self):
        self.assertEqual(sum(lr.DOMAINS.values()), 100)
        points = {}
        for criterion in lr.CRITERIA:
            points[criterion['domain']] = points.get(criterion['domain'], 0) + criterion['points']
        self.assertEqual(points, lr.DOMAINS)

    def test_missing_evidence_gets_no_credit_and_a_claim_needs_a_real_source_file(self):
        report = lr.assess(evidence={}, performance=None, forward_days=0, shadow_days=0, root=ROOT)
        self.assertEqual(report['score'], 0)
        ghost = {'risk.entry_gate': dict(status='pass', source='tests/does_not_exist.py')}
        self.assertEqual(lr.assess(ghost, None, 0, 0, root=ROOT)['score'], 0)
        real = {'risk.entry_gate': dict(status='pass', source='tests/test_entry_gate.py')}
        report = lr.assess(real, None, 0, 0, root=ROOT)
        self.assertEqual(report['score'], next(c['points'] for c in lr.CRITERIA if c['id'] == 'risk.entry_gate'))

    def test_a_source_outside_the_repo_or_unsafe_path_gets_no_credit(self):
        for source in ('../outside.py', 'C:/Windows/win.ini', '/etc/passwd', ''):
            claim = {'risk.entry_gate': dict(status='pass', source=source)}
            self.assertEqual(lr.assess(claim, None, 0, 0, root=ROOT)['score'], 0)

    def test_classification_bands(self):
        for score, name in ((0, 'DEVELOPMENT ONLY'), (59, 'DEVELOPMENT ONLY'), (60, 'BACKTESTING ONLY'), (74, 'BACKTESTING ONLY'),
                            (75, 'PAPER AND SHADOW TRADING'), (89, 'PAPER AND SHADOW TRADING'),
                            (90, 'ELIGIBLE FOR MICRO-LIVE APPROVAL'), (100, 'ELIGIBLE FOR MICRO-LIVE APPROVAL')):
            self.assertEqual(lr.classify(score), name)

    def test_classification_is_capped_by_an_open_blocker_but_not_by_owner_authorisation_alone(self):
        self.assertEqual(lr.classify(100, [dict(id='net_expectancy', status='blocked')]), 'PAPER AND SHADOW TRADING')
        self.assertEqual(lr.classify(100, [dict(id=lr.OWNER_GATE, status='blocked')]), 'ELIGIBLE FOR MICRO-LIVE APPROVAL')
        self.assertEqual(lr.classify(70, [dict(id='x', status='blocked')]), 'BACKTESTING ONLY')

    def test_a_hundred_points_cannot_override_a_blocker(self):
        report = lr.assess(evidence={}, performance=None, forward_days=0, shadow_days=0, root=ROOT, human_authorisation=None)
        self.assertIn('human_authorisation', {b['id'] for b in report['blockers']})
        full = lr.decide(score=100, blockers=[dict(id='x', status='blocked')])
        self.assertNotIn('MICRO-LIVE', full)
        self.assertEqual(full, 'PAPER TRADING READY')
        self.assertEqual(lr.decide(score=100, blockers=[]), 'MICRO-LIVE ELIGIBLE — HUMAN APPROVAL REQUIRED')
        # owner authorisation is given AFTER eligibility, so it alone does not cap the decision
        self.assertEqual(lr.decide(score=90, blockers=[dict(id=lr.OWNER_GATE, status='blocked')]), lr.MICRO_LIVE)
        self.assertEqual(lr.decide(score=89, blockers=[]), 'PAPER TRADING READY')
        self.assertEqual(lr.decide(score=50, blockers=[]), 'NOT READY')
        self.assertEqual(lr.decide(score=65, blockers=[dict(id='x')]), 'BACKTEST READY')
        self.assertEqual(lr.decide(score=80, blockers=[dict(id='x')]), 'PAPER TRADING READY')

    def test_no_data_means_every_quantitative_blocker_is_blocked(self):
        report = lr.assess({}, None, 0, 0, root=ROOT)
        ids = {b['id'] for b in report['blockers']}
        for needed in ('forward_testing_days', 'independent_trade_sample', 'net_expectancy', 'maximum_drawdown',
                       'broker_compliance', 'shadow_trading_days', 'human_authorisation', 'order_reconciliation',
                       'disaster_recovery', 'security_vulnerabilities', 'emergency_kill_switch'):
            self.assertIn(needed, ids)
        self.assertEqual(ids, set(lr.GATE_IDS))
        self.assertTrue(all(b['status'] == 'blocked' for b in report['blockers']))
        self.assertEqual(report['decision'], 'NOT READY')
        self.assertFalse(report['liveTradingPermitted'])

    def test_negative_expectancy_and_excess_drawdown_block_even_with_credit(self):
        perf = dict(tradeCount=400, tradingDays=80, sharpe=1.8, sortino=2.0, profitFactor=1.7, maxDrawdown=0.12,
                    calmar=2.0, expectancy=-1.0, netPnl=-400.0)
        blockers = {b['id']: b['status'] for b in lr.assess({}, perf, 80, 20, root=ROOT)['blockers']}
        self.assertEqual(blockers['net_expectancy'], 'blocked')
        self.assertEqual(blockers['maximum_drawdown'], 'blocked')
        self.assertEqual(blockers['forward_testing_days'], 'clear')
        self.assertEqual(blockers['shadow_trading_days'], 'clear')

    def test_report_is_json_serialisable_and_never_claims_profit(self):
        report = lr.assess({}, None, 0, 0, root=ROOT)
        text = json.dumps(report, allow_nan=False)
        self.assertIn('"claimsProfitability": false', text)
        self.assertIn('generatedAt', report)
        self.assertFalse(any(isinstance(v, float) and not math.isfinite(v) for v in report.values()))


class GateBoundaryTests(unittest.TestCase):
    """Each of the 11 hard blockers, just below and at its threshold."""

    PERF = dict(tradeCount=300, tradingDays=300, sessions=600, sharpe=2.0, sortino=2.0, profitFactor=1.8, maxDrawdown=0.08,
                calmar=1.5, expectancy=0.01, netPnl=3.0)
    ALL = {c['id']: dict(status='pass', source='live_readiness.py') for c in lr.CRITERIA}
    OWNER = dict(by='owner', text='approved')

    def gates(self, evidence=None, perf=None, forward=60, shadow=10, owner=OWNER):
        report = lr.assess(self.ALL if evidence is None else evidence, self.PERF if perf is None else perf, forward, shadow,
                           root=ROOT, human_authorisation=owner)
        return {b['id']: b['status'] for b in report['blockers']}, report

    def test_everything_at_threshold_clears_every_gate(self):
        gates, report = self.gates()
        self.assertEqual(set(gates.values()), {'clear'}, gates)
        self.assertEqual(report['decision'], lr.MICRO_LIVE)
        self.assertFalse(report['liveTradingPermitted'])

    def test_each_gate_blocks_just_below_its_threshold(self):
        cases = {
            'forward_testing_days': dict(forward=59),
            'independent_trade_sample': dict(perf=dict(self.PERF, tradeCount=299)),
            'net_expectancy': dict(perf=dict(self.PERF, expectancy=0.0)),
            'maximum_drawdown': dict(perf=dict(self.PERF, maxDrawdown=0.0801)),
            'shadow_trading_days': dict(shadow=9),
            'broker_compliance': dict(evidence={k: v for k, v in self.ALL.items() if k != 'regulatory.zerodha_terms'}),
            'order_reconciliation': dict(evidence={k: v for k, v in self.ALL.items() if k != 'execution.broker_status'}),
            'disaster_recovery': dict(evidence={k: v for k, v in self.ALL.items() if k != 'reliability.chaos'}),
            'security_vulnerabilities': dict(evidence={k: v for k, v in self.ALL.items() if k != 'security.audit_high'}),
            'emergency_kill_switch': dict(evidence={k: v for k, v in self.ALL.items() if k != 'risk.kill_switch'}),
        }
        for gate, change in cases.items():
            gates, report = self.gates(**change)
            self.assertEqual([g for g, status in gates.items() if status == 'blocked'], [gate])
            self.assertNotEqual(report['decision'], lr.MICRO_LIVE, gate)
        self.assertEqual(self.gates(perf=dict(self.PERF, maxDrawdown=None))[0]['maximum_drawdown'], 'blocked')
        self.assertEqual(self.gates(perf=dict(self.PERF, expectancy=None))[0]['net_expectancy'], 'blocked')

    def test_owner_authorisation_needs_the_owner_and_written_text(self):
        for owner in (None, {}, dict(by='agent', text='ok'), dict(by='owner', text='  '), dict(by='owner', text=7), 'yes'):
            self.assertEqual(self.gates(owner=owner)[0][lr.OWNER_GATE], 'blocked', owner)


class EvidenceRuleTests(unittest.TestCase):
    def test_a_fail_or_malformed_claim_earns_nothing(self):
        for claim in (dict(status='fail', source='tests/test_entry_gate.py'), 'pass', ['pass'], None,
                      dict(status='PASS', source='live_readiness.py')):
            report = lr.assess({'risk.entry_gate': claim}, None, 0, 0, root=ROOT)
            self.assertEqual(report['score'], 0, claim)

    def test_a_test_citation_must_name_tests_that_exist(self):
        ok = 'tests/test_live_readiness.py::EvidenceRuleTests::test_a_test_citation_must_name_tests_that_exist'
        self.assertTrue(lr.source_ok(ok, ROOT))
        for bad in ('tests/test_live_readiness.py::NoSuchClass', 'tests/test_live_readiness.py::EvidenceRuleTests::nope',
                    'tests/test_live_readiness.py::a.b', 'tests/test_live_readiness.py::'):
            self.assertFalse(lr.source_ok(bad, ROOT), bad)

    def test_the_report_carries_lineage_and_marks_inputs_as_self_reported(self):
        a = lr.assess({}, None, 0, 0, root=ROOT)
        b = lr.assess({'risk.entry_gate': dict(status='pass', source='tests/test_entry_gate.py')}, None, 0, 0, root=ROOT)
        self.assertNotEqual(a['lineage']['evidenceSha256'], b['lineage']['evidenceSha256'])
        self.assertEqual(a['lineage']['selfReported'], ['trades', 'forwardDays', 'shadowDays'])


class SessionBasisTests(unittest.TestCase):
    def test_sharpe_and_calmar_are_computed_over_every_elapsed_session(self):
        # one trade per Monday: the four idle weekdays between trades count as zero-return sessions
        start = dt.date(2026, 1, 5)
        outcomes = [6, -2, 5, -3, 4, -1, 7, -2, 3, -1]
        sparse = [dict(day=(start + dt.timedelta(weeks=i)).isoformat(), net=v) for i, v in enumerate(outcomes)]
        perf = lr.performance(sparse, capital=1000)
        self.assertEqual(perf['sessions'], 46)
        by_day = {item['day']: item['net'] for item in sparse}
        weekdays = [start + dt.timedelta(days=n) for n in range(64) if (start + dt.timedelta(days=n)).weekday() < 5][:46]
        equity, daily = 1000.0, []
        for day in weekdays:
            gain = by_day.get(day.isoformat(), 0.0)
            daily.append(gain / equity)
            equity += gain
        mean = sum(daily) / len(daily)
        sd = math.sqrt(sum((r - mean) ** 2 for r in daily) / (len(daily) - 1))
        self.assertAlmostEqual(perf['sharpe'], mean / sd * math.sqrt(252), places=9)
        dense = lr.performance([dict(day=(start + dt.timedelta(days=i)).isoformat(), net=v) for i, v in enumerate(outcomes)],
                               capital=1000)
        self.assertGreater(dense['sharpe'], perf['sharpe'] * 1.5)
        self.assertAlmostEqual(perf['calmar'], (sum(outcomes) / 1000) * (252 / 46) / perf['maxDrawdown'], places=9)

    def test_an_explicit_exchange_calendar_is_used_and_must_contain_every_trade_day(self):
        sample = [dict(day='2026-01-05', net=5), dict(day='2026-01-07', net=-2), dict(day='2026-01-09', net=4)]
        perf = lr.performance(sample, capital=1000, sessions=['2026-01-05', '2026-01-07', '2026-01-08', '2026-01-09'])
        self.assertEqual(perf['sessions'], 4)
        with self.assertRaises(ValueError):
            lr.performance(sample, capital=1000, sessions=['2026-01-05', '2026-01-09'])

    def test_bootstrap_interval_matches_an_independent_percentile_calculation(self):
        import random
        sample = trades([5, -3, 2, 4, -1, 6, -2, 3, 1, -4, 2, 5])
        nets = [t['net'] for t in sample]
        rng = random.Random(4)
        means = sorted(sum(rng.choices(nets, k=len(nets))) / len(nets) for _ in range(2000))
        self.assertEqual(lr.bootstrap_expectancy(sample, seed=4), (means[50], means[1949]))


class RepositoryEvidenceTests(unittest.TestCase):
    """The tracked evidence file must only cite files that exist and must not overclaim."""

    def setUp(self):
        self.evidence = json.loads((ROOT / 'docs' / 'readiness-evidence.json').read_text(encoding='utf-8'))

    def test_every_cited_source_exists_and_every_id_is_a_known_criterion(self):
        known = {c['id'] for c in lr.CRITERIA}
        for key, claim in self.evidence['criteria'].items():
            self.assertIn(key, known)
            if claim['status'] == 'pass':
                self.assertTrue(lr.source_ok(claim['source'], ROOT), claim)

    def test_the_repository_is_honestly_not_ready_for_live_trading(self):
        report = lr.assess(self.evidence['criteria'], None, forward_days=0, shadow_days=0, root=ROOT)
        self.assertFalse(report['liveTradingPermitted'])
        self.assertIn(report['decision'], ('NOT READY', 'BACKTEST READY', 'PAPER TRADING READY'))
        self.assertTrue(any(b['status'] == 'blocked' for b in report['blockers']))


if __name__ == '__main__':
    unittest.main()
