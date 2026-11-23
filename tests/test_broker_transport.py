import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch
from broker_transport import fetch_json, NoBrokerRedirect

URL='https://api.kite.trade/orders'
class BrokerTransportTests(unittest.TestCase):
 def response(self,raw):
  value=Mock()
  value.geturl.return_value=URL
  value.read.return_value=raw
  value.__enter__=Mock(return_value=value)
  value.__exit__=Mock(return_value=False)
  return value
 def test_only_approved_https_origin_can_receive_credentials(self):
  for address in ['http://api.kite.trade/orders','https://api.kite.trade.evil.invalid/orders',
                   'https://user@api.kite.trade/orders','https://api.kite.trade:444/orders',
                   'https://api.kite.trade/orders#fragment']:
   with patch('broker_transport.urllib.request.build_opener') as opener:
    with self.assertRaises(ValueError):
     fetch_json(urllib.request.Request(address,headers={'Authorization':'FAKE_ONLY'}))
    opener.assert_not_called()
 def test_valid_response_and_size_utf8_failures(self):
  for raw,valid in [(b'{"status":"success","data":[]}',True),
                    (b'X'*2_000_001,False),(b'\xff',False),(b'<html>',False)]:
   with patch('broker_transport.urllib.request.build_opener') as opener:
    opener.return_value.open.return_value=self.response(raw)
    if valid:
     self.assertEqual(fetch_json(urllib.request.Request(URL))['data'],[])
    else:
     with self.assertRaises((ValueError,UnicodeError)):
      fetch_json(urllib.request.Request(URL))
 def test_response_url_change_is_rejected(self):
  value=self.response(b'{"status":"success"}')
  value.geturl.return_value='https://evil.invalid/'
  with patch('broker_transport.urllib.request.build_opener') as opener:
   opener.return_value.open.return_value=value
   with self.assertRaises(ValueError):fetch_json(urllib.request.Request(URL))
 def test_cross_host_redirect_never_receives_dummy_authorization(self):
  received=[]
  class Sink(BaseHTTPRequestHandler):
   def do_GET(self):
    received.append(self.headers.get('Authorization'))
    self.send_response(200);self.end_headers()
   def log_message(self,*args):pass
  sink=ThreadingHTTPServer(('127.0.0.1',0),Sink)
  class Source(BaseHTTPRequestHandler):
   code=302
   def do_GET(self):
    self.send_response(self.code)
    self.send_header('Location','http://localhost:'+str(sink.server_port)+'/')
    self.end_headers()
   def log_message(self,*args):pass
  source=ThreadingHTTPServer(('127.0.0.1',0),Source)
  threads=[threading.Thread(target=s.serve_forever,daemon=True) for s in (source,sink)]
  for thread in threads:thread.start()
  try:
   opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoBrokerRedirect())
   for code in (302,307):
    Source.code=code
    request=urllib.request.Request('http://127.0.0.1:'+str(source.server_port)+'/',
                                  headers={'Authorization':'FAKE_ONLY'})
    with self.assertRaises(urllib.error.HTTPError) as caught:
     opener.open(request,timeout=2)
    caught.exception.close()
   self.assertEqual(received,[])
  finally:
   for server in (source,sink):server.shutdown();server.server_close()
   for thread in threads:thread.join(timeout=2)
