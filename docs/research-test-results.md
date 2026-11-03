# Offline research test results

Executed: 2026-11-03T17:07:39.395912+00:00
Command: `.\.venv\Scripts\python.exe scripts/check_research.py`
Fixtures: synthetic OHLCV, seeded synthetic paths, and in-memory mock job/order state only. No live account operations.
Expected for each test: the named invariant holds under the fixtures and assertions in its linked test function.
Actual results below. Excluded/not-run integration scenarios are listed in [implementation status](research-implementation.md).

| Test / expected invariant | Fixture source | Actual | Status |
| --- | --- | --- | --- |
| ambiguous acceptance faults without retry | [AutomationTests](../tests/test_automation.py) | All assertions passed | PASS |
| config requires explicit limits | [AutomationTests](../tests/test_automation.py) | All assertions passed | PASS |
| crash during submission recovers unknown | [AutomationTests](../tests/test_automation.py) | All assertions passed | PASS |
| duplicate concurrent signal creates one intent | [AutomationTests](../tests/test_automation.py) | All assertions passed | PASS |
| external position mismatch faults | [AutomationTests](../tests/test_automation.py) | All assertions passed | PASS |
| partial fills cannot regress | [AutomationTests](../tests/test_automation.py) | All assertions passed | PASS |
| pending exposure blocks addition | [AutomationTests](../tests/test_automation.py) | All assertions passed | PASS |
| public start cannot arm | [AutomationTests](../tests/test_automation.py) | All assertions passed | PASS |
| real adapter rejected | [AutomationTests](../tests/test_automation.py) | All assertions passed | PASS |
| stale loss mismatch margin and session block | [AutomationTests](../tests/test_automation.py) | All assertions passed | PASS |
| stop does not fake cancellation or closure | [AutomationTests](../tests/test_automation.py) | All assertions passed | PASS |
| unknown missing from snapshot stays blocked | [AutomationTests](../tests/test_automation.py) | All assertions passed | PASS |
| versions persist and restart disarms | [AutomationTests](../tests/test_automation.py) | All assertions passed | PASS |
| candles deduplicate sort and validate | [HistoricalTests](../tests/test_market_data.py) | All assertions passed | PASS |
| invalid ranges rejected | [HistoricalTests](../tests/test_market_data.py) | All assertions passed | PASS |
| jobs are private and payload bounded | [HistoricalTests](../tests/test_market_data.py) | All assertions passed | PASS |
| storage gate prevents network and disk | [HistoricalTests](../tests/test_market_data.py) | All assertions passed | PASS |
| stream state not shared | [HistoricalTests](../tests/test_market_data.py) | All assertions passed | PASS |
| windows cover range once | [HistoricalTests](../tests/test_market_data.py) | All assertions passed | PASS |
| demo deterministic and validates inputs | [StrategyTests](../tests/test_market_data.py) | All assertions passed | PASS |
| no future signal executes on final bar | [StrategyTests](../tests/test_market_data.py) | All assertions passed | PASS |
| signal executes on next open | [StrategyTests](../tests/test_market_data.py) | All assertions passed | PASS |
| ambiguous submission cannot replay | [OrderTests](../tests/test_orders.py) | All assertions passed | PASS |
| expired or changed review blocked | [OrderTests](../tests/test_orders.py) | All assertions passed | PASS |
| fraction boolean and nonfinite quantity rejected | [OrderTests](../tests/test_orders.py) | All assertions passed | PASS |
| host header rejects rebinding | [OrderTests](../tests/test_orders.py) | All assertions passed | PASS |
| stop limit direction validated | [OrderTests](../tests/test_orders.py) | All assertions passed | PASS |
| unreviewed order cannot submit | [OrderTests](../tests/test_orders.py) | All assertions passed | PASS |
| bad prices and zero volume rejected | [RankingTests](../tests/test_research.py) | All assertions passed | PASS |
| decline produces no candidate | [RankingTests](../tests/test_research.py) | All assertions passed | PASS |
| duplicate and out of order rejected | [RankingTests](../tests/test_research.py) | All assertions passed | PASS |
| experiment hash changes with data | [RankingTests](../tests/test_research.py) | All assertions passed | PASS |
| future information does not change rank | [RankingTests](../tests/test_research.py) | All assertions passed | PASS |
| intraday requires complete contiguous session | [RankingTests](../tests/test_research.py) | All assertions passed | PASS |
| long term is blocked without fundamentals | [RankingTests](../tests/test_research.py) | All assertions passed | PASS |
| positive rank has exact contribution | [RankingTests](../tests/test_research.py) | All assertions passed | PASS |
| purge prevents label overlap | [RankingTests](../tests/test_research.py) | All assertions passed | PASS |
| ranking job owner and completion gate | [RankingTests](../tests/test_research.py) | All assertions passed | PASS |
| stale daily rejected | [RankingTests](../tests/test_research.py) | All assertions passed | PASS |
| duplicate rejected | [RiskContractTests](../tests/test_research.py) | All assertions passed | PASS |
| kill does not claim closed positions | [RiskContractTests](../tests/test_research.py) | All assertions passed | PASS |
| restart disarms | [RiskContractTests](../tests/test_research.py) | All assertions passed | PASS |
| stale unreconciled pending and daily loss gates | [RiskContractTests](../tests/test_research.py) | All assertions passed | PASS |
| unknown acceptance blocks resubmit | [RiskContractTests](../tests/test_research.py) | All assertions passed | PASS |
| explicit approval and no replay | [PaperApprovalTests](../tests/test_trader_suite.py) | All assertions passed | PASS |
| scans two thousand synthetic symbols | [PaperApprovalTests](../tests/test_trader_suite.py) | All assertions passed | PASS |
| budget bounds units by risk | [TraderSuiteTests](../tests/test_trader_suite.py) | All assertions passed | PASS |
| costs reduce quantity | [TraderSuiteTests](../tests/test_trader_suite.py) | All assertions passed | PASS |
| disclosure preserves owner and lag | [TraderSuiteTests](../tests/test_trader_suite.py) | All assertions passed | PASS |
| earnings zero base has no percentage | [TraderSuiteTests](../tests/test_trader_suite.py) | All assertions passed | PASS |
| future incomplete bar excluded | [TraderSuiteTests](../tests/test_trader_suite.py) | All assertions passed | PASS |
| invalid long plan and nan rejected | [TraderSuiteTests](../tests/test_trader_suite.py) | All assertions passed | PASS |
| news deduplicates and matches exact symbol | [TraderSuiteTests](../tests/test_trader_suite.py) | All assertions passed | PASS |
| orb uses complete opening window | [TraderSuiteTests](../tests/test_trader_suite.py) | All assertions passed | PASS |
| pending exposure and daily loss block | [TraderSuiteTests](../tests/test_trader_suite.py) | All assertions passed | PASS |
| price alert boundary | [TraderSuiteTests](../tests/test_trader_suite.py) | All assertions passed | PASS |
| scanner requires permission | [TraderSuiteTests](../tests/test_trader_suite.py) | All assertions passed | PASS |
| time machine runs 10000 reproducibly | [TraderSuiteTests](../tests/test_trader_suite.py) | All assertions passed | PASS |
| zero size cannot pass risk | [TraderSuiteTests](../tests/test_trader_suite.py) | All assertions passed | PASS |
| costs reduce equity for same fills | [ExecutionTests](../tests/test_validation_lab.py) | All assertions passed | PASS |
| delay defers first fill | [ExecutionTests](../tests/test_validation_lab.py) | All assertions passed | PASS |
| gap stop fills below stop | [ExecutionTests](../tests/test_validation_lab.py) | All assertions passed | PASS |
| halt prevents fills | [ExecutionTests](../tests/test_validation_lab.py) | All assertions passed | PASS |
| next bar signal and cash reconciliation | [ExecutionTests](../tests/test_validation_lab.py) | All assertions passed | PASS |
| partial fills respect participation | [ExecutionTests](../tests/test_validation_lab.py) | All assertions passed | PASS |
| rejection never changes cash | [ExecutionTests](../tests/test_validation_lab.py) | All assertions passed | PASS |
| stress suite has losses and all variants | [ExecutionTests](../tests/test_validation_lab.py) | All assertions passed | PASS |
