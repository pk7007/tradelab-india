"""Verify browser -> HTTP -> isolated paper ledger using controlled observations.

Run with a Python environment containing Playwright and installed Chromium.
No broker credentials, orders, running app or production database are used.
"""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT))

from test_intraday_http import IntradayHTTPTests


def main():
    from playwright.sync_api import sync_playwright

    case = IntradayHTTPTests()
    case.setUp()
    namespace = case.namespace
    namespace.update(API_KEY='fixture', API_SECRET='fixture', LIVE_ORDERS_ENABLED=False,
        LIVE_EXECUTION_READY=False, LIVE_READINESS_REASON='fixture', PAPER_BUILD='fixture')
    namespace['automatic_selection_status'] = lambda: dict(
        case.fixture.selector.status(), calendar=case.fixture.calendar)
    namespace['NEWS_AGENT'] = SimpleNamespace(status=lambda *args: dict(
        status='fixture', stale=False, sources=[], items=[]))
    base = 'http://127.0.0.1:' + str(case.server.server_port)
    errors = []
    try:
        with patch.dict(os.environ, KITE_DATA_STORAGE_APPROVED='true'), patch(
                'auto_selector.threading', SimpleNamespace(Thread=Mock())), sync_playwright() as p:
            browser = p.chromium.launch(headless=True, timeout=20000)
            context = browser.new_context(viewport=dict(width=390, height=844))
            context.add_cookies([dict(name='tradelab_session', value='fixture', url=base)])
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base, wait_until='networkidle')
            page.locator('#selection-permission').check()
            with page.expect_response(lambda response: response.url.endswith('/api/auto-selection/start')) as response:
                page.get_by_role('button', name='Start paper trading', exact=True).click()
            assert response.value.status == 200, response.value.text()
            page.wait_for_load_state('networkidle')
            fixture = case.fixture
            fixture.selector.tick()
            fixture.selector.tick()
            fixture.advance(10)
            page.evaluate('() => refreshSelection()')
            with page.expect_response(lambda response: response.url.endswith('/api/auto-selection/control')) as response:
                page.get_by_role('button', name='Pause new entries', exact=True).first.click()
            assert response.value.status == 200, response.value.text()
            assert response.value.json()['entriesPaused']
            page.wait_for_load_state('networkidle')
            with page.expect_response(lambda response: response.url.endswith('/api/auto-selection/control')) as response:
                page.get_by_role('button', name='End session and reconcile', exact=True).click()
            assert response.value.status == 200, response.value.text()
            assert response.value.json()['endRequested']
            page.wait_for_load_state('networkidle')
            fixture.advance(5)
            page.evaluate('() => refreshSelection()')
            page.get_by_role('heading', name='Closing report · reconciled and flat', exact=True).wait_for()
            summary = case.request('/api/intraday-session')[1]
            assert summary['report']['final'] and summary['report']['quantity'] == 0
            page.reload(wait_until='networkidle')
            page.get_by_role('heading', name='Closing report · reconciled and flat', exact=True).wait_for()
            assert page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth')
            assert not errors, errors
            case.broker_order.assert_not_called()
            report = summary['report']
            evidence = dict(mode='Controlled replay through actual browser and HTTP API',
                viewport='390x844', symbol=report['symbol'], capital=summary['savedProfile']['capital'],
                cash=report['cash'], fees=report['fees'], realized=report['realized'],
                quantity=report['quantity'], final=report['final'], fills=report['trace']['fills'],
                selection=report['trace']['selection'],
                receiptCount=len(report['trace']['receipts']), pageErrors=errors,
                brokerOrderCalls=case.broker_order.call_count)
            destination = ROOT / 'docs' / 'intraday-session-example.json'
            destination.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
            print(json.dumps({key: value for key, value in evidence.items()
                              if key not in ('fills', 'selection')}, indent=2))
            browser.close()
    finally:
        case.doCleanups()


if __name__ == '__main__':
    main()
