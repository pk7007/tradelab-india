import copy
import unittest
from broker_snapshot import build_snapshot


NOW='2026-11-20T10:00:00+05:30'


def payloads():
    return dict(profile={'user_id':'TEST1'},funds={'equity':{'net':1000,'available':{'cash':1000}}},
                orders=[],trades=[],positions={'net':[]},holdings=[])


def expected():
    return dict(cash=1000,positions={},holdings={},workingOrderIds=[],tradeIds=[])


class BrokerSnapshotTests(unittest.TestCase):
    def build(self,values=None,**kwargs):
        return build_snapshot('TEST1',values or payloads(),as_of=NOW,received_at=NOW,**kwargs)

    def test_missing_allocations_never_establish_ownership(self):
        result=self.build()
        self.assertFalse(result['matchesExpected']);self.assertFalse(result['executionAllowed'])
        self.assertFalse(result['positionsReconciled']);self.assertNotIn('TEST1',result['accountHash'])

    def test_matching_books_still_do_not_grant_execution(self):
        result=self.build(expected=expected())
        self.assertTrue(result['matchesExpected']);self.assertFalse(result['executionAllowed'])
        self.assertEqual(result['fingerprint'],self.build(expected=expected())['fingerprint'])

    def test_external_position_and_working_order_are_reported(self):
        values=payloads()
        values['positions']['net']=[dict(exchange='NSE',tradingsymbol='DEMO',product='MIS',quantity=2)]
        values['orders']=[dict(exchange='NSE',tradingsymbol='DEMO',product='MIS',quantity=2,filled_quantity=0,transaction_type='BUY',order_id='ord1',status='OPEN')]
        result=self.build(values,expected=expected())
        self.assertFalse(result['matchesExpected']);self.assertEqual(result['workingOrderIds'],['ord1'])
        self.assertEqual(len(result['differences']),2)

    def test_holdings_and_positions_are_never_summed(self):
        values=payloads();record=dict(exchange='NSE',tradingsymbol='DEMO',product='CNC',quantity=2)
        values['positions']['net']=[record];values['holdings']=[dict(record,t1_quantity=1)]
        result=self.build(values)
        self.assertEqual(result['positions']['NSE:DEMO:CNC']['quantity'],2)
        self.assertEqual(result['holdings']['NSE:DEMO:CNC']['t1Quantity'],1)
        self.assertNotIn('sellableQuantity',result)

    def test_wrong_account_stale_missing_and_failed_reads_rejected(self):
        values=payloads();values['profile']['user_id']='OTHER'
        with self.assertRaises(ValueError):self.build(values)
        values=payloads();values['orders']={'status':'error','data':[]}
        with self.assertRaises(ValueError):self.build(values)
        values=payloads();del values['holdings']
        with self.assertRaises(ValueError):self.build(values)
        with self.assertRaises(ValueError):
            build_snapshot('TEST1',payloads(),as_of=NOW,received_at='2026-11-20T09:59:00+05:30')

    def test_boolean_or_duplicate_financial_evidence_rejected(self):
        values=payloads();values['funds']['equity']['net']=True
        with self.assertRaises(ValueError):self.build(values)
        values=payloads();record=dict(exchange='NSE',tradingsymbol='DEMO',product='MIS',quantity=1)
        values['positions']['net']=[record,copy.deepcopy(record)]
        with self.assertRaises(ValueError):self.build(values)

    def test_trade_evidence_and_expected_activity_mismatch(self):
        values=payloads()
        values['trades']=[dict(exchange='NSE',tradingsymbol='DEMO',product='MIS',quantity=1,average_price=100,trade_id='t1',order_id='o1',transaction_type='BUY')]
        result=self.build(values,expected=expected())
        self.assertTrue(any('tradeIds' in reason for reason in result['differences']))
        values['trades']*=2
        with self.assertRaises(ValueError):self.build(values)

    def test_success_envelopes_are_supported(self):
        result=self.build({k:dict(status='success',data=v) for k,v in payloads().items()},expected=expected())
        self.assertTrue(result['matchesExpected'])

    def test_cross_instrument_trade_cannot_match_an_order(self):
        values=payloads()
        values['orders']=[dict(exchange='NSE',tradingsymbol='DEMO',product='MIS',quantity=1,filled_quantity=1,transaction_type='BUY',order_id='o1',status='COMPLETE')]
        values['trades']=[dict(exchange='NSE',tradingsymbol='OTHER',product='MIS',quantity=1,average_price=100,trade_id='t1',order_id='o1',transaction_type='BUY')]
        with self.assertRaises(ValueError):self.build(values)

    def test_missing_trade_fill_is_difference_even_if_books_match(self):
        values=payloads()
        values['orders']=[dict(exchange='NSE',tradingsymbol='DEMO',product='MIS',quantity=1,filled_quantity=1,transaction_type='BUY',order_id='o1',status='COMPLETE')]
        result=self.build(values,expected=expected())
        self.assertFalse(result['matchesExpected'])
        self.assertTrue(any('fill quantities' in reason for reason in result['differences']))
