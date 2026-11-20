import copy
from pathlib import Path
import tempfile
import unittest

from fundamental_research import research_long_term
from portal import Portal


class FundamentalResearchTests(unittest.TestCase):
    def request(self):
        source = dict(symbol='DEMO', provider='Fixture filings', url='https://example.invalid/filing',
                      publishedAt='2026-11-01T12:00:00+05:30', availableAt='2026-11-01T12:01:00+05:30')
        financials = dict(periodDays=90, currency='INR', unit='crores', accountingBasis='consolidated',
                          metrics=dict(revenue=200, netProfit=20, operatingCashFlow=30,
                                       totalDebt=40, totalEquity=100, cash=15))
        records = [dict(source, id='current', kind='fundamentals', data=dict(financials, periodEnd='2026-09-30')),
                   dict(source, id='prior', kind='fundamentals', data=dict(financials, periodEnd='2026-06-30',
                        metrics=dict(financials['metrics'], revenue=100, netProfit=10))),
                   dict(source, id='valuation', kind='valuation', data=dict(price=100, sharesOutstanding=100000000,
                        currency='INR', unit='crores')),
                   dict(source, id='sector', kind='sector', data=dict(name='Technology')),
                   dict(source, id='benchmark', kind='benchmark', data=dict(name='NIFTY IT', returnPct=3,
                        stockReturnPct=5, periodStart='2026-09-01', periodEnd='2026-10-31')),
                   dict(source, id='actions', kind='corporate-actions', data=dict(actions=['Board announced dividend'])),
                   dict(source, id='governance', kind='governance', data=dict(flags=['Auditor opinion supplied']))]
        return dict(horizon='long-term', watchlist=['DEMO'], permitted=True,
                    asOf='2026-11-20T12:00:00+05:30', evidenceRecords=records)

    def test_real_comparisons_with_sources_and_no_purchase_authority(self):
        report=research_long_term(self.request(), ['DEMO'])
        card=report['candidates'][0]
        self.assertEqual(report['status'],'Dated research evidence available')
        self.assertEqual(card['financials']['changes']['revenue']['percent'],100)
        self.assertEqual(card['financials']['ratios']['netMarginPct'],10)
        self.assertEqual(card['financials']['ratios']['debtToEquity'],.4)
        self.assertEqual(card['valuation']['marketCapitalization'],1000)
        self.assertEqual(card['valuation']['priceToPeriodEarnings'],50)
        self.assertEqual(card['benchmark']['excessReturnPercentagePoints'],2)
        self.assertFalse(card['autoPurchase'])
        self.assertFalse(report['executionAllowed'])

    def test_missing_and_future_evidence_stays_insufficient(self):
        request=self.request();request['evidenceRecords'][2]['availableAt']='2026-11-21T00:00:00+05:30'
        report=research_long_term(request,['DEMO'])
        self.assertIn('valuation',report['candidates'][0]['missing'])
        self.assertEqual(report['excluded'][0]['id'],'valuation')
        self.assertEqual(report['status'],'Insufficient evidence')

    def test_conflicting_identity_is_excluded_not_selected_by_order(self):
        request=self.request()
        changed=copy.deepcopy(request['evidenceRecords'][0]);changed['data']['metrics']['netProfit']=999
        request['evidenceRecords'].append(changed)
        card=research_long_term(request,['DEMO'])['candidates'][0]
        self.assertNotIn('current',card['financials']['citations'])
        self.assertIn('Comparable prior financial period',card['missing'])

    def test_units_and_periods_must_be_comparable(self):
        request=self.request();request['evidenceRecords'][1]['data']['periodDays']=365
        request['evidenceRecords'][2]['data']['currency']='USD'
        card=research_long_term(request,['DEMO'])['candidates'][0]
        self.assertEqual(card['financials']['changes'],{})
        self.assertNotIn('valuation',card)
        self.assertIn('Comparable prior financial period',card['missing'])
        self.assertIn('Comparable valuation currency and unit',card['missing'])

    def test_negative_or_zero_earnings_never_make_positive_pe(self):
        request=self.request();request['evidenceRecords'][0]['data']['metrics']['netProfit']=-5
        card=research_long_term(request,['DEMO'])['candidates'][0]
        self.assertIsNone(card['valuation']['priceToPeriodEarnings'])

    def test_permission_boolean_metrics_staleness_and_invalid_url(self):
        request=self.request();request['permitted']=False
        with self.assertRaises(ValueError):research_long_term(request,['DEMO'])
        request=self.request();request['evidenceRecords'][0]['data']['metrics']['revenue']=True
        request['evidenceRecords'][2]['publishedAt']='2026-01-01T00:00:00+05:30'
        request['evidenceRecords'][3]['url']='https://secret@example.invalid/'
        report=research_long_term(request,['DEMO'])
        self.assertEqual(len(report['excluded']),3)

    def test_existing_portal_watchlist_and_evidence_request(self):
        with tempfile.TemporaryDirectory() as folder:
            portal=Portal(Path(folder)/'portal.sqlite')
            self.assertEqual(portal.research(dict(horizon='long-term',watchlist=['DEMO']))['status'],'Insufficient evidence')
            result=portal.research(self.request())
            self.assertEqual(result['status'],'Dated research evidence available')
            self.assertEqual(portal.status()['watchlist'],['DEMO'])
