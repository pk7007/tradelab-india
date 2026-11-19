import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from execution_journal import ExecutionJournal

ORDER = dict(exchange='NSE', tradingsymbol='INFY', product='CNC', transaction_type='BUY', quantity=2, order_type='LIMIT', price=100)

class ExecutionJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'journal.sqlite'
        self.journal = ExecutionJournal(self.path)
        self.account = self.journal.account({'user_id':'fixture-account'})
    def prepare(self, review='review-one'):
        return self.journal.prepare(self.account, review, ORDER, b'fixture-digest')
    def broker(self, intent, status='COMPLETE', filled=2):
        return dict(ORDER, tag=intent['tag'], order_id='broker-one', status=status, filled_quantity=filled)
    def trade(self, quantity=2):
        return dict(ORDER, order_id='broker-one', trade_id='trade-one', quantity=quantity, average_price=100)
    def test_restart_and_new_review_cannot_resubmit_unknown(self):
        item=self.prepare(); self.journal.acknowledgement(item['id'])
        restarted=ExecutionJournal(self.path)
        with self.assertRaisesRegex(ValueError,'unresolved'):
            restarted.prepare(self.account,'new-review',ORDER,b'new-login')
        self.assertEqual(restarted.list(self.account)[0]['state'],'UNKNOWN')
    def test_parallel_separate_reviews_have_one_durable_winner(self):
        def submit(index):
            try:return self.prepare(str(index))['id']
            except ValueError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(submit,range(2)))
        self.assertEqual(sum(bool(x) for x in results),1)
    def test_missing_daily_book_never_releases_unknown(self):
        self.prepare()
        self.assertEqual(self.journal.reconcile(self.account,[],[])[0]['state'],'UNKNOWN')
        with self.assertRaises(ValueError):self.prepare('new')
    def test_terminal_requires_matching_trade_evidence(self):
        item=self.prepare()
        state=self.journal.reconcile(self.account,[self.broker(item)],[])[0]
        self.assertEqual(state['state'],'UNKNOWN')
        state=self.journal.reconcile(self.account,[self.broker(item)],[self.trade()])[0]
        self.assertEqual(state['state'],'COMPLETE')
        self.prepare('intentional-new-review')
        with self.assertRaises(ValueError):self.prepare('review-one')
    def test_partial_then_cancel_retains_fills_and_wrong_id_faults(self):
        item=self.prepare()
        state=self.journal.reconcile(self.account,[self.broker(item,'OPEN',1)],[self.trade(1)])[0]
        self.assertEqual((state['state'],state['filledQuantity']),('PARTIAL',1))
        wrong=dict(self.broker(item,'COMPLETE',2), order_id='wrong')
        state=self.journal.reconcile(self.account,[wrong],[self.trade()])[0]
        self.assertEqual((state['state'],state['filledQuantity'],state['brokerOrderId']),('UNKNOWN',1,'broker-one'))
        state=self.journal.reconcile(self.account,[self.broker(item,'CANCELLED',1)],[self.trade(1)])[0]
        self.assertEqual((state['state'],state['filledQuantity']),('CANCELLED',1))
    def test_missing_identity_and_duplicate_trades_rejected(self):
        with self.assertRaises(ValueError):self.journal.account({})
        item=self.prepare()
        state=self.journal.reconcile(self.account,[self.broker(item)],[self.trade(1),self.trade(1)])[0]
        self.assertEqual(state['state'],'UNKNOWN')
    def test_late_ack_cannot_undo_terminal(self):
        item=self.prepare()
        self.journal.reconcile(self.account,[self.broker(item)],[self.trade()])
        self.journal.acknowledgement(item['id'],'broker-one')
        self.assertEqual(self.journal.list(self.account)[0]['state'],'COMPLETE')

    def test_late_ack_preserves_partial_and_foreign_tag_blocks(self):
        item=self.prepare()
        self.journal.reconcile(self.account,[self.broker(item,'OPEN',1)],[self.trade(1)])
        self.journal.acknowledgement(item['id'],'broker-one')
        self.assertEqual(self.journal.list(self.account)[0]['state'],'PARTIAL')
        foreign=dict(self.broker(item),tag='unrelated')
        state=self.journal.reconcile(self.account,[foreign],[self.trade()])[0]
        self.assertEqual(state['state'],'UNKNOWN')
        self.assertEqual(state['filledQuantity'],1)

    def test_modified_order_and_invalid_fill_price_block_resolution(self):
        item=self.prepare()
        for changed in (dict(self.broker(item), price=10000), dict(self.broker(item), quantity=3)):
            result=self.journal.reconcile(self.account,[changed],[self.trade()])[0]
            self.assertEqual(result['state'],'UNKNOWN')
        for price in (10000, float('nan'), 0, True):
            result=self.journal.reconcile(self.account,[self.broker(item)],[dict(self.trade(),average_price=price)])[0]
            self.assertEqual(result['state'],'UNKNOWN')
