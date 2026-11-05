import csv
import datetime as dt
import io
import unittest

from evaluation import FIELDS, demo_request, evaluate


class EvaluationTests(unittest.TestCase):
    def test_no_same_bar_fill_after_jump(self):
        data = demo_request()
        rows = data["candles"]["DEMO"]
        # An isolated surprise at the first holdout close is untradeable beforehand.
        # The rule can first buy the next morning at 200, never at 100.
        for i, row in enumerate(rows):
            o = 100 if i <= 240 else 200
            c = 100 if i < 240 else 200
            row.update(open=o, high=c, low=o, close=c)
        out = evaluate(dict(data, costBps=0, slippageBps=0))
        self.assertEqual(out["holdout"]["strategy"]["returnPct"], 0)
        self.assertEqual(out["holdout"]["benchmark"]["returnPct"], 100)
        self.assertEqual(out["holdout"]["strategy"]["completedTrades"], 1)

    def test_changing_final_window_leaves_validation_unchanged(self):
        data = demo_request()
        original = evaluate(data)
        for row in data["candles"]["DEMO"][240:]:
            for field in ("open", "high", "low", "close"):
                row[field] *= 2
        changed = evaluate(data)
        self.assertEqual(original["validation"], changed["validation"])
        self.assertNotEqual(original["fingerprint"], changed["fingerprint"])
        self.assertLess(original["validation"][-1]["end"], original["holdout"]["start"])

    def test_net_equity_reconciles_to_both_sides_on_flat_path(self):
        data = demo_request()
        for row in data["candles"]["DEMO"]:
            row.update(open=100, high=100, low=100, close=100)
        r = evaluate(dict(data, costBps=100, slippageBps=100))["holdout"]
        # 100000 buys 980 whole units at 101 + a 1% fee; sale at 99 less 1%.
        self.assertEqual(r["benchmark"]["finalEquity"], 100000 + 980*(99*.99-101*1.01))
        self.assertEqual(r["strategy"]["completedTrades"], 0)
        self.assertIsNone(r["strategy"]["winRatePct"])

    def test_daily_cutoff_excludes_unfinished_bar(self):
        data = demo_request()
        rows=data["candles"]["DEMO"]
        out=evaluate(dict(data, asOf=rows[-1]["date"]))
        self.assertEqual(out["completedBars"],len(rows)-1)

    def test_export_csv_matches_json_and_rejects_missing_values(self):
        data=demo_request()
        rows=data["candles"]["DEMO"]
        output=io.StringIO()
        writer=csv.DictWriter(output,fieldnames=("date",*FIELDS))
        writer.writeheader();writer.writerows(rows)
        expected=evaluate(data)
        csv_request={k:v for k,v in data.items() if k!="candles"}
        self.assertEqual(evaluate(dict(csv_request, csv=output.getvalue(),symbol="DEMO")),expected)
        with self.assertRaises(ValueError):
            evaluate(dict(csv_request, csv="when,close\n2020,100",symbol="DEMO"))

    def test_import_rejects_missing_friction_and_permission(self):
        for field in ("costBps","slippageBps","permitted"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                data=demo_request();del data[field];evaluate(data)

    def test_five_minute_gap_fails(self):
        data=demo_request();rows=data["candles"]["DEMO"][:149]
        start=dt.datetime.fromisoformat("2023-01-02T09:15:00+05:30")
        for i,row in enumerate(rows):
            row["date"]=(start+dt.timedelta(days=i//75,minutes=5*(i%75))).isoformat()
        data.update(interval="5minute",candles={"DEMO": rows})
        self.assertEqual(evaluate(data)["completedBars"],149)
        del rows[30]
        with self.assertRaisesRegex(ValueError,"Missing five-minute"):evaluate(data)
