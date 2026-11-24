import ast
import io
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

import improvement_proposals as ip
from evaluation import demo_request, evaluate
from experiment_registry import ExperimentRegistry

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import propose_improvements as cli  # noqa: E402


def report(holdout_fp='h1', **holdout_strategy):
    base = dict(symbol='DEMO', fingerprint='f' * 64, capital=100000.0, datasetFingerprint='d', holdoutFingerprint=holdout_fp,
                validation=[dict(excessReturnPct=1.0, strategy=dict(returnPct=2.0))],
                holdout=dict(excessReturnPct=1.0, strategy=dict(returnPct=3.0, completedTrades=50, fees=100.0, slippage=50.0)),
                stressHoldout=dict(strategy=dict(returnPct=2.0)))
    base['holdout']['strategy'].update(holdout_strategy)
    return base


def rules_for(item, views=1):
    return {f['rule'] for f in ip.attribute(dict(id=1, created='t', holdoutViews=views, report=item))}


class RuleTests(unittest.TestCase):
    def test_a_clean_result_produces_no_finding(self):
        self.assertEqual(rules_for(report()), set())

    def test_trade_count_boundary(self):
        self.assertEqual(rules_for(report(completedTrades=29)), {'too-few-trades'})
        self.assertEqual(rules_for(report(completedTrades=30)), set())

    def test_costs_boundary_counts_fees_and_slippage(self):
        self.assertEqual(rules_for(report(returnPct=0.15)), {'costs-dominate'})            # 150 / 100000 = 0.15%
        self.assertEqual(rules_for(report(returnPct=0.1501)), set())
        self.assertEqual(rules_for(report(returnPct=0.12, fees=100.0, slippage=0.0)), set())  # 0.10% < 0.12%
        self.assertEqual(rules_for(report(returnPct=0.12, fees=100.0, slippage=50.0)), {'costs-dominate'})

    def test_doubled_cost_boundary(self):
        at_zero = dict(report(), stressHoldout=dict(strategy=dict(returnPct=0.0)))
        self.assertEqual(rules_for(at_zero), {'fails-doubled-costs'})
        above = dict(report(), stressHoldout=dict(strategy=dict(returnPct=0.01)))
        self.assertEqual(rules_for(above), set())

    def test_benchmark_rule_needs_every_window_to_trail(self):
        mixed = report()
        mixed['validation'] = [dict(excessReturnPct=-1.0, strategy=dict(returnPct=2.0))]
        self.assertEqual(rules_for(mixed), set())
        mixed['holdout']['excessReturnPct'] = -0.5
        self.assertEqual(rules_for(mixed), {'trails-benchmark'})

    def test_sign_change_between_windows(self):
        unstable = dict(report(), validation=[dict(excessReturnPct=1.0, strategy=dict(returnPct=-2.0))])
        self.assertEqual(rules_for(unstable), {'unstable-across-windows'})

    def test_holdout_views(self):
        self.assertEqual(rules_for(report(), views=1), set())
        self.assertEqual(rules_for(report(), views=2), {'holdout-reused'})

    def test_malformed_or_non_numeric_results_are_reported_not_skipped(self):
        for bad in (None, 'text', report(completedTrades='5'), report(returnPct=float('nan'))):
            self.assertEqual(rules_for(bad), {'unreadable-report'}, bad)
        self.assertEqual(rules_for(dict(report(), validation='x')), set())      # a non-list window set is ignored, not fatal

    def test_the_deterministic_demo_evaluation_gives_exactly_its_two_findings(self):
        self.assertEqual(rules_for(evaluate(demo_request())), {'too-few-trades', 'unstable-across-windows'})


class FileTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.registry_path = self.root / 'research.sqlite'
        self.registry = ExperimentRegistry(self.registry_path)
        self.out = self.root / 'private' / 'proposals.jsonl'

    def lines(self):
        return [json.loads(line) for line in self.out.read_text(encoding='utf-8').splitlines()]

    def test_nothing_is_written_for_clean_results(self):
        self.registry.record(report())
        self.assertEqual(ip.propose(self.registry_path, self.out), [])
        self.assertFalse(self.out.exists())

    def test_runs_append_only_and_are_idempotent(self):
        self.registry.record(report(completedTrades=5))
        first = ip.propose(self.registry_path, self.out)
        self.assertEqual(ip.propose(self.registry_path, self.out), [])
        self.registry.record(report('h2', completedTrades=6))
        second = ip.propose(self.registry_path, self.out)
        self.assertEqual([p['id'] for p in self.lines()], [p['id'] for p in first + second])   # earlier lines kept
        for proposal in self.lines():
            self.assertEqual((proposal['status'], proposal['requiresOwnerReview'], proposal['appliesAutomatically'],
                              proposal['claimsProfitability']), ('proposed', True, False, False))

    def test_several_findings_on_one_experiment_keep_distinct_ids(self):
        self.registry.record(report(completedTrades=5, returnPct=0.1))
        found = ip.propose(self.registry_path, self.out)
        self.assertEqual({p['rule'] for p in found}, {'too-few-trades', 'costs-dominate'})
        self.assertEqual(len({p['id'] for p in found}), 2)

    def test_a_recreated_registry_does_not_hide_new_proposals(self):
        self.registry.record(report(completedTrades=5))
        ip.propose(self.registry_path, self.out)
        self.registry_path.unlink()
        ExperimentRegistry(self.registry_path).record(dict(report('h9', completedTrades=7), fingerprint='e' * 64))
        self.assertEqual([p['rule'] for p in ip.propose(self.registry_path, self.out)], ['too-few-trades'])

    def test_a_partial_last_line_is_closed_before_appending(self):
        self.registry.record(report(completedTrades=5))
        self.out.parent.mkdir(parents=True)
        self.out.write_text('{"id": "broken', encoding='utf-8')
        new = ip.propose(self.registry_path, self.out)
        text = self.out.read_text(encoding='utf-8').splitlines()
        self.assertEqual(text[0], '{"id": "broken')
        self.assertEqual(json.loads(text[1])['id'], new[0]['id'])
        self.assertEqual(ip.propose(self.registry_path, self.out), [])

    def test_unreadable_rows_and_a_non_utf8_output_file_do_not_stop_the_run(self):
        self.registry.record(report(completedTrades=5))
        self.registry.record(report('h2'))
        with closing(sqlite3.connect(self.registry_path)) as db:
            db.execute("UPDATE experiments SET report='not json' WHERE id=2")
            db.commit()
        self.out.parent.mkdir(parents=True)
        self.out.write_bytes(b'\xff\xfe junk\n')
        self.assertEqual(sorted(p['rule'] for p in ip.propose(self.registry_path, self.out)), ['too-few-trades', 'unreadable-report'])

    def test_concurrent_runs_write_each_proposal_once(self):
        for n in range(40):
            self.registry.record(report('h%d' % n, completedTrades=5))
        errors = []

        def run():
            try:
                ip.propose(self.registry_path, self.out)
            except Exception as error:  # pragma: no cover - reported below
                errors.append(error)
        threads = [threading.Thread(target=run) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        ids = [p['id'] for p in self.lines()]
        self.assertEqual(len(ids), 40)
        self.assertEqual(len(set(ids)), 40)
        self.assertFalse(self.out.with_name(self.out.name + '.lock').exists())

    def test_a_held_lock_blocks_a_second_run_and_a_stale_one_is_taken_over(self):
        import os
        import time
        from unittest.mock import patch
        self.registry.record(report(completedTrades=5))
        self.out.parent.mkdir(parents=True)
        lock = self.out.with_name(self.out.name + '.lock')
        lock.write_text('held', encoding='utf-8')
        with patch.object(ip, 'LOCK_WAIT_SECONDS', 0.2):
            with self.assertRaisesRegex(RuntimeError, 'in progress'):
                ip.propose(self.registry_path, self.out)
        self.assertFalse(self.out.exists())
        old = time.time() - ip.STALE_LOCK_SECONDS - 5
        os.utime(lock, (old, old))
        self.assertEqual([p['rule'] for p in ip.propose(self.registry_path, self.out)], ['too-few-trades'])
        self.assertFalse(lock.exists())

    def test_non_finite_values_are_cleaned_before_writing(self):
        tiny = dict(report(returnPct=1.0), capital=1e-320)
        self.registry.record(tiny)
        found = ip.propose(self.registry_path, self.out)
        self.assertIn('costs-dominate', {p['rule'] for p in found})
        for line in self.out.read_text(encoding='utf-8').splitlines():
            json.loads(line)                                      # strict JSON: no NaN or Infinity

    def test_the_registry_connection_cannot_write(self):
        self.registry.record(report())
        with closing(ip._readonly(self.registry_path)) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("UPDATE experiments SET report='x'")
        before = self.registry_path.read_bytes()
        ip.propose(self.registry_path, self.out)
        self.assertEqual(self.registry_path.read_bytes(), before)

    def test_an_unreadable_registry_is_an_error_and_a_missing_one_is_empty(self):
        self.assertEqual(ip.propose(self.root / 'none.sqlite', self.out), [])
        empty = self.root / 'empty.sqlite'
        empty.write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'could not be read'):
            ip.propose(empty, self.out)

    def test_output_inside_the_repository_is_refused_except_the_private_folder(self):
        for path in (ROOT / 'docs' / 'proposals.jsonl', ROOT / 'proposals.jsonl'):
            with self.assertRaisesRegex(ValueError, 'private'):
                ip.propose(self.registry_path, path)
        self.assertEqual(ip._check_output(ROOT / 'data' / 'private' / 'p.jsonl'), (ROOT / 'data' / 'private' / 'p.jsonl').resolve())


class IsolationTests(unittest.TestCase):
    def test_the_module_cannot_reach_engines_limits_the_inbox_or_an_apply_step(self):
        tree = ast.parse((ROOT / 'improvement_proposals.py').read_text(encoding='utf-8'))
        imported = {a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertEqual(imported, {'contextlib', 'datetime', 'hashlib', 'json', 'math', 'os', 'sqlite3', 'time', 'pathlib'})
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        self.assertFalse({n for n in names if 'apply' in n or 'promote' in n})


class CliTests(unittest.TestCase):
    def test_cli_writes_to_the_given_private_file_and_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = Path(folder) / 'r.sqlite'
            ExperimentRegistry(registry).record(report(completedTrades=5))
            out = io.StringIO()
            target = Path(folder) / 'p' / 'proposals.jsonl'
            self.assertEqual(cli.main(['--registry', str(registry), '--out', str(target)], out), 0)
            self.assertTrue(target.exists())
            self.assertIn('too-few-trades', out.getvalue())
            self.assertIn('Nothing was changed', out.getvalue())
            missing = io.StringIO()
            self.assertEqual(cli.main(['--registry', str(Path(folder) / 'typo.sqlite'), '--out', str(target)], missing), 2)
            self.assertIn('not found', missing.getvalue())
            refused = io.StringIO()
            self.assertEqual(cli.main(['--registry', str(registry), '--out', str(ROOT / 'docs' / 'x.jsonl')], refused), 1)
            self.assertIn('private', refused.getvalue())


if __name__ == '__main__':
    unittest.main()
