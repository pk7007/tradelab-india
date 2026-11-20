# Implementation progress · 20 November 2026

| Workflow | Before | After | Status and evidence |
|---|---|---|---|
| Scheduled collection | HTTP reads could initiate slow provider calls | The local server owns a collector. Portal and paper research read snapshots. | Verified in a single process with a blocked provider and a closed dashboard. Separate app or CLI processes can still duplicate requests. |
| Source outages | Failed-source history disappeared from view | Cached items are separated from eligible research. UI shows last success and next check. | Tested failure, backoff and recovery, including a provider retry delay. |
| Evidence attribution | Source URL, timestamps and keyword labels | Exact story groups, publisher, disclosure/editorial type, revision status and classification version | Distinct evidence records are retained. Matching titles do not establish independent corroboration. |
| Historical import | Missing receipt could stand in for evidence known at a historical cutoff | Historical views require availability. Latest eligible corrections are applied before filtering watchlist symbols. | Tested late receipts, duplicate links, missing receipts and changed issuer tags. |
| RSS input | Multiple parser entry points with byte-level declaration checks | All three sources first validate bounded UTF-8 RSS and reject unsupported declarations | Valid inputs and unsupported encoding checks pass in the local suite. |
| Paper and live operation | Existing paper accounting and broker controls | This release changes the context supplied to research | Isolated HTTP restart and ledger reconciliation passed. Deployment and forward-market observation remain pending. |

See the [feature inventory](feature-gap-matrix.md), [news ratings](feature-audit-latest.md), [test results](feature-test-results.md) and [ten ranked remaining gaps](remaining-feature-roadmap.md). The next operational milestone is to deploy outside an active paper session and collect dated receipt, failure and eligible-research counts through market sessions and a restart. Use those records to assess availability before comparing paper results with and without news context.
