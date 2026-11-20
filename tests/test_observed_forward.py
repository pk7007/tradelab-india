import copy
import datetime as dt
from pathlib import Path
import tempfile
import unittest

from observed_forward import observe, record_signal
from paper import PaperEngine
from test_intraday_paper import CONFIG, bars


class ObservedForwardTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        engine=PaperEngine(Path(self.folder.name)/'paper.sqlite')
        self.state=engine.create(dict(CONFIG,source='imported'))
        self.state['status']='running'
        self.calendar=dict(exchange='NSE',segment='EQ',source='https://example.invalid/calendar',
                           availableAt='2026-01-01T00:00:00+05:30',sessions={
                               '2026-01-02':dict(open='2026-01-02T09:15:00+05:30',close='2026-01-02T15:30:00+05:30')})

    def warm(self):
        for bar in bars(20):
            receipt=(dt.datetime.fromisoformat(bar['date'])+dt.timedelta(minutes=5)).isoformat()
            events=record_signal(self.state,bar,receipt,receipt)
            self.assertFalse(any(event['type']=='fill' for event in events))
        self.assertEqual(self.state['pending']['side'],'BUY')

    def quote(self,**changes):
        result=dict(instrument='NSE:DEMO',provider='fixture-quotes',exchangeAt='2026-01-02T10:55:01+05:30',
                    receivedAt='2026-01-02T10:55:02+05:30',bid=99.9,ask=100,bidQuantity=100,askQuantity=100)
        result.update(changes)
        return result

    def test_signals_never_fill_completed_bar_and_later_quote_fills_at_ask(self):
        self.warm()
        self.assertEqual(self.state['quantity'],0)
        events=observe(self.state,self.quote(), '2026-01-02T10:55:03+05:30',self.calendar)
        fill=next(event for event in events if event['type']=='fill')
        self.assertGreater(fill['price'],100)
        self.assertGreater(fill['exchangeAt'],self.state['lastDecisionAt'])
        self.assertEqual(self.state['quantity'],fill['quantity'])
        self.assertGreater(self.state['fees'],0)

    def test_predecision_quote_is_not_eligible(self):
        self.warm()
        events=observe(self.state,self.quote(exchangeAt='2026-01-02T10:54:59+05:30'),
                       '2026-01-02T10:55:03+05:30',self.calendar)
        self.assertFalse(any(event['type']=='fill' for event in events))
        self.assertEqual(self.state['quantity'],0)

    def test_stale_future_crossed_unknown_session_rejected_without_mutation(self):
        self.warm()
        for quote in (self.quote(exchangeAt='2026-01-02T09:00:00+05:30'),
                      self.quote(receivedAt='2026-01-02T11:00:00+05:30'),
                      self.quote(bid=101),self.quote(askQuantity=True)):
            before=copy.deepcopy(self.state)
            with self.assertRaises(ValueError):observe(self.state,quote,'2026-01-02T10:55:03+05:30',self.calendar)
            self.assertEqual(before,self.state)

    def test_partial_fill_and_observed_gap_exit_remain_reconcilable(self):
        self.warm()
        events=observe(self.state,self.quote(askQuantity=2),'2026-01-02T10:55:03+05:30',self.calendar)
        self.assertEqual(self.state['quantity'],2)
        self.assertTrue(any(event['type']=='cancelled' for event in events))
        events=observe(self.state,self.quote(exchangeAt='2026-01-02T10:55:04+05:30',
                       receivedAt='2026-01-02T10:55:05+05:30',bid=90,ask=90.1,bidQuantity=1),
                       '2026-01-02T10:55:06+05:30',self.calendar)
        fill=next(event for event in events if event['type']=='fill')
        self.assertLess(fill['price'],90)
        self.assertEqual(self.state['quantity'],1)
        self.assertEqual(self.state['pending']['side'],'SELL')
        self.assertLess(self.state['realized'],0)

    def test_quote_retransmission_and_wide_spread_do_not_fill(self):
        self.warm()
        quote=self.quote(bid=90)
        first=observe(self.state,quote,'2026-01-02T10:55:03+05:30',self.calendar)
        self.assertFalse(any(event['type']=='fill' for event in first))
        second=observe(self.state,quote,'2026-01-02T10:55:03+05:30',self.calendar)
        self.assertEqual(second[0]['reason'],'Duplicate or older exchange observation')

    def test_warmup_and_uncompleted_bars(self):
        bar=bars(1)[0]
        with self.assertRaises(ValueError):record_signal(self.state,bar,bar['date'],bar['date'])
        for bar in bars(20):
            receipt=(dt.datetime.fromisoformat(bar['date'])+dt.timedelta(minutes=5)).isoformat()
            record_signal(self.state,bar,receipt,receipt,warmup=True)
        self.assertIsNone(self.state['pending'])
