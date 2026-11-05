import datetime as dt
import unittest

from test_trader_suite import PLAN, RISK, bars
from trader_suite import risk_check, time_machine, news
from validation_lab import simulate


class TradingAuditTests(unittest.TestCase):
    def test_risk_at_limit_or_one_rupee_over(self):
        self.assertTrue(risk_check(dict(RISK,dailyLoss=900))["allowed"])
        self.assertFalse(risk_check(dict(RISK,dailyLoss=901))["allowed"])
        self.assertFalse(risk_check(dict(RISK,target=100.01,slippageBps=30))["allowed"])

    def test_stop_can_trigger_on_entry_bar_and_shares_volume(self):
        rows=[dict(open=100+i,close=100+i,high=101+i,low=99+i,volume=10000) for i in range(24)]
        rows[20].update(low=100,volume=150)
        r=simulate(rows,capital=100000,units=10,fee_bps=0,slippage_bps=0,participation=.1,stop_pct=.05)
        fills=[f for f in r["fills"] if f["bar"]==20]
        self.assertEqual([(f["side"],f["quantity"],f["price"]) for f in fills],[("buy",10,120),("sell",5,114)])
        self.assertEqual(r["fills"][2]["quantity"],5)

    def test_scheduled_open_exit_precedes_later_intrabar_low(self):
        rows=[dict(open=100+i,close=100+i,high=101+i,low=99+i,volume=10000) for i in range(23)]
        # Fall below the moving-average threshold without touching a 90% stop.
        rows[20].update(close=20,low=19)
        rows[21].update(open=55,low=1,close=60,high=61)
        r=simulate(rows,capital=100000,units=10,fee_bps=0,slippage_bps=0,participation=1,stop_pct=.9)
        self.assertEqual((r["fills"][1]["price"],r["fills"][1]["reason"]),(55,"signal"))

    def test_replay_never_samples_overnight_gap_and_sees_first_breakout(self):
        rows=bars()
        for i,row in enumerate(rows):
            day=dt.datetime.fromisoformat(row["date"])
            if i>=20:
                row["date"]=(day+dt.timedelta(days=1,minutes=-100)).isoformat()
            price=100 if i<3 else 101 if i<20 else 202
            row.update(open=price,low=price,high=price,close=price)
        r=time_machine(dict(PLAN,candles={"DEMO":rows},asOf="2026-10-02T15:30:00+05:30",permitted=True,horizon=1))
        self.assertEqual(r["sampledReturnCount"],38)
        self.assertEqual(r["historicalMatches"][0]["signalAt"],rows[3]["date"])
        self.assertLessEqual(r["p95"],PLAN["maxLoss"])

    def test_news_honors_availability_and_merges_tracking_links(self):
        base=dict(title="Earnings",symbols=["AAA"],url="https://example.org/story",publishedAt="2026-01-02T10:00:00+05:30")
        data=dict(records=[base,dict(base,symbols=["BBB"],url=base["url"]+"?utm_source=mail#top"),
                           dict(base,url=base["url"]+"2",availableAt="2026-01-02T10:40:00+05:30")],
                  asOf="2026-01-02T10:30:00+05:30",watchlist="AAA,BBB",permitted=True)
        result=news(data)["items"]
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["watchMatches"],["AAA","BBB"])
