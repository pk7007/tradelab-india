import datetime as dt
import unittest
from types import SimpleNamespace
from dashboard_news import DashboardNews


class DashboardNewsTests(unittest.TestCase):
    def setUp(self):
        now=dt.datetime.now(dt.timezone.utc).isoformat()
        self.item=dict(id='one',source='nse',sourceName='NSE',title='DEMO LIMITED',summary='Results',url='https://www.nseindia.com/',publishedAt=now,receivedAt=now)
        self.payload=dict(status='fetched',sources=[dict(source='nse',status='fetched',checkedAt=now)],items=[self.item])
        self.calls=0
        def poll():
            self.calls+=1
            return self.payload
        self.service=DashboardNews(None,SimpleNamespace(poll_once=poll))
        self.master=[dict(exchange='NSE',instrument_type='EQ',name='DEMO LIMITED',tradingsymbol='DEMO')]

    def test_cache_retains_unchanged_items_and_maps_only_exact_names(self):
        self.assertEqual(self.service.status(self.master)['items'][0]['symbols'],['DEMO'])
        self.service.status(self.master);self.assertEqual(self.calls,1)
        self.service.checked=None;self.payload['items']=[]
        self.assertEqual(len(self.service.status(self.master)['items']),1)

    def test_failed_source_removes_previous_items(self):
        self.service.status(self.master)
        self.service.checked=None;self.payload=dict(status='unavailable',sources=[dict(source='nse',status='unavailable')],items=[])
        result=self.service.status(self.master)
        self.assertTrue(result['stale']);self.assertEqual(result['items'],[])

    def test_editorial_text_never_becomes_verified_symbol(self):
        self.item['source']='et';self.payload['sources'][0]['source']='et'
        result=self.service.status(self.master)
        self.assertEqual(result['items'][0]['symbols'],[])
        self.assertFalse(result['executionAllowed'])
