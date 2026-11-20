"""Dated, imported long-term evidence cards with no purchase authority."""
import datetime as dt
import math
import re
from urllib.parse import urlsplit

from research import timestamp


KINDS = ('fundamentals', 'valuation', 'corporate-actions', 'governance', 'sector', 'benchmark')
MAX_AGE_DAYS = {'fundamentals': 400, 'valuation': 30, 'corporate-actions': 90,
                'governance': 400, 'sector': 400, 'benchmark': 30}
METRICS = ('revenue', 'netProfit', 'operatingCashFlow', 'totalDebt', 'totalEquity', 'cash')


def _text(value, label, limit=500):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('Specify ' + label)
    return value.strip()


def _number(value, label, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Finite numeric ' + label + ' required')
    if positive and value <= 0:
        raise ValueError('Positive ' + label + ' required')
    return float(value)


def _date(value, label):
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError('ISO date required for ' + label) from None


def _validate_data(kind, raw, cutoff):
    if not isinstance(raw, dict):
        raise ValueError('Evidence data must be an object')
    data = dict(raw)
    if kind == 'fundamentals':
        end = _date(data.get('periodEnd'), 'periodEnd')
        if end > cutoff.date():
            raise ValueError('Financial period ends after cutoff')
        days = data.get('periodDays')
        if type(days) is not int or not 1 <= days <= 400:
            raise ValueError('Financial periodDays must be 1–400')
        for key in ('currency', 'unit', 'accountingBasis'):
            data[key] = _text(data.get(key), key, 100)
        metrics = data.get('metrics')
        if not isinstance(metrics, dict):
            raise ValueError('Financial metrics required')
        data['metrics'] = {key: _number(metrics.get(key), key) for key in METRICS}
        if data['metrics']['totalDebt'] < 0 or data['metrics']['cash'] < 0:
            raise ValueError('Debt and cash must be nonnegative')
    elif kind == 'valuation':
        for key in ('price', 'sharesOutstanding'):
            data[key] = _number(data.get(key), key, positive=True)
        data['currency'] = _text(data.get('currency'), 'currency', 100)
        # Statement monetary values are converted using this explicit scale.
        if data.get('unit') not in ('units', 'thousands', 'millions', 'crores'):
            raise ValueError('Valuation unit must match a supported statement unit')
    elif kind == 'benchmark':
        data['name'] = _text(data.get('name'), 'benchmark name', 100)
        start = _date(data.get('periodStart'), 'benchmark periodStart')
        end = _date(data.get('periodEnd'), 'benchmark periodEnd')
        if not start < end <= cutoff.date():
            raise ValueError('Benchmark period is invalid or future')
        data['returnPct'] = _number(data.get('returnPct'), 'benchmark returnPct')
        data['stockReturnPct'] = _number(data.get('stockReturnPct'), 'stockReturnPct')
        if min(data['returnPct'], data['stockReturnPct']) < -100:
            raise ValueError('Unleveraged returns cannot be below -100%')
    elif kind == 'sector':
        data['name'] = _text(data.get('name'), 'sector name', 100)
    else:
        key = 'actions' if kind == 'corporate-actions' else 'flags'
        values = data.get(key)
        if not isinstance(values, list) or len(values) > 100:
            raise ValueError('Bounded ' + key + ' list required')
        data[key] = [_text(value, key, 500) for value in values]
    return data


def _record(raw, cutoff):
    if not isinstance(raw, dict):
        raise ValueError('Evidence record must be an object')
    identity = _text(raw.get('id'), 'evidence id', 128)
    kind = raw.get('kind')
    if kind not in KINDS:
        raise ValueError('Unsupported evidence kind')
    symbol = raw.get('symbol')
    if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z0-9&-]{1,30}', symbol):
        raise ValueError('Exact uppercase symbol required')
    provider = _text(raw.get('provider'), 'provider', 128)
    url = _text(raw.get('url'), 'source URL', 2048)
    try:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        parsed.port
    except ValueError:
        raise ValueError('Source requires HTTPS without embedded credentials') from None
    published = timestamp(raw.get('publishedAt', ''))
    available = timestamp(raw.get('availableAt', ''))
    if max(published, available) > cutoff:
        raise ValueError('Evidence was unavailable at cutoff')
    if cutoff - published > dt.timedelta(days=MAX_AGE_DAYS[kind]):
        raise ValueError('Evidence exceeds ' + str(MAX_AGE_DAYS[kind]) + '-day age policy')
    data = _validate_data(kind, raw.get('data'), cutoff)
    if kind == 'fundamentals' and _date(data['periodEnd'], 'periodEnd') > published.date():
        raise ValueError('Financial results published before their period ended')
    return dict(id=identity, kind=kind, symbol=symbol, provider=provider, url=url,
                publishedAt=published.isoformat(), availableAt=available.isoformat(), data=data)


def _financial_analysis(current, previous):
    metrics = current['data']['metrics']
    ratios = {}
    if metrics['revenue'] > 0:
        ratios['netMarginPct'] = 100 * metrics['netProfit'] / metrics['revenue']
    if metrics['totalEquity'] > 0:
        ratios['debtToEquity'] = metrics['totalDebt'] / metrics['totalEquity']
    if metrics['netProfit'] > 0:
        ratios['operatingCashFlowToProfit'] = metrics['operatingCashFlow'] / metrics['netProfit']
    changes = {}
    if previous:
        for key in METRICS:
            before = previous['data']['metrics'][key]
            value = metrics[key]
            changes[key] = dict(previous=before, current=value, absolute=value-before,
                                percent=100*(value-before)/abs(before) if before else None)
    return dict(periodEnd=current['data']['periodEnd'], periodDays=current['data']['periodDays'],
                currency=current['data']['currency'], unit=current['data']['unit'],
                accountingBasis=current['data']['accountingBasis'], metrics=metrics, ratios=ratios,
                changes=changes, citations=[current['id']] + ([previous['id']] if previous else []))


def research_long_term(request, watchlist):
    """Return factual comparisons. Missing or rejected evidence never becomes a buy."""
    raw = request.get('evidenceRecords', [])
    if not isinstance(raw, list) or len(raw) > 5000:
        raise ValueError('Supply at most 5,000 evidence records')
    if raw and request.get('permitted') is not True:
        raise ValueError('Confirm permission to analyse the imported evidence')
    cutoff = timestamp(request.get('asOf', '')) if raw or request.get('asOf') else None
    records = []
    excluded = []
    seen = {}
    for item in raw:
        try:
            record = _record(item, cutoff)
            if record['id'] in seen:
                if record != seen[record['id']]:
                    raise ValueError('Conflicting duplicate evidence identity')
                continue
            seen[record['id']] = record
            records.append(record)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            excluded.append(dict(id=item.get('id') if isinstance(item, dict) else None,
                                 reason=str(exc)))
    conflicting = {item['id'] for item in excluded if item['reason'] == 'Conflicting duplicate evidence identity'}
    records = [record for record in records if record['id'] not in conflicting]
    cards = []
    for symbol in watchlist:
        relevant = [record for record in records if record['symbol'] == symbol]
        latest = {}
        for kind in KINDS:
            choices = [record for record in relevant if record['kind'] == kind]
            if choices:
                latest[kind] = max(choices, key=lambda r: timestamp(r['availableAt']))
        missing = [kind for kind in KINDS if kind not in latest]
        card = dict(symbol=symbol, exchange='NSE', sector='Unverified', missing=missing,
                    status='Insufficient evidence', autoPurchase=False, sources=relevant,
                    evidence='Imported dated evidence; attribution is caller-supplied.')
        if 'fundamentals' in latest:
            financials = sorted((record for record in relevant if record['kind'] == 'fundamentals'),
                                key=lambda r: (r['data']['periodEnd'], r['availableAt']), reverse=True)
            current = financials[0]
            previous = next((record for record in financials[1:]
                             if record['data']['periodEnd'] < current['data']['periodEnd']
                             and all(record['data'][key] == current['data'][key]
                                     for key in ('periodDays', 'currency', 'unit', 'accountingBasis'))), None)
            card['financials'] = _financial_analysis(current, previous)
            if previous is None:
                missing.append('Comparable prior financial period')
            valuation = latest.get('valuation')
            if valuation:
                fdata = current['data']
                vdata = valuation['data']
                if vdata['currency'] == fdata['currency'] and vdata['unit'] == fdata['unit']:
                    scale = {'units': 1, 'thousands': 1000, 'millions': 1000000, 'crores': 10000000}[vdata['unit']]
                    market_cap = vdata['price'] * vdata['sharesOutstanding'] / scale
                    metrics = fdata['metrics']
                    card['valuation'] = dict(marketCapitalization=market_cap, unit=fdata['unit'],
                                             currency=fdata['currency'], price=vdata['price'],
                                             priceToBook=market_cap/metrics['totalEquity'] if metrics['totalEquity'] > 0 else None,
                                             priceToPeriodEarnings=market_cap/metrics['netProfit'] if metrics['netProfit'] > 0 else None,
                                             periodDays=fdata['periodDays'], citations=[current['id'], valuation['id']])
                else:
                    missing.append('Comparable valuation currency and unit')
        if 'sector' in latest:
            card['sector'] = latest['sector']['data']['name']
        if 'benchmark' in latest:
            data = latest['benchmark']['data']
            card['benchmark'] = dict(data, excessReturnPercentagePoints=data['stockReturnPct']-data['returnPct'],
                                     citations=[latest['benchmark']['id']])
        for kind in ('corporate-actions', 'governance'):
            if kind in latest:
                card[kind] = dict(latest[kind]['data'], citations=[latest[kind]['id']])
        if not missing:
            card['status'] = 'Dated research evidence available'
        cards.append(card)
    return dict(status='Dated research evidence available' if cards and all(not card['missing'] for card in cards)
                else 'Insufficient evidence', horizon='long-term', live=False, candidates=cards,
                asOf=cutoff.isoformat() if cutoff else None, excluded=excluded,
                agePolicyDays=dict(MAX_AGE_DAYS), executionAllowed=False,
                limitations=['Imported sources and financial statements are not independently authenticated.',
                             'Period earnings are not annualized. Negative earnings have no positive P/E.',
                             'Corporate action and governance lists describe supplied evidence, not complete market coverage.',
                             'No intrinsic value, price target or purchase recommendation is inferred.'])
