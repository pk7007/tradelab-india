# Quality and security tooling

| Tool | Where | Policy |
|---|---|---|
| ruff (`E9`,`F`) | CI, pre-commit | Blocking. Unused-variable findings (F841) are ignored for now; see below. |
| bandit | CI | Blocks on high severity only (currently 0). Mediums reviewed below. |
| pip-audit | CI | Report only. `kiteconnect` pins an `autobahn` with known advisories. |
| gitleaks, detect-private-key, large-file check | pre-commit (local) | Run `pip install pre-commit && pre-commit install`. Not run in CI. |
| Dependabot | GitHub | Weekly pip and Actions updates. |

## Open items
- F841 unused locals: `evaluation.py:96`, `paper.py:487`, `worker_runtime.py:55`, two scripts and tests. Check whether any hides a bug.
- Bandit mediums: XML parsing in `announcements.py`, `news_agent.py`, `scripts/weekly_digest.py` (DOCTYPE/ENTITY already rejected; consider `defusedxml`); URL opens in `app.py` and scripts; string-built SQL in `storage_ops.py:24` and `strategy_lab.py:185` (confirm table names are fixed constants).
- The pre-commit hook versions were not run in this environment.
