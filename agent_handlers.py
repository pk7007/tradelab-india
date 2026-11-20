"""Pure imported-evidence processing and isolated subprocess entry point."""
import hashlib
import json
import math
import statistics
import sys
from urllib.parse import urlsplit

from agent_catalog import DOMAINS, IMPLEMENTED_RESPONSIBILITIES
from research import timestamp

LEGACY = {'strategy-research.analysis': 'scan', 'portfolio-risk.validation': 'risk',
          'backtesting.analysis': 'evaluate'}
NUMERIC_FIELDS = frozenset({'instrumentToken', 'bid', 'ask', 'open', 'high', 'low',
    'close', 'volume', 'revenue', 'profit', 'debt', 'cash', 'value', 'period',
    'returnPct', 'benchmarkReturnPct', 'fee', 'slippage', 'quantity', 'price',
    'capital', 'entry', 'stop', 'maxLoss', 'exposure', 'limit', 'maxDrawdownPct',
    'sampleSize', 'confidenceLower', 'strategyReturnPct', 'realized', 'fees',
    'expectedQuantity', 'observedQuantity', 'errorCount', 'latencyMs'})


def encode(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def supported(capability):
    if capability in LEGACY:
        return True
    domain, separator, responsibility = capability.partition('.')
    return bool(separator and domain in DOMAINS and responsibility in IMPLEMENTED_RESPONSIBILITIES)


def validate_records(payload, cutoff, domain):
    if payload.get('permitted') is not True:
        raise ValueError('Explicit local evidence permission required.')
    records = payload.get('records')
    if not isinstance(records, list) or not 1 <= len(records) <= 1000:
        raise ValueError('Supply 1–1000 records.')
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get('id'), str) or not record['id'].strip():
            raise ValueError('Every record needs an identity.')
        if any(key not in record for key in DOMAINS[domain]):
            raise ValueError('Domain fields missing.')
        source = record.get('source')
        if not isinstance(source, str) or not source.strip():
            raise ValueError('Evidence source required.')
        if source.startswith(('http:', 'https:')):
            parsed = urlsplit(source)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('Unsafe source address.')
        observed = timestamp(record.get('observedAt', ''))
        available = timestamp(record.get('availableAt', ''))
        if max(observed, available) > cutoff:
            raise ValueError('Future evidence excluded.')
        for value in record.values():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isfinite(value):
                raise ValueError('Non-finite evidence value.')
        for field in DOMAINS[domain]:
            textual_period = field == 'period' and domain in ('earnings-disclosures', 'fundamental-statements')
            calendar_time = field in ('open', 'close') and domain == 'exchange-calendar'
            if field in NUMERIC_FIELDS and not (textual_period or calendar_time):
                if type(record[field]) not in (int, float) or not math.isfinite(record[field]):
                    raise ValueError('Numeric domain field required.')
    return records


def features(domain, records):
    """Calculate explicit domain quantities from supplied observations."""
    rows = []
    def ratio(numerator, denominator):
        return numerator / denominator if denominator else None
    for record in records:
        row = dict(id=record['id'])
        if domain == 'instrument-reference':
            row.update(mapped=record['exchange'] == 'NSE' and record['instrumentToken'] > 0)
        elif domain == 'exchange-calendar':
            start, end = timestamp(record['open']), timestamp(record['close'])
            row.update(sessionMinutes=(end-start).total_seconds()/60, sameDate=start.date()==end.date())
        elif domain in ('quote-observations', 'liquidity-spreads'):
            row.update(spread=record['ask']-record['bid'], spreadPct=ratio(100*(record['ask']-record['bid']), record['ask']))
        elif domain == 'historical-candles':
            row.update(returnPct=100*(record['close']/record['open']-1) if record['open'] else None,
                       range=record['high']-record['low'], turnoverProxy=record['close']*record['volume'])
        elif domain == 'corporate-actions':
            row.update(action=record['action'], effectiveAfterObservation=str(record['effectiveDate']) >= record['observedAt'][:10])
        elif domain == 'news-ingestion':
            row.update(headlineCharacters=len(str(record['headline'])), symbol=record['symbol'], sourceUrl=record['url'])
        elif domain == 'event-entity-mapping':
            linked = {r['symbol'] for r in records if r['entity'] == record['entity']}
            row.update(entity=record['entity'], ambiguous=len(linked)>1, symbols=sorted(linked))
        elif domain == 'earnings-disclosures':
            row.update(netMargin=ratio(record['profit'], record['revenue']))
        elif domain == 'fundamental-statements':
            row.update(netDebt=record['debt']-record['cash'], debtToRevenue=ratio(record['debt'], record['revenue']))
        elif domain == 'financial-ratios':
            row.update(ratio=record['ratio'], value=record['value'], positive=record['value']>0)
        elif domain == 'valuation-assumptions':
            row.update(method=record['method'], positiveValuation=record['value']>0, assumedValue=record['value'])
        elif domain == 'governance-evidence':
            row.update(finding=record['finding'], attributed=bool(record['filing']), unresolved=True)
        elif domain == 'sector-classification':
            row.update(sector=record['sector'], classifiedShare=sum(r['sector']==record['sector'] for r in records)/len(records))
        elif domain == 'benchmark-data':
            previous = next((r for r in records if r['benchmark']==record['benchmark']), record)
            row.update(returnFromFirstPct=100*(record['close']/previous['close']-1) if previous['close'] else None)
        elif domain == 'technical-indicators':
            row.update(indicator=record['indicator'], configuredPeriod=record['period'], observedValue=record['value'])
        elif domain == 'momentum-relative-strength':
            row.update(excessReturnPct=record['returnPct']-record['benchmarkReturnPct'])
        elif domain == 'market-regimes':
            row.update(regime=record['regime'], classificationShare=sum(r['regime']==record['regime'] for r in records)/len(records))
        elif domain == 'transaction-costs':
            row.update(totalModeledCost=record['fee']+record['slippage'], costPerUnit=ratio(record['fee']+record['slippage'], record['quantity']))
        elif domain == 'position-sizing':
            value=record['quantity']*record['price']
            row.update(notional=value, capitalUtilization=ratio(value, record['capital']), fitsCapital=0<=value<=record['capital'])
        elif domain == 'trade-risk':
            loss=record['quantity']*(record['entry']-record['stop'])
            row.update(plannedPriceRisk=loss, withinPriceRiskAllowance=0<=loss<=record['maxLoss'], costsIncluded=False)
        elif domain == 'portfolio-exposure':
            row.update(utilization=ratio(record['exposure'], record['limit']), withinLimit=0<=record['exposure']<=record['limit'])
        elif domain == 'backtest-execution':
            row.update(returnToDrawdown=ratio(record['returnPct'], record['maxDrawdownPct']))
        elif domain == 'statistical-validation':
            row.update(positiveLowerBound=record['confidenceLower']>0, sampleSize=record['sampleSize'], calibrationVerified=False)
        elif domain == 'benchmark-evaluation':
            row.update(excessReturnPct=record['strategyReturnPct']-record['benchmarkReturnPct'])
        elif domain == 'performance-attribution':
            row.update(netRealized=record['realized'], grossBeforeFees=record['realized']+record['fees'])
        elif domain == 'strategy-versioning':
            row.update(version=record['strategyVersion'], datasetHash=record['datasetHash'], state=record['state'], promotionAllowed=False)
        elif domain == 'paper-execution':
            if record['side'] not in ('BUY', 'SELL'):
                raise ValueError('Unsupported paper side.')
            row.update(signedNotional=record['quantity']*record['price']*(1 if record['side']=='BUY' else -1), modeled=True)
        elif domain == 'order-position-reconciliation':
            difference=record['observedQuantity']-record['expectedQuantity']
            row.update(quantityDifference=difference, matches=difference==0)
        elif domain == 'recovery-persistence':
            if type(record['restoreVerified']) is not bool:
                raise ValueError('Explicit Boolean restore result required.')
            row.update(restoreEvidencePresent=bool(record['backupHash']), restoreReportedVerified=record['restoreVerified'])
        elif domain == 'operations-security':
            row.update(healthy=record['state']=='healthy' and record['errorCount']==0, errorCount=record['errorCount'])
        elif domain == 'application-reporting':
            row.update(journey=record['journey'], latencyMs=record['latencyMs'], completed=record['state']=='complete')
        rows.append(row)
    return dict(features=rows, scope='Imported domain features; source truth remains unverified')


def evidence_task(capability, payload, cutoff):
    domain, responsibility = capability.split('.')
    records = validate_records(payload, cutoff, domain)
    fields = DOMAINS[domain]
    latest = {}
    for record in records:
        if record['id'] not in latest or timestamp(record['availableAt']) > timestamp(latest[record['id']]['availableAt']):
            latest[record['id']] = record
    selected = sorted(latest.values(), key=lambda record: record['id'])
    common = dict(domain=domain, responsibility=responsibility, recordCount=len(records),
                  uniqueRecords=len(selected), evidenceHash=digest(records), executionAllowed=False)
    if responsibility == 'intake':
        result = dict(acceptedIds=[record['id'] for record in selected])
    elif responsibility == 'normalization':
        result = dict(records=[{**record, 'observedAt': timestamp(record['observedAt']).isoformat(),
                                'availableAt': timestamp(record['availableAt']).isoformat()} for record in selected])
    elif responsibility == 'schema-validation':
        result = dict(valid=True, checkedFields=list(fields))
    elif responsibility == 'source-validation':
        result = dict(sources=sorted({record['source'] for record in selected}), providerTruthVerified=False)
    elif responsibility == 'availability-validation':
        result = dict(cutoff=cutoff.isoformat(), latestAvailableAt=max(timestamp(r['availableAt']) for r in selected).isoformat())
    elif responsibility == 'completeness':
        missing = [{ 'id': r['id'], 'fields': [key for key in fields if r[key] in (None, '')]} for r in selected]
        result = dict(complete=not any(r['fields'] for r in missing), missing=missing)
    elif responsibility == 'duplicate-revision-handling':
        result = dict(records=selected, removedCount=len(records)-len(selected))
    elif responsibility == 'analysis':
        summaries = {}
        for field in fields:
            values = [r[field] for r in selected if type(r[field]) in (int, float)]
            if values:
                summaries[field] = dict(min=min(values), max=max(values), mean=statistics.mean(values))
        result = dict(numericSummary=summaries, scope='Descriptive imported evidence')
    elif responsibility == 'feature-calculation':
        result = features(domain, selected)
    elif responsibility == 'scenario-testing':
        # Contract/data sensitivity only. These scenarios never claim market outcomes.
        base = features(domain, selected)
        stressed = [dict(record) for record in selected]
        numeric = [key for key in fields if key in NUMERIC_FIELDS and all(type(r[key]) in (int, float) for r in stressed)]
        for record in stressed:
            for key in numeric:
                record[key] *= 1.1
        result = dict(baseline=base, scenario=features(domain, stressed),
                      missingLastObservation=features(domain, selected[:-1]),
                      perturbation='Numeric fields multiplied by1.1 and last observation removed in separate scenarios',
                      scenarioType='Imported-feature sensitivity', changedFields=numeric,
                      scenarioHash=digest(stressed), marketOutcomeSimulation=False)
    elif responsibility == 'anomaly-detection':
        conflicts = [r['id'] for r in selected if any(r[key] is None for key in fields)]
        if domain in ('quote-observations', 'liquidity-spreads'):
            conflicts.extend(r['id'] for r in selected if r['bid'] > r['ask'])
        if domain == 'order-position-reconciliation':
            conflicts.extend(r['id'] for r in selected if r['expectedQuantity'] != r['observedQuantity'])
        result = dict(flaggedIds=sorted(set(conflicts)))
    elif responsibility == 'evidence-preparation':
        result = dict(citations=[dict(id=r['id'], source=r['source'], observedAt=r['observedAt'], availableAt=r['availableAt'], fingerprint=digest(r)) for r in selected])
    elif responsibility == 'baseline-comparison':
        baseline = payload.get('baseline')
        if not isinstance(baseline, list):
            raise ValueError('Baseline records required.')
        checked = validate_records(dict(permitted=True, records=baseline), cutoff, domain)
        old = {r['id']: digest(r) for r in checked}
        result = dict(changedIds=[r['id'] for r in selected if old.get(r['id']) != digest(r)], baselineHash=digest(checked))
    elif responsibility == 'independent-review':
        subject = payload.get('subject')
        if not isinstance(subject, dict) or subject.get('capability') == capability:
            raise ValueError('Independent subject required.')
        if subject.get('capability') != domain+'.analysis':
            raise ValueError('This reviewer verifies domain descriptive analysis only.')
        expected = evidence_task(domain+'.analysis', dict(permitted=True, records=records), cutoff)
        result = dict(matches=encode(expected) == encode(subject.get('output')), expectedHash=digest(expected))
    elif responsibility == 'monitoring':
        max_age = payload.get('maxAgeSeconds')
        if type(max_age) is not int or max_age < 1:
            raise ValueError('Positive freshness budget required.')
        result = dict(staleIds=[r['id'] for r in selected if (cutoff-timestamp(r['observedAt'])).total_seconds() > max_age])
    else:
        result = dict(status='Imported evidence available', ids=[r['id'] for r in selected], fields=list(fields), limitations=['Source accuracy and investment implications require separate verification.'])
    return dict(**common, **result)


def execute(capability, envelope):
    if not supported(capability):
        raise ValueError('Unimplemented capability.')
    payload = envelope['input']
    cutoff = timestamp(envelope['evidenceCutoff'])
    if 'asOf' in payload and timestamp(payload['asOf']) != cutoff:
        raise ValueError('Research and task cutoffs differ.')
    handler = LEGACY.get(capability)
    if handler == 'scan':
        from trader_suite import scan
        return scan(payload)
    if handler == 'risk':
        from trader_suite import risk_check
        return risk_check(payload)
    if handler == 'evaluate':
        from evaluation import evaluate
        return evaluate(payload)
    return evidence_task(capability, payload, cutoff)


if __name__ == '__main__':
    try:
        request = json.loads(sys.stdin.read(70000))
        result = dict(ok=True, output=execute(request['capability'], request['envelope']))
        encoded = encode(result)
        if len(encoded.encode()) > 200000:
            raise ValueError('Output exceeds bound.')
        print(encoded)
    except Exception as exc:
        print(encode(dict(ok=False, errorType=type(exc).__name__)))
