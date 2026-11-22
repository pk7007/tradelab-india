"""Cross-entry-point regression for the shared completed-close signal."""
import datetime as dt
import unittest
from unittest.mock import patch

from auto_selector import rank_candidates
from entry_review import evaluate as review_entry
from evaluation import demo_request, evaluate
from intraday_evaluation import evaluate_intraday
from strategy_contract import VERSION, target_long
from test_intraday_paper import CONFIG, bars


class SignalConsistencyTests(unittest.TestCase):
    calendar = dict(
        exchange='NSE', segment='EQ', version='fixture',
        source='https://example.invalid/calendar',
        availableAt='2026-01-01T00:00:00+05:30',
        sessions={'2026-01-02': dict(
            open='2026-01-02T09:15:00+05:30',
            close='2026-01-02T15:30:00+05:30')})

    def test_scanner_reviewer_and_intraday_replay_agree_at_signal_boundaries(self):
        for label, closes, expected in (
                ('warmup', [100 + i / 10 for i in range(19)], False),
                ('equal', [100.0] * 20, False),
                ('rising', [100 + i / 10 for i in range(20)], True),
                ('falling', [104 - i / 10 for i in range(20)], False)):
            with self.subTest(label=label):
                rows = bars(len(closes))
                for row, close in zip(rows, closes):
                    row.update(open=close, close=close, high=close + .1, low=close - .1)
                completed = dt.datetime.fromisoformat(rows[-1]['date']) + dt.timedelta(minutes=5)
                now = completed.isoformat()
                selected, excluded = rank_candidates({'DEMO': rows}, CONFIG, self.calendar, now)
                decision = review_entry(dict(
                    reviewedAt=now, receivedAt=now, signalAt=rows[-1]['date'],
                    closes=closes, selectionValid=True, authorized=True, ownerValid=True,
                    maxQuantity=1, entriesPaused=False, riskHalted=False))
                replay = evaluate_intraday(dict(permitted=True, config=CONFIG, bars=rows))
                self.assertEqual(target_long(closes), expected)
                self.assertEqual(bool(selected), expected, excluded)
                self.assertEqual(decision['status'] == 'eligible', expected)
                self.assertEqual(bool(replay['pending'] and replay['pending']['side'] == 'BUY'), expected)
                self.assertEqual(replay['signalContract'], VERSION)
                # A completed-close decision cannot fill at that same bar's open.
                self.assertEqual(replay['fills'], [])
                if expected:
                    following = bars(len(rows) + 1)[-1]
                    filled = evaluate_intraday(dict(permitted=True, config=CONFIG, bars=rows + [following]))
                    self.assertEqual(filled['fills'][0]['bar'], following['date'])
                    self.assertEqual(filled['fills'][0]['signalAt'], rows[-1]['date'])

    def test_historical_evaluator_passes_only_prior_completed_closes(self):
        data = demo_request()
        rows = data['candles']['DEMO']
        with patch('evaluation.target_long', wraps=target_long) as observed:
            report = evaluate(data)
        self.assertEqual(report['protocol'], VERSION)
        self.assertEqual(len(observed.call_args_list), len(rows) - 20)
        for offset, call in enumerate(observed.call_args_list, start=20):
            self.assertEqual(call.args[0], [row['close'] for row in rows[offset - 20:offset]])
