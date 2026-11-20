import unittest

from scripts.batch_loss_audit import accounting, metrics
from strategy_contract import assumed_fill


class LossAccountingTests(unittest.TestCase):
    def fill(self, side, quantity, raw, stamp):
        price, fee=assumed_fill(raw,quantity,side,10,5)
        return dict(side=side,quantity=quantity,price=price,fee=fee,bar=stamp,reason='fixture')

    def test_partial_exit_grouped_once_with_exact_cost_identity(self):
        rows=[self.fill('BUY',10,100,'2026-01-02T10:00:00+05:30'),
              self.fill('SELL',4,102,'2026-01-02T10:05:00+05:30'),
              self.fill('SELL',6,103,'2026-01-02T10:10:00+05:30')]
        report=accounting(rows,dict(costBps=10,slippageBps=5))
        self.assertEqual(report['openQuantity'],0)
        self.assertEqual(len(report['trades']),1)
        trade=report['trades'][0]
        self.assertAlmostEqual(trade['rawGross'],26)
        self.assertAlmostEqual(trade['net'],trade['rawGross']-trade['slippage']-trade['fees'])
        self.assertAlmostEqual(trade['net'],report['cashDelta'])
        self.assertEqual(trade['holdingMinutes'],10)

    def test_unclosed_position_is_not_counted_as_trade(self):
        row=self.fill('BUY',2,100,'2026-01-02T10:00:00+05:30')
        report=accounting([row],dict(costBps=10,slippageBps=5))
        self.assertEqual(report['openQuantity'],2)
        self.assertEqual(metrics(report['trades'])['completedTrades'],0)
        self.assertGreater(report['remainingBasis'],200)

    def test_oversell_or_corrupt_fee_rejected(self):
        row=self.fill('SELL',2,100,'2026-01-02T10:00:00+05:30')
        with self.assertRaises(ValueError):accounting([row],dict(costBps=10,slippageBps=5))
        row=self.fill('BUY',2,100,'2026-01-02T10:00:00+05:30');row['fee']=0
        with self.assertRaises(ValueError):accounting([row],dict(costBps=10,slippageBps=5))
