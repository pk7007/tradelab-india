import datetime as dt
from pathlib import Path
import tempfile
import unittest
from dashboard_news import DashboardNews
from news_agent import NewsAgent
from nse_filings import safe_filing_url
from research_context import attach_announcements, evidence_references
NOW=dt.datetime(2026,11,22,12,tzinfo=dt.timezone.utc)
URL='https://nsearchives.nseindia.com/corporate/demo.pdf'
def feed(url=URL):
 return ('<rss><channel><item><title>Demo Limited</title><link>https://www.nseindia.com/announcement</link><description>Financial results</description><pubDate>22-Nov-2026 16:00:00</pubDate><enclosure url="'+url+'"/></item></channel></rss>').encode()
class NSEFilingTests(unittest.TestCase):
 def test_safe_links(self):
  self.assertEqual(safe_filing_url(URL+'#page=2'),URL)
  for value in ['http://nsearchives.nseindia.com/a.pdf','https://nsearchives.nseindia.com.evil.invalid/a.pdf','https://user@nsearchives.nseindia.com/a.pdf','https://nsearchives.nseindia.com:444/a.pdf','https://[bad',URL+'\n']:
   self.assertIsNone(safe_filing_url(value))
 def test_revision_mapping_and_staleness(self):
  with tempfile.TemporaryDirectory() as folder:
   raw,clock,calls=[feed()],[NOW],[]
   def fetch(url):
    calls.append(url)
    return raw[0]
   agent=NewsAgent(Path(folder)/'news.sqlite',sources=('nse',),fetch=fetch,clock=lambda:clock[0])
   first=agent.poll_once()['items'][0]
   self.assertEqual(first['filings'][0]['url'],URL)
   self.assertEqual(agent.poll_once()['items'],[])
   raw[0]=feed(URL.replace('demo.pdf','new.pdf'));clock[0]+=dt.timedelta(seconds=30)
   revised=agent.poll_once()['items'][0]
   self.assertEqual(first['id'],revised['id'])
   self.assertNotEqual(first['availableAt'],revised['availableAt'])
   self.assertEqual(revised['filings'][0]['availableAt'],revised['availableAt'])
   self.assertEqual(len(calls),3)
   self.assertNotIn(b'Financial results',agent.state.read_bytes())
   service=DashboardNews(None,agent,lambda:clock[0]);service.poll_due()
   master=[dict(exchange='NSE',instrument_type='EQ',name='Demo Limited',tradingsymbol='DEMO')]
   request,context=attach_announcements(dict(asOf=clock[0].isoformat()),service.status(master))
   self.assertEqual(context['attached'],1)
   self.assertEqual(request['records'][0]['filings'][0]['documentType'],'Financial results')
   refs=evidence_references(request['records'],'DEMO')
   self.assertEqual(refs[0]['filingIds'],[revised['filings'][0]['id']])
   self.assertEqual(attach_announcements(dict(asOf=NOW.isoformat()),service.status(master))[1]['attached'],0)
   clock[0]+=dt.timedelta(seconds=61)
   self.assertEqual(attach_announcements(dict(asOf=clock[0].isoformat()),service.status(master))[1]['attached'],0)

 def test_direct_pdf_and_description_anchor(self):
  import xml.etree.ElementTree as ET
  from announcements import parse_feed
  for primary in [True,False]:
   root=ET.fromstring(feed())
   item=root.find('./channel/item')
   item.remove(item.find('enclosure'))
   if primary:
    item.find('link').text=URL
   else:
    item.find('description').text='<a href="'+URL+'">Original PDF</a>'
   parsed=parse_feed(ET.tostring(root),NOW)
   self.assertEqual(parsed[0]['filingLinks'],[URL])
