# Verification record · 20 November 2026

| Check | Before | After | Evidence |
|---|---:|---:|---|
| Python test discovery | 317 passed | 320 passed | Final local run completed in 17.619 seconds. Includes news, research, ledger, worker and risk tests. |
| JavaScript test files | 6 passed | 6 passed | Account display, stale previews, worker controls, risk limit changes and research distinctions. |
| Portal script syntax | — | Passed | Node parsed the edited dashboard script. |
| Local HTTP recovery | Passed | Passed | Isolated paper account restarted paused, rejected a missing bar, skipped two overlapping and five retransmitted bars, reconstructed one fixture fill and matched dashboard equity. Live orders zero. |

Run from the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
$files = @(Get-ChildItem tests -Filter '*.test.js' | ForEach-Object FullName)
node --test $files
node --check web/portal.js
.\.venv\Scripts\python.exe -B scripts/fixture_recovery.py
```

One intermediate Python run exposed a historical tracking-link fixture that supplied no receipt time. The fixture now states when its article was observed. Repeated links representing the same revision still combine issuer tags. Separate regression cases check that a missing historical receipt is excluded and a subsequent correction removing a symbol takes effect in either input order.

The dashboard fixtures test collection without a page, nonblocking reads during provider I/O, repeated reads during a single interval, startup and shutdown, provider failures with and without retry instructions, recovery, ambiguous issuer mapping and related story identities. The benchmark and source-health observations are in the [news audit](feature-audit-latest.md). The measured paper balance comes from generated prices. Market-session uptime, broker execution, licensed production feeds and future returns require separate evidence.
