"""Versioned imported-evidence roles. Registry presence is not implementation evidence."""

VERSION = 'evidence-roles-v1'

# Each contract identifies evidence that this family actually requires.
DOMAINS = {
    'instrument-reference': ('symbol', 'exchange', 'instrumentToken'),
    'exchange-calendar': ('sessionDate', 'open', 'close'),
    'quote-observations': ('symbol', 'bid', 'ask'),
    'historical-candles': ('symbol', 'open', 'high', 'low', 'close', 'volume'),
    'corporate-actions': ('symbol', 'action', 'effectiveDate'),
    'news-ingestion': ('symbol', 'headline', 'url'),
    'event-entity-mapping': ('symbol', 'entity', 'eventType'),
    'earnings-disclosures': ('symbol', 'period', 'revenue', 'profit'),
    'fundamental-statements': ('symbol', 'period', 'revenue', 'debt', 'cash'),
    'financial-ratios': ('symbol', 'ratio', 'value'),
    'valuation-assumptions': ('symbol', 'method', 'value'),
    'governance-evidence': ('symbol', 'finding', 'filing'),
    'sector-classification': ('symbol', 'sector', 'classificationVersion'),
    'benchmark-data': ('benchmark', 'close'),
    'technical-indicators': ('symbol', 'indicator', 'value', 'period'),
    'momentum-relative-strength': ('symbol', 'returnPct', 'benchmarkReturnPct'),
    'market-regimes': ('benchmark', 'regime', 'ruleVersion'),
    'liquidity-spreads': ('symbol', 'bid', 'ask', 'volume'),
    'transaction-costs': ('symbol', 'fee', 'slippage', 'quantity'),
    'position-sizing': ('symbol', 'quantity', 'price', 'capital'),
    'trade-risk': ('symbol', 'entry', 'stop', 'quantity', 'maxLoss'),
    'portfolio-exposure': ('symbol', 'exposure', 'limit'),
    'backtest-execution': ('strategyVersion', 'returnPct', 'maxDrawdownPct'),
    'statistical-validation': ('experiment', 'sampleSize', 'confidenceLower'),
    'benchmark-evaluation': ('experiment', 'strategyReturnPct', 'benchmarkReturnPct'),
    'performance-attribution': ('strategyVersion', 'realized', 'fees'),
    'strategy-versioning': ('strategyVersion', 'datasetHash', 'state'),
    'paper-execution': ('account', 'symbol', 'side', 'quantity', 'price'),
    'order-position-reconciliation': ('account', 'symbol', 'expectedQuantity', 'observedQuantity'),
    'recovery-persistence': ('account', 'backupHash', 'restoreVerified'),
    'operations-security': ('service', 'state', 'errorCount'),
    'application-reporting': ('journey', 'state', 'latencyMs'),
}

RESPONSIBILITIES = (
    'intake', 'normalization', 'schema-validation', 'source-validation',
    'availability-validation', 'completeness', 'duplicate-revision-handling',
    'feature-calculation', 'analysis', 'anomaly-detection', 'evidence-preparation',
    'scenario-testing', 'baseline-comparison', 'independent-review', 'monitoring', 'reporting',
)

# These responsibilities have distinct bounded implementations for every domain.
# More specialized domain calculations must earn their own acceptance evidence.
IMPLEMENTED_RESPONSIBILITIES = frozenset(RESPONSIBILITIES)


def registry():
    roles = []
    for domain, fields in DOMAINS.items():
        for responsibility in RESPONSIBILITIES:
            roles.append(dict(
                id=f'{domain}.{responsibility}', family=domain,
                responsibility=responsibility, version=VERSION,
                task=f'{responsibility} for {domain} records containing {", ".join(fields)}',
                inputContract=dict(records='1–1000 permitted records', requiredFields=list(fields),
                                   provenance=['id', 'source', 'observedAt', 'availableAt']),
                outputContract='Bounded deterministic evidence findings and source lineage',
                permissions=['research-only'],
                dependencies=['permitted attributed evidence', 'task evidence cutoff'],
                failureBehavior='Explicit insufficient evidence or rejected invalid record',
                acceptance=f'Validate {responsibility} against {domain} contract fixtures',
                implemented=responsibility in IMPLEMENTED_RESPONSIBILITIES,
            ))
    return roles
