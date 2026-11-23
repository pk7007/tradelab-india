# Quality and security tooling

| Tool | Where | Policy |
|---|---|---|
| ruff (`E9`,`F`) | CI, pre-commit | Blocking, including unused variables (F841). |
| bandit | CI | Blocks on high severity only (currently 0). Mediums reviewed below. |
| pip-audit | CI | Report only. `kiteconnect` pins an `autobahn` with known advisories. |
| gitleaks, detect-private-key, large-file check | pre-commit (local) | Run `pip install pre-commit && pre-commit install`. Not run in CI. |
| Dependabot | GitHub | Weekly pip and Actions updates. |

## Review outcomes (F841 and bandit mediums)
- F841: all seven were dead code, none hid a bug, so the ignore is removed. `evaluation.py` `slip_rate` and `paper.py` `fee`/`slip` were unused because fills and costs already go through `assumed_fill` with `costBps`/`slippageBps`. `worker_runtime.py` `row` only needed the `_assert` call, which is kept. `render_batch_audit.py` `original` was a load never used in the report. Two test `identity` values were unused. No paper results or behaviour changed.
- Bandit mediums: now 0 unsuppressed. XML in `announcements.py`, `news_agent.py` and `scripts/weekly_digest.py`: the bytes are decoded strictly as UTF-8 (BOM allowed), NUL bytes and invalid UTF-8 are rejected, then a case-insensitive `<!DOCTYPE`/`<!ENTITY` substring check runs on the text, and that text is what is parsed (`# nosec B314` is true only because of this). `announcements.py` and `news_agent.py` already did this check before; `weekly_digest.py` had no check and `announcements.py` checked raw bytes, which UTF-16 input bypassed. Both are fixed with tests (watched failing first) in `tests/test_weekly_digest_safety.py` and `tests/test_announcements.py`. URL opens: `app.py` builds URLs from the fixed https `KITE_API`; `announcements.py` opens the fixed https `FEED` and rejects a different final URL; `weekly_digest.py` now requires an https `feed_url` and an https final URL (`# nosec B310`). SQL: `strategy_lab.py` table is allow-listed; `storage_ops.py` names come from `sqlite_master` and are identifier-quoted (`# nosec B608`). Bandit prints "no failed test" warnings for the multi-line B608 sites; harmless.

## Open items
- `defusedxml` could replace the DOCTYPE/ENTITY pre-checks later; not required now.
- The pre-commit hook versions were not run in this environment.

## Status report (scripts/project_report.py)
Offline Markdown report (--write gives reports/status-YYYY-MM-DD.md, an ignored directory; weekly CI artifact in .github/workflows/status-report.yml). Overall status is PASS only if every present check passes. paper_readiness BLOCKED items are listed with their owner actions and are not failures. A readiness FAIL whose only failing item is the missing kiteconnect package is shown as FAILED (environment) and does not fail the overall status, because the CI report installs only requirements-dev.txt; any other readiness FAIL (live lock, corrupt ledger, worker armed by default) fails the report. The report never rates strategy performance.
