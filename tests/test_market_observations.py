import datetime as dt
import math
import sys
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from market_observations import TickGuard
from market_data import MarketData

NOW=dt.datetime(2026,11,22,12,tzinfo=dt.timezone.utc)
def tick(**changes):
 return dict(instrument_token=123,last_price=100,volume_traded=1000,
             exchange_timestamp=NOW,last_trade_time=NOW,**changes)

class TickAdmissionTests(unittest.TestCase):
 def test_bad_numbers_and_timestamps_are_rejected_without_exceptions(self):
  guard=TickGuard(123)
  for key,values in [('last_price',[True,0,-1,math.nan,math.inf,10**400]),
                     ('volume_traded',[True,-1,math.nan,10**400])]:
   for value in values:
    row=tick();row[key]=value
    self.assertIsNone(guard.observe(row,NOW))
  for key,value in [('exchange_timestamp',None),
                    ('exchange_timestamp',NOW-dt.timedelta(seconds=16)),
                    ('exchange_timestamp',NOW+dt.timedelta(seconds=20)),
                    ('last_trade_time',NOW+dt.timedelta(seconds=20))]:
   row=tick();row[key]=value
   self.assertIsNone(guard.observe(row,NOW))
  self.assertEqual(guard.accepted,0)
 def test_duplicates_reordering_and_cache_are_bounded(self):
  guard=TickGuard(123)
  self.assertIsNotNone(guard.observe(tick(),NOW))
  self.assertIsNone(guard.observe(tick(),NOW))
  old=tick();old['exchange_timestamp']=NOW-dt.timedelta(seconds=1)
  self.assertIsNone(guard.observe(old,NOW))
  for index in range(1100):
   row=tick();row['last_price']=101+index
   guard.observe(row,NOW)
  self.assertEqual(guard.status()['cacheEntries'],1024)
  self.assertEqual(guard.rejected['duplicate'],1)
  self.assertEqual(guard.rejected['out-of-order'],1)
 def test_sdk_naive_epoch_fields_keep_host_timezone_semantics(self):
  row=tick();local=NOW.astimezone().replace(tzinfo=None)
  row.update(exchange_timestamp=local,last_trade_time=local)
  self.assertEqual(TickGuard(123).observe(row,NOW)['exchangeTimestamp'],NOW.isoformat())
  for kwargs in [dict(max_age_seconds=True),dict(future_tolerance_seconds=True)]:
   with self.assertRaises(ValueError):TickGuard(123,**kwargs)
 def test_real_callback_contains_bad_tick_and_stale_generation(self):
  clock=[NOW]
  with tempfile.TemporaryDirectory() as folder:
   market=MarketData('FAKE',Path(folder),clock=lambda:clock[0],start_reaper=False)
   market.resolve=Mock(return_value=dict(instrument_token=123))
   first,second=Mock(),Mock()
   with patch.dict(sys.modules, {'kiteconnect':SimpleNamespace(KiteTicker=Mock(side_effect=[first,second]))}):
    market.start_stream('owner','FAKE_TOKEN','DEMO')
    old_callback=first.on_ticks
    invalid=tick();invalid['last_price']=10**400
    old_callback(first,[invalid,tick(),tick()])
    status=market.stream_status('owner')
    self.assertEqual(len(status['points']),1)
    self.assertEqual(status['tickHealth']['acceptedTicks'],1)
    self.assertEqual(status['tickHealth']['rejectedTicks'],2)
    self.assertTrue(status['freshTrade'])
    clock[0]+=dt.timedelta(seconds=16)
    self.assertFalse(market.stream_status('owner')['freshTrade'])
    market.start_stream('owner','FAKE_TOKEN','DEMO')
    old_callback(first,[tick()])
    self.assertEqual(market.stream_status('owner')['points'],[])
    second.on_ticks(second,{'malformed':'batch'})
    self.assertEqual(market.stream_status('owner')['tickHealth']['rejectedTicks'],1)
    market.close()
    second.close.assert_called_once()
