import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from evaluation import demo_request, evaluate
from experiment_registry import ExperimentRegistry


class ExperimentTests(unittest.TestCase):
    def test_parameter_tuning_does_not_reset_holdout_exposure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'research.sqlite'
            registry = ExperimentRegistry(path)
            first = evaluate(demo_request())
            one = registry.record(first)
            second = evaluate(dict(demo_request(), costBps=20))
            two = ExperimentRegistry(path).record(second)
            self.assertNotEqual(first['fingerprint'], second['fingerprint'])
            self.assertEqual(first['holdoutFingerprint'], second['holdoutFingerprint'])
            self.assertFalse(one['holdoutViewedBefore'])
            self.assertTrue(two['holdoutViewedBefore'])
            self.assertFalse(two['promotionAllowed'])
            with closing(sqlite3.connect(path)) as db:
                reports = [json.loads(r[0]) for r in db.execute('SELECT report FROM experiments')]
            self.assertEqual(len(reports), 2)
            self.assertLess(reports[0]['holdout']['excessReturnPct'], 0)
            self.assertNotIn('candles', reports[0])
