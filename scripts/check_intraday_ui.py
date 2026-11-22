"""Exercise Start -> scheduler -> automatic exit -> closing report in Chromium.

Uses the real HTTP handler, selector loop and isolated persistent ledger with a
controlled market clock. Requires Playwright and installed Chromium.
"""
import datetime as dt
import json
import math
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT))

from test_intraday_http import IntradayHTTPTests
from test_intraday_paper import bars


def oracle(config):
    """Calculate this fixed replay's entry size and square-off independently."""
    rows = bars(75)
    entry = rows[22]['open']  # 11:05, following the post-warmup signal.
    exit_price = rows[70]['open']  # Planned 15:05 square-off.
    fees = config['costBps'] / 10000
    slip = config['slippageBps'] / 10000
    buy = entry * (1 + slip)
    sell = exit_price * (1 - slip)
    cash_per_share = buy * (1 + fees)
    stop_proceeds = entry * (1 - config['stopDistancePct'] / 100) * (1 - slip) * (1 - fees)
    quantity = math.floor(min(config['units'], config['capital'] / cash_per_share,
        config['maxExposure'] / cash_per_share, config['maxLoss'] / (cash_per_share - stop_proceeds),
        rows[22]['volume'] * config['participationPct'] / 100))
    total_fees = quantity * (buy + sell) * fees
    closing_cash = config['capital'] + quantity * (sell - buy) - total_fees
    return dict(quantity=quantity, buyPrice=buy, sellPrice=sell, fees=total_fees,
                cash=closing_cash, pnl=closing_cash - config['capital'])


def run_scenario(browser, qualifying):
    case = IntradayHTTPTests()
    case.setUp()
    fixture = case.fixture
    fixture.config.update(capital=10000, maxExposure=10000, maxLoss=250,
                          dailyLossLimit=1000, targetMultiple=20)
    fixture.rows = bars(75)
    if not qualifying:
        fixture.rows = [dict(row, volume=0) for row in fixture.rows]
    case.template = fixture.engine.create(fixture.config)['id']
    initial_accounts = len(fixture.engine.status()['accounts'])
    case.namespace.update(API_KEY='fixture', API_SECRET='fixture', LIVE_ORDERS_ENABLED=False,
        LIVE_EXECUTION_READY=False, LIVE_READINESS_REASON='fixture', PAPER_BUILD='fixture')
    case.namespace['automatic_selection_status'] = lambda: dict(
        fixture.selector.status(), calendar=fixture.calendar)
    case.namespace['NEWS_AGENT'] = SimpleNamespace(status=lambda *args: dict(
        status='fixture', stale=False, sources=[], items=[]))
    base = 'http://127.0.0.1:' + str(case.server.server_port)
    errors, mutations = [], []
    context = browser.new_context(viewport=dict(width=390, height=844))
    try:
        context.add_cookies([dict(name='tradelab_session', value='fixture', url=base)])
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: mutations.append(request.url.split(base)[-1])
                if request.method == 'POST' and '/api/auto-selection/' in request.url else None)
        page.goto(base, wait_until='networkidle')
        assert page.locator('#selection-permission').count() == 0
        with page.expect_response(lambda response: response.url.endswith('/api/auto-selection/start')) as response:
            page.get_by_role('button', name='Start paper trading', exact=True).click()
        assert response.value.status == 200, response.value.text()
        page.wait_for_load_state('networkidle')

        # Run the actual scheduled loop. Only its wait advances the fixture clock.
        cycles = []
        def next_clock(_seconds):
            fixture.now += dt.timedelta(seconds=30)
            cycles.append(fixture.now.isoformat())
            if len(cycles) > 1000:
                raise AssertionError('The session never completed automatically.')
        with patch.object(fixture.selector.shutdown, 'wait', side_effect=next_clock):
            fixture.selector.loop()

        page.evaluate('() => refreshSelection()')
        page.get_by_role('heading', name='Closing report · reconciled and flat', exact=True).wait_for()
        summary = case.request('/api/intraday-session')[1]
        report = summary['report']
        assert report['final'] and report['quantity'] == 0 and report['pending'] is None
        assert report['reconciliation']['matches']
        assert mutations == ['/api/auto-selection/start'], mutations
        assert not fixture.selector.enabled
        if qualifying:
            expected = oracle(fixture.config)
            assert report['fillCount'] == 2, report['trace']['fills']
            buy, sell = report['trace']['fills']
            assert buy['quantity'] == sell['quantity'] == expected['quantity']
            assert buy['bar'] == bars(75)[22]['date']
            assert sell['bar'] == bars(75)[70]['date']
            for actual, predicted in ((buy['price'], expected['buyPrice']),
                                      (sell['price'], expected['sellPrice']),
                                      (report['cash'], expected['cash']),
                                      (report['fees'], expected['fees'])):
                assert math.isclose(actual, predicted, abs_tol=1e-7), (actual, predicted)
            assert len(fixture.engine.status()['accounts']) == initial_accounts + 1
        else:
            expected = dict(cash=10000, fees=0, pnl=0, quantity=0)
            assert report['fillCount'] == 0 and report['cash'] == 10000
            assert report['totalPnl'] == 0
            assert len(fixture.engine.status()['accounts']) == initial_accounts
        page.reload(wait_until='networkidle')
        page.get_by_role('heading', name='Closing report · reconciled and flat', exact=True).wait_for()
        assert page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth')
        assert not errors, errors
        assert mutations == ['/api/auto-selection/start']
        case.broker_order.assert_not_called()
        return dict(scenario='qualifying' if qualifying else 'no-trade',
                    mode='Controlled replay through browser, HTTP, real scheduler loop and isolated ledger',
                    viewport='390x844', symbol=report['symbol'], capital=summary['savedProfile']['capital'],
                    cash=report['cash'], fees=report['fees'], realized=report['realized'],
                    quantity=report['quantity'], final=report['final'],
                    fills=report['trace']['fills'], selection=report['trace']['selection'],
                    receiptCount=len(report['trace']['receipts']), oracle=expected,
                    schedulerCycles=len(cycles), browserTradingMutations=mutations,
                    pageErrors=errors, brokerOrderCalls=case.broker_order.call_count)
    finally:
        context.close()
        case.doCleanups()


def run_workspace_scenario(browser):
    """Four improvements exercised through the real handler, isolated storage."""
    case = IntradayHTTPTests(); case.setUp()
    case.namespace.update(API_KEY='fixture', API_SECRET='fixture', LIVE_ORDERS_ENABLED=False,
        LIVE_EXECUTION_READY=False, LIVE_READINESS_REASON='fixture', PAPER_BUILD='fixture')
    stories = [dict(id=str(i), source=source, title='DEMO announces results', symbols=['DEMO'],
        publisher=source.upper(), url='https://news.example/' + str(i),
        publishedAt='2026-11-22T06:00:00Z', availableAt='2026-11-22T06:01:00Z')
        for i, source in enumerate(('nse', 'et'))]
    stories[0]['filings'] = [dict(url='https://nsearchives.nseindia.com/corporate/demo.pdf',
        documentType='Financial results', contentStatus='linked-not-downloaded')]
    case.namespace['NEWS_AGENT'] = SimpleNamespace(status=lambda *args: dict(
        status='fetched', stale=False, sources=[], items=stories))
    case.namespace['ALERTS'].observe('fixture:outage', 'Fixture feed unavailable.', True)
    base = 'http://127.0.0.1:' + str(case.server.server_port)
    context = browser.new_context(viewport=dict(width=390, height=844))
    errors, posts = [], []
    try:
        context.add_cookies([dict(name='tradelab_session', value='fixture', url=base)])
        page = context.new_page(); page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda req: posts.append(req.url) if req.method == 'POST' else None)
        page.goto(base, wait_until='networkidle')
        page.get_by_text('Market news', exact=True).click()
        page.get_by_text('2 matching stories', exact=True).wait_for()
        page.locator('#news-kind-filter').select_option('filings')
        document_link = page.get_by_role('link', name='Open NSE filing - PDF', exact=True)
        document_link.wait_for()
        assert document_link.get_attribute('href') == 'https://nsearchives.nseindia.com/corporate/demo.pdf'
        page.locator('#news-kind-filter').select_option('all')
        page.locator('#news-search').fill('DEMO')
        page.get_by_text('Mapped stock match', exact=True).first.wait_for()
        page.locator('#news-source-filter').select_option('et')
        assert page.get_by_text('DEMO announces results', exact=True).count() == 1
        page.locator('#news-search').fill('NO_MATCH')
        page.get_by_text('No headlines match these filters.', exact=True).wait_for()
        assert not [path for path in posts if not path.endswith('/api/trader/paper-state')], posts
        page.get_by_text('Operational alerts', exact=False).first.click()
        page.get_by_role('button', name='Acknowledge', exact=True).click()
        page.get_by_text('Operational alerts · 0 unread', exact=True).wait_for()
        page.get_by_role('button', name='Settings', exact=True).click()
        page.get_by_text('Guided intraday paper setup', exact=True).click()
        page.get_by_role('button', name='Copy selected account settings', exact=True).click()
        form = page.locator('#guided-paper-setup')
        assert form.locator('[name=capital]').input_value() == str(case.fixture.config['capital'])
        page.get_by_role('button', name='Review paper profile', exact=True).click()
        confirm = page.get_by_role('button', name='Create paused paper account', exact=True)
        assert confirm.is_visible()
        form.locator('[name=units]').fill('50')
        assert not confirm.is_visible(), 'Editing must invalidate the reviewed configuration'
        page.get_by_role('button', name='Review paper profile', exact=True).click()
        before = len(case.fixture.engine.status()['accounts'])
        confirm.click()
        page.get_by_text('Paused paper account created. Review its settings before starting a session.', exact=True).wait_for()
        accounts = case.fixture.engine.status()['accounts']
        assert len(accounts) == before + 1
        created = next(account for account in accounts if account['config']['units'] == 50)
        assert created['status'] == 'paused' and created['quantity'] == 0
        page.get_by_text('Storage and service health', exact=True).click()
        page.get_by_role('button', name='Back up current databases', exact=True).click()
        page.get_by_text('Backup coverage 2/2 databases', exact=False).wait_for()
        page.get_by_role('button', name='Check an isolated restore', exact=True).click()
        page.get_by_text('Last restore check passed', exact=False).wait_for()
        assert case.namespace['OPERATIONS'].status()['lastRestoreDrill']['complete']
        assert page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth')
        assert not errors, errors
        assert not any('/auto-selection/start' in path for path in posts)
        case.broker_order.assert_not_called()
        return dict(scenario='guided-setup-news-alerts-recovery', pageErrors=errors,
                    pausedAccountCreated=True, isolatedRestore=True, brokerOrderCalls=0)
    finally:
        context.close(); case.doCleanups()


def main():
    from playwright.sync_api import sync_playwright
    with patch.dict(os.environ, KITE_DATA_STORAGE_APPROVED='true'), patch(
            'auto_selector.threading', SimpleNamespace(Thread=Mock(), RLock=threading.RLock, Event=threading.Event)), sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, timeout=20000)
        try:
            evidence = [run_scenario(browser, qualifying) for qualifying in (True, False)]
            evidence.append(run_workspace_scenario(browser))
        finally:
            browser.close()
    destination = ROOT / 'docs' / 'intraday-session-example.json'
    destination.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps([{key: value for key, value in case.items() if key not in ('fills', 'selection')}
                      for case in evidence], indent=2))


if __name__ == '__main__':
    main()
