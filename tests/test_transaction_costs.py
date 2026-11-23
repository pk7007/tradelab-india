import datetime as dt
from decimal import Decimal
import unittest

from transaction_costs import (VERSION, UnsupportedCosts, estimate_order,
                               require_live_eligible, schedule_status)

D = Decimal
DAY = '2026-11-22'


def order(segment='equity-intraday', side='BUY', price='1000', quantity=100):
    return dict(costVersion=VERSION, exchange='NSE',
                accountType='resident-individual', segment=segment, side=side,
                settlement='normal-trade', price=price, quantity=quantity)


def estimate(values=None, **kwargs):
    args = dict(as_of=DAY, slippage_bps='0', other_charges_including_tax='0')
    args.update(kwargs)
    return estimate_order(values or order(), **args)


class TransactionCostTests(unittest.TestCase):
    def test_nse_published_cash_outflow_is_not_double_counted(self):
        result = estimate()
        raw = result['rawComponents']
        self.assertEqual(raw['exchange'], D('3.069900000'))
        self.assertEqual(raw['ipft'], D('0.000100000'))
        self.assertEqual(raw['exchange'] + raw['ipft'], D('3.07'))
        self.assertEqual(raw['sebi'], D('0.1'))
        self.assertEqual(raw['brokerage'], D('20'))
        self.assertEqual(raw['gst'], D('4.1706'))
        self.assertEqual(result['total'], D('30.34'))

    def test_intraday_stamp_buy_and_stt_sell_only(self):
        buy = estimate()['rawComponents']
        sell = estimate(order(side='SELL'))['rawComponents']
        self.assertEqual(buy['stt'], 0)
        self.assertEqual(buy['stampDuty'], D('3'))
        self.assertEqual(sell['stt'], D('25'))
        self.assertEqual(sell['stampDuty'], 0)

    def test_brokerage_is_per_executed_order_capped_not_per_fill(self):
        self.assertEqual(estimate(order(price='100', quantity=10))['rawComponents']['brokerage'], D('.3'))
        self.assertEqual(estimate(order(price='1000', quantity=1000))['rawComponents']['brokerage'], D('20'))

    def test_futures_2026_stt_and_exchange_outflow(self):
        result = estimate(order('equity-futures', 'SELL'))
        self.assertEqual(result['rawComponents']['stt'], D('50'))
        self.assertEqual(result['rawComponents']['exchange'] + result['rawComponents']['ipft'], D('1.83'))
        self.assertEqual(estimate(order('equity-futures'))['rawComponents']['stampDuty'], D('2'))

    def test_options_premium_stt_matches_official_rounding_example(self):
        result = estimate(order('equity-options', 'SELL', price='30', quantity=100))
        self.assertEqual(result['rawComponents']['stt'], D('4.5'))
        self.assertEqual(result['components']['stt'], D('5'))
        self.assertEqual(result['rawComponents']['brokerage'], D('20'))
        self.assertEqual(result['rawComponents']['exchange'] + result['rawComponents']['ipft'], D('1.0659'))

    def test_delivery_both_sides_stt_and_explicit_dp_no_double_gst(self):
        buy = estimate(order('equity-delivery'))
        sell = estimate(order('equity-delivery', 'SELL'), dp_charge_including_tax='15.34')
        self.assertEqual(buy['rawComponents']['stt'], D('100'))
        self.assertEqual(buy['rawComponents']['stampDuty'], D('15'))
        self.assertEqual(buy['rawComponents']['brokerage'], 0)
        self.assertEqual(sell['rawComponents']['stt'], D('100'))
        self.assertEqual(sell['rawComponents']['dpIncludingTax'], D('15.34'))
        self.assertEqual(sell['rawComponents']['gst'], buy['rawComponents']['gst'])
        with self.assertRaises(UnsupportedCosts):
            estimate(order('equity-delivery', 'SELL'))

    def test_slippage_and_other_charges_are_explicit_nonnegative_inputs(self):
        result = estimate(slippage_bps='5', other_charges_including_tax='2')
        self.assertEqual(result['rawComponents']['slippage'], D('50'))
        self.assertEqual(result['rawComponents']['otherChargesIncludingTax'], D('2'))
        with self.assertRaises(TypeError):
            estimate_order(order(), as_of=DAY)

    def test_conservative_reserve_covers_raw_and_presented_order_estimates(self):
        for segment in ('equity-intraday', 'equity-delivery', 'equity-futures', 'equity-options'):
            for side in ('BUY', 'SELL'):
                for price in ('1', '100.005', '10000'):
                    dp = '15.34' if segment == 'equity-delivery' and side == 'SELL' else None
                    result = estimate(order(segment, side, price, 3), dp_charge_including_tax=dp)
                    self.assertGreaterEqual(result['reserveTotal'], result['total'])
                    self.assertGreaterEqual(result['reserveTotal'], sum(result['rawComponents'].values()))
                    self.assertFalse(result['liveEligible'])
                    self.assertFalse(result['executionAllowed'])

    def test_dates_are_versioned_and_unverified_future_dates_block(self):
        self.assertEqual(schedule_status('2026-04-01')['version'], VERSION)
        for day in ('2026-03-31', '2026-11-23', '2027-01-01'):
            with self.assertRaises(UnsupportedCosts):
                estimate(as_of=day)
        for value in ('2026-4-1', 'invalid', dt.date(2026, 11, 22)):
            with self.assertRaises(ValueError):
                estimate(as_of=value)

    def test_unknown_account_exchange_segment_and_settlement_fail_closed(self):
        for field, value in [('exchange', 'BSE'), ('accountType', 'NRI'),
                             ('segment', 'commodity-futures'), ('costVersion', 'old'),
                             ('settlement', 'option-exercise'), ('settlement', 'physical-delivery')]:
            values = order()
            values[field] = value
            with self.assertRaises(UnsupportedCosts):
                estimate(values)

    def test_invalid_financial_values_and_boolean_inputs_are_rejected(self):
        for key, value in [('price', True), ('price', 100.1), ('price', 'NaN'),
                           ('price', 'Infinity'), ('price', '0'), ('quantity', True),
                           ('quantity', 1.5), ('quantity', 0), ('quantity', -1)]:
            values = order()
            values[key] = value
            with self.assertRaises(ValueError):
                estimate(values)
        for field in ('slippage_bps', 'other_charges_including_tax'):
            for value in (True, 1.1, '-1', 'NaN', 'Infinity'):
                with self.assertRaises(ValueError):
                    estimate(**{field: value})

    def test_dp_booleans_and_malformed_segments_are_rejected(self):
        with self.assertRaises(ValueError):
            estimate(dp_charge_including_tax=False)
        values = order()
        values['segment'] = []
        with self.assertRaises(UnsupportedCosts):
            estimate(values)

    def test_inputs_unchanged_and_cost_result_cannot_promote_live(self):
        values = order()
        original = dict(values)
        result = estimate(values)
        self.assertEqual(values, original)
        self.assertTrue(result['estimateOnly'])
        with self.assertRaises(UnsupportedCosts):
            require_live_eligible(result)
