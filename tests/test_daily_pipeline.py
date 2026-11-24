import ast
import inspect
import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import auto_selector
import daily_pipeline as dp
import entry_gate
import lineage_store
from test_auto_selector import SelectionTests

NOW = '2026-01-02T11:00:00+05:30'
QUOTE_AT = '2026-01-02T10:59:40+05:30'
BAR_END = '2026-01-02T10:55:00+05:30'


def scan(**overrides):
    args = dict(day='2026-01-02', now=NOW, symbols=['AAA', 'BBB', 'CCC', 'DDD'], quote_excluded=[],
                quote_observed_at=QUOTE_AT, candles={'AAA': [dict(date='2026-01-02T10:50:00+05:30', close=1)]},
                ranked=[dict(symbol='AAA', score=1.5)], excluded=[], candle_observed_at=BAR_END)
    args.update(overrides)
    return dp.assess_scan(**args)


class AssessTests(unittest.TestCase):
    def test_clean_scan_with_a_candidate_is_selected_with_a_four_task_chain(self):
        result = scan()
        self.assertEqual((result['decision'], result['selected']), ('selected', 'AAA'))
        self.assertEqual([t['domain'] for t in result['tasks']],
                         ['instrument-reference', 'quote-observations', 'historical-candles', 'selection'])
        self.assertEqual(result['finalTaskId'], result['tasks'][-1]['taskId'])
        for index, task in enumerate(result['tasks']):
            self.assertEqual(task['state'], 'reviewed')
            self.assertEqual(task['parents'], [result['tasks'][index - 1]['taskId']] if index else [])
            self.assertTrue(task['inputHash'] and task['availableAt'] and task['observedAt'] and task['source'])
            self.assertLessEqual(task['observedAt'], task['availableAt'])

    def test_no_candidate_is_an_abstention_with_a_reason_not_a_block(self):
        result = scan(ranked=[], excluded=[dict(symbol='AAA', reason='Shared SMA condition is false.')])
        self.assertEqual(result['decision'], 'abstain')
        self.assertIsNone(result['selected'])
        self.assertIn('no qualifying', result['reasons'][0].lower())
        self.assertEqual(result['tasks'][-1]['state'], 'reviewed')

    def test_empty_universe_blocks_selection(self):
        result = scan(symbols=[], ranked=[])
        self.assertEqual(result['decision'], 'blocked')
        self.assertTrue(any('universe' in r.lower() for r in result['reasons']))
        self.assertEqual(result['tasks'][0]['state'], 'blocked')

    def test_dead_quote_feed_blocks_selection_but_one_fresh_quote_in_four_is_enough(self):
        three = [dict(symbol=s, reason='Quote timestamp is stale or future.') for s in ('AAA', 'BBB', 'CCC')]
        self.assertEqual(scan(quote_excluded=three)['decision'], 'selected')   # 25% fresh >= the 20% floor
        bad = three + [dict(symbol='DDD', reason='Quote missing or malformed.')]
        result = scan(quote_excluded=bad)
        self.assertEqual(result['decision'], 'blocked')
        self.assertTrue(any('quote' in r.lower() for r in result['reasons']))
        self.assertEqual(result['tasks'][1]['state'], 'blocked')
        self.assertIsNone(result['selected'])

    def test_legitimate_exclusions_are_not_data_failures(self):
        excluded = [dict(symbol=s, reason='Quote price, capital or volume excludes this stock.') for s in ('AAA', 'BBB', 'CCC', 'DDD')]
        result = scan(quote_excluded=excluded, ranked=[], candles={})
        self.assertEqual(result['decision'], 'abstain')

    def test_bad_candle_data_blocks_but_a_false_signal_does_not(self):
        data_bad = [dict(symbol='AAA', reason='Candle gap.'), dict(symbol='BBB', reason='Latest completed candle is stale.')]
        self.assertEqual(scan(ranked=[], excluded=data_bad, candles={'AAA': [], 'BBB': []})['decision'], 'blocked')
        signal = [dict(symbol='AAA', reason='Shared SMA condition is false.'), dict(symbol='BBB', reason='No modeled liquidity.')]
        self.assertEqual(scan(ranked=[], excluded=signal, candles={'AAA': [], 'BBB': []})['decision'], 'abstain')

    @staticmethod
    def unclassified_reasons(source):
        """Reasons raised as bare literals that daily_pipeline does not classify, and constants used."""
        literals, names = set(), set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'ValueError' and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant):
                    literals.add(arg.value)
                elif isinstance(arg, ast.Attribute):
                    names.add(arg.attr)
        known = set(dp.CANDLE_DATA_FAULTS) | set(dp.LEGITIMATE_CANDLE_EXCLUSIONS)
        return literals - known, names

    def test_every_reason_rank_candidates_raises_is_classified_so_text_cannot_drift(self):
        unknown, names = self.unclassified_reasons(inspect.getsource(auto_selector.rank_candidates))
        self.assertEqual(unknown, set(), 'unclassified exclusion text')
        self.assertEqual(names, {'REASON_SIGNAL', 'REASON_LIQUIDITY', 'REASON_NO_SHARE'})

    def test_drift_check_catches_a_new_or_misspelled_reason(self):
        source = inspect.getsource(auto_selector.rank_candidates)
        for literal in ('Brand new reason.', 'Costs, cash or volume excludes a whole share.'):
            extra = "\n    raise ValueError('%s')\n" % literal
            unknown, _ = self.unclassified_reasons(source + extra)
            self.assertEqual(unknown, {literal})

    def test_availability_is_the_scan_time_when_observations_are_earlier(self):
        result = scan()
        for task in result['tasks']:
            self.assertEqual(task['availableAt'], '2026-01-02T11:00:00+05:30')
        self.assertLess(result['tasks'][1]['observedAt'], result['tasks'][1]['availableAt'])

    def test_whole_share_exclusions_are_normal_abstentions_not_data_faults(self):
        excluded = [dict(symbol=s, reason=dp.REASON_NO_SHARE) for s in ('AAA', 'BBB', 'CCC')]
        result = scan(ranked=[], excluded=excluded, candles={s: [] for s in ('AAA', 'BBB', 'CCC')})
        self.assertEqual(result['decision'], 'abstain')

    def test_mixed_real_world_exclusions_only_block_when_data_faults_dominate(self):
        series = {str(n): [] for n in range(20)}
        legit = [dict(symbol=str(n), reason=dp.REASON_SIGNAL if n % 2 else dp.REASON_NO_SHARE) for n in range(10)]
        few = [dict(symbol=str(n), reason='Candle gap.') for n in range(10, 13)]
        self.assertEqual(scan(ranked=[], excluded=legit + few, candles=series)['decision'], 'abstain')
        many = [dict(symbol=str(n), reason='Latest completed candle is stale.') for n in range(10, 21)]
        self.assertEqual(scan(ranked=[], excluded=legit[:9] + many, candles=series)['decision'], 'blocked')

    def test_large_universe_with_a_stale_tail_is_not_misread_as_a_dead_feed(self):
        symbols = ['S%04d' % n for n in range(2000)]
        stale = [dict(symbol=s, reason='Quote timestamp is stale or future.') for s in symbols[:1900]]
        self.assertEqual(scan(symbols=symbols, quote_excluded=stale)['decision'], 'selected')   # 100 fresh >= cap of 25
        dead = [dict(symbol=s, reason='Quote timestamp is stale or future.') for s in symbols[:1990]]
        self.assertEqual(scan(symbols=symbols, quote_excluded=dead)['decision'], 'blocked')      # 10 fresh < 25

    def test_future_dated_observations_are_faults_not_silently_clamped(self):
        future = scan(quote_observed_at='2026-01-02T11:05:00+05:30')
        self.assertEqual(future['decision'], 'blocked')
        self.assertTrue(any('feed clock' in r for r in future['reasons']))
        self.assertEqual(scan(candle_observed_at='2026-01-02T11:10:00+05:30')['decision'], 'blocked')
        for task in scan()['tasks']:
            self.assertLessEqual(task['observedAt'], task['availableAt'])

    def test_blocked_scan_never_names_a_selection_even_if_ranking_exists(self):
        bad = [dict(symbol=s, reason='Quote missing or malformed.') for s in ('AAA', 'BBB', 'CCC', 'DDD')]
        result = scan(quote_excluded=bad, ranked=[dict(symbol='AAA', score=9)])
        self.assertEqual(result['decision'], 'blocked')
        self.assertIsNone(result['selected'])
        self.assertEqual(result['tasks'][-1]['state'], 'blocked')

    def test_task_ids_are_deterministic_and_change_with_inputs(self):
        self.assertEqual(scan()['finalTaskId'], scan()['finalTaskId'])
        self.assertNotEqual(scan()['finalTaskId'], scan(symbols=['AAA', 'BBB'])['finalTaskId'])

    def test_optional_event_context_is_recorded_but_never_blocks(self):
        with_events = scan(optional_events=dict(status='unavailable', attached=0))
        self.assertEqual(with_events['decision'], 'selected')
        mapped = scan(optional_events=dict(status='matched', attached=2))
        self.assertEqual(mapped['decision'], 'selected')
        self.assertIn('event-entity-mapping', [o['domain'] for o in mapped['optional']])
        self.assertNotIn('event-entity-mapping', [t['domain'] for t in mapped['tasks']])

    def test_invalid_inputs_fail_closed(self):
        with self.assertRaises(ValueError):
            scan(now='not-a-time')
        with self.assertRaises(ValueError):
            scan(symbols='AAA')


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        lineage_store.ensure_schema(self.db)
        dp.ensure_schema(self.db)

    def test_record_persists_lineage_inputs_and_a_log_row(self):
        result = scan()
        dp.record_scan(self.db, result)
        rows = self.db.execute('SELECT domain,state,source,observed_at,available_at,input_hash FROM lineage_tasks ORDER BY seq').fetchall()
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r['available_at'] and r['input_hash'] and r['source'] for r in rows))
        log = self.db.execute('SELECT * FROM daily_selection_log').fetchone()
        self.assertEqual((log['day'], log['decision'], log['selected']), ('2026-01-02', 'selected', 'AAA'))
        self.assertEqual(log['final_task_id'], result['finalTaskId'])
        refs = json.loads(log['inputs'])
        self.assertEqual([r['domain'] for r in refs], ['instrument-reference', 'quote-observations', 'historical-candles', 'selection'])
        self.assertTrue(all(r['availableAt'] and r['inputHash'] for r in refs))

    def test_abstain_and_blocked_scans_are_logged_with_reasons(self):
        dp.record_scan(self.db, scan(ranked=[]))
        dp.record_scan(self.db, scan(symbols=[], ranked=[]))
        rows = self.db.execute('SELECT decision,reasons FROM daily_selection_log ORDER BY seq').fetchall()
        self.assertEqual([r['decision'] for r in rows], ['abstain', 'blocked'])
        self.assertTrue(all(json.loads(r['reasons']) for r in rows))

    def test_recording_the_same_scan_twice_adds_a_log_row_but_no_duplicate_lineage(self):
        result = scan()
        dp.record_scan(self.db, result)
        dp.record_scan(self.db, result)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM lineage_tasks').fetchone()[0], 4)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM daily_selection_log').fetchone()[0], 2)

    def test_record_runs_inside_the_callers_transaction(self):
        db = sqlite3.connect(':memory:', isolation_level=None)
        db.row_factory = sqlite3.Row
        lineage_store.ensure_schema(db)
        dp.ensure_schema(db)
        db.execute('BEGIN IMMEDIATE')
        dp.record_scan(db, scan())
        self.assertTrue(db.in_transaction)
        db.execute('ROLLBACK')
        self.assertEqual(db.execute('SELECT COUNT(*) FROM daily_selection_log').fetchone()[0], 0)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM lineage_tasks').fetchone()[0], 0)

    def test_selection_lineage_is_a_valid_chain_for_the_phase_a_store(self):
        result = scan()
        dp.record_scan(self.db, result)
        chain = lineage_store.chain(self.db, result['finalTaskId'])
        self.assertEqual([r['domain'] for r in chain][-1], 'selection')
        self.assertEqual(entry_gate.REQUIRED_DOMAINS[0], 'instrument-reference')  # shared domain vocabulary


class PipelineIntegrationTests(unittest.TestCase):
    """The real AutoSelector with offline fixtures: no network, no secrets."""
    setUp = SelectionTests.setUp
    start = SelectionTests.start
    advance = SelectionTests.advance

    def log(self):
        with self.engine.db() as db:
            return [dict(r) for r in db.execute('SELECT decision,selected,reasons,final_task_id FROM daily_selection_log ORDER BY seq')]

    def test_normal_scan_selects_and_logs_inputs_with_availability(self):
        self.start()
        self.selector.tick()
        rows = self.log()
        self.assertEqual(rows[0]['decision'], 'selected')
        self.assertEqual(rows[0]['selected'], 'DEMO')
        self.assertEqual(self.selector.status()['symbol'], 'DEMO')
        with self.engine.db() as db:
            domains = {r[0] for r in db.execute('SELECT domain FROM lineage_tasks')}
        self.assertTrue({'instrument-reference', 'quote-observations', 'historical-candles', 'selection'} <= domains)

    def test_stale_quotes_block_selection_for_the_scan_and_nothing_is_funded(self):
        self.start()
        stale = self.now.replace(minute=40)
        self.market.client = lambda _: SimpleNamespace(
            quote=lambda _s: {'NSE:DEMO': dict(last_price=102, volume=10000, timestamp=stale)},
            historical_data=lambda *a, **k: [])
        self.selector.tick()
        rows = self.log()
        self.assertEqual(rows[0]['decision'], 'blocked')
        self.assertIsNone(rows[0]['selected'])
        self.assertEqual(self.selector.detail['state'], 'selection-blocked')
        with self.engine.db() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM auto_selection').fetchone())

    def test_real_rank_candidates_whole_share_exclusion_is_an_abstention_end_to_end(self):
        self.start()
        tiny = dict(self.config, capital=1, maxExposure=1)
        ranked, excluded = auto_selector.rank_candidates({'DEMO': self.rows}, tiny, self.calendar, self.now.isoformat())
        self.assertEqual(ranked, [])
        self.assertEqual([e['reason'] for e in excluded], [dp.REASON_NO_SHARE])
        result = dp.assess_scan(day='2026-01-02', now=self.now.isoformat(), symbols=['DEMO'], quote_excluded=[],
                                quote_observed_at=self.now.isoformat(), candles={'DEMO': self.rows}, ranked=ranked,
                                excluded=excluded, candle_observed_at=self.now.isoformat())
        self.assertEqual(result['decision'], 'abstain')

    def test_future_dated_quotes_from_the_real_selector_are_absorbed_by_the_stale_rule(self):
        self.start()
        future = self.now.replace(minute=30)
        future = future.replace(hour=12)
        self.market.client = lambda _: SimpleNamespace(
            quote=lambda _s: {'NSE:DEMO': dict(last_price=102, volume=10000, timestamp=future)},
            historical_data=lambda *a, **k: [])
        self.selector.tick()
        self.assertEqual(self.log()[0]['decision'], 'blocked')
        self.assertIn('Only 0 of 1 quotes', json.loads(self.log()[0]['reasons'])[0])

    def test_no_candidate_is_logged_as_an_abstention(self):
        self.start()
        self.market.client = lambda _: SimpleNamespace(
            quote=lambda _s: {'NSE:DEMO': dict(last_price=999999, volume=10000, timestamp=self.now)},
            historical_data=lambda *a, **k: [])
        self.selector.tick()
        rows = self.log()
        self.assertEqual(rows[0]['decision'], 'abstain')
        self.assertEqual(self.selector.detail['state'], 'no-qualifying-candidate')
        self.assertTrue(json.loads(rows[0]['reasons']))

    def test_log_failure_blocks_selection_fail_closed(self):
        self.start()
        with patch.object(dp, 'record_scan', side_effect=sqlite3.OperationalError('disk')):
            self.selector.tick()
        self.assertEqual(self.selector.detail['state'], 'selection-blocked')
        with self.engine.db() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM auto_selection').fetchone())


del SelectionTests

if __name__ == '__main__':
    unittest.main()
