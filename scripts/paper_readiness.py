"""Offline paper-trading readiness preflight for TradeLab India.

No network access, no broker login, no secret values: variable NAMES only. The real
paper ledger is only read from a temporary copy. Exit status is 1 only when a check
FAILS; BLOCKED items need an owner action (login, credentials, approval, market hours).

Stop the app before running it so the ledger copy is consistent.

--json shape (consumed by scripts/project_report.py):
  {"generatedAt": ISO time, "istDate": "YYYY-MM-DD", "ok": bool (no FAIL),
   "counts": {"FAIL": n, "BLOCKED": n, "PASS": n},
   "checks": [{"id", "title", "status": "PASS|FAIL|BLOCKED", "detail", "ownerAction"}]}
"""
import argparse
import ast
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
IST = dt.timezone(dt.timedelta(hours=5, minutes=30), 'IST')
PLACEHOLDER_SUFFIX = '_here'
REQUIRED = ('KITE_API_KEY', 'KITE_API_SECRET')
OPTIONAL = ('KITE_REDIRECT_URL',)
SECRET_PREFIXES = ('KITE_', 'ANTHROPIC_', 'SYNDICATION_')
ORDER = {'FAIL': 0, 'BLOCKED': 1, 'PASS': 2}


def check(cid, title, status, detail, action=''):
    return dict(id=cid, title=title, status=status, detail=detail, ownerAction=action)


def read_dotenv(path):
    """Parse KEY=VALUE like app.load_dotenv (environment wins)."""
    values = {}
    try:
        text = Path(path).read_text(encoding='utf-8')
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('"\'')
    return values


class Env:
    """Merged environment and .env. Values stay private to this object."""

    def __init__(self, environ, dotenv):
        self.environ, self.dotenv = dict(environ), dict(dotenv)

    def value(self, name):
        return self.environ.get(name, self.dotenv.get(name, ''))

    def usable(self, name):
        value = self.value(name).strip()
        return bool(value) and not value.endswith(PLACEHOLDER_SUFFIX)

    def where(self, name):
        found = [label for label, src in (('environment', self.environ), ('.env', self.dotenv)) if src.get(name, '').strip()]
        return '+'.join(found) or 'unset'

    def flag(self, name):
        return self.value(name).strip().lower() == 'true'


def live_lock(project_root, env):
    flag = env.flag('TRADELAB_ENABLE_LIVE_ORDERS')
    try:
        tree = ast.parse((Path(project_root) / 'app.py').read_text(encoding='utf-8'))
    except (OSError, SyntaxError, ValueError) as exc:
        return check('live-lock', 'Live execution locked', 'FAIL', 'Cannot read app.py (%s).' % type(exc).__name__,
                     'Restore app.py; do not run the app until the lock can be verified.')
    found = [n.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == 'LIVE_EXECUTION_READY' for t in n.targets)]
    if len(found) != 1 or not isinstance(found[0], ast.Constant) or found[0].value is not False:
        return check('live-lock', 'Live execution locked', 'FAIL',
                     'LIVE_EXECUTION_READY is not a single literal False in app.py; live ordering may not be locked.',
                     'Restore LIVE_EXECUTION_READY = False in app.py before running anything.')
    note = ('TRADELAB_ENABLE_LIVE_ORDERS is set to true but ineffective: the flag alone cannot enable orders.'
            if flag else 'TRADELAB_ENABLE_LIVE_ORDERS is not true.')
    return check('live-lock', 'Live execution locked', 'PASS', 'LIVE_EXECUTION_READY is False (locked). ' + note)


def credentials(env):
    missing = [n for n in REQUIRED if not env.usable(n)]
    present = ['%s (%s)' % (n, env.where(n)) for n in REQUIRED if env.usable(n)]
    optional = ['%s (%s)' % (n, env.where(n)) for n in OPTIONAL if env.where(n) != 'unset']
    detail = 'Present: %s. Missing or placeholder: %s. Optional set: %s. Names only; values never read out.' % (
        ', '.join(present) or 'none', ', '.join(missing) or 'none', ', '.join(optional) or 'none (default redirect URL applies)')
    if missing:
        return check('kite-credentials', 'Kite variable names', 'BLOCKED', detail,
                     'Owner: put %s from your own Kite developer app in .env (see .env.example). Never paste them into chat.' % ' and '.join(missing))
    return check('kite-credentials', 'Kite variable names', 'PASS', detail)


def sdk():
    try:
        found = importlib.util.find_spec('kiteconnect') is not None
    except (ImportError, ValueError):
        found = False
    if found:
        return check('kiteconnect', 'kiteconnect importable', 'PASS', 'kiteconnect SDK is installed.')
    return check('kiteconnect', 'kiteconnect importable', 'FAIL', 'kiteconnect is not importable.',
                 'Run: python -m pip install -r requirements.txt (inside your project virtual environment).')


def data_dir(env, project_root):
    configured = env.value('TRADELAB_DATA_DIR').strip()
    base = Path(env.value('LOCALAPPDATA').strip() or Path(project_root) / 'data' / 'private')
    target = Path(configured) if configured else base / 'TradeLabIndia' / 'market-data'
    probe = target
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        if probe.is_dir() and probe == target:
            with tempfile.TemporaryFile(dir=probe):
                pass
            return check('data-dir', 'Private data directory writable', 'PASS', 'Directory exists and accepts files: %s' % target)
        if probe.is_dir() and os.access(probe, os.W_OK | os.X_OK):
            return check('data-dir', 'Private data directory writable', 'PASS', 'Will be created on first save under writable %s.' % probe)
    except OSError:
        pass
    return check('data-dir', 'Private data directory writable', 'FAIL', 'Not writable or not creatable: %s' % target,
                 'Choose a folder you control and set TRADELAB_DATA_DIR in .env.')


def worker_default():
    sys.path.insert(0, str(ROOT))
    try:
        from paper import PaperEngine
        from paper_worker import PaperWorker
        with tempfile.TemporaryDirectory(prefix='readiness-') as tmp:
            status = PaperWorker(PaperEngine(Path(tmp) / 'probe.sqlite'), lambda *a: []).status()
    except Exception as exc:  # report, never crash the checklist
        return check('worker-default', 'Worker disarmed by default', 'FAIL', 'Could not construct the worker (%s).' % type(exc).__name__)
    if status.get('state') == 'disarmed' and status.get('enabled') is False and status.get('live') is False:
        return check('worker-default', 'Worker disarmed by default', 'PASS',
                     'A fresh PaperWorker reports state=disarmed, enabled=False, live=False (observed-candle paper only).')
    return check('worker-default', 'Worker disarmed by default', 'FAIL', 'Fresh worker status is %s.' % status.get('state'))


def paper_ledger(env, project_root, now):
    """Return (checks, intraday_configs). Reads only a temporary copy."""
    configured = env.value('TRADELAB_PAPER_DB').strip()
    base = Path(env.value('LOCALAPPDATA').strip() or Path(project_root) / 'data' / 'private')
    path = Path(configured) if configured else base / 'TradeLabIndia' / 'paper.sqlite'
    if not path.is_file():
        return [check('paper-db', 'Paper database integrity', 'PASS', 'No ledger at %s yet; the app creates it on first start.' % path),
                check('ledger-lease', 'No active worker lease in ledger', 'PASS', 'No ledger, so no lease.')], []
    configs = []
    with tempfile.TemporaryDirectory(prefix='readiness-') as tmp:
        copy = Path(tmp) / 'paper-copy.sqlite'
        try:
            shutil.copyfile(path, copy)
            if Path(str(path) + '-wal').is_file():
                shutil.copyfile(str(path) + '-wal', str(copy) + '-wal')
            db = sqlite3.connect(copy)
            try:
                result = [r[0] for r in db.execute('PRAGMA integrity_check')]
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                accounts = [json.loads(r[0]) for r in db.execute('SELECT body FROM accounts')] if 'accounts' in tables else []
                leases = db.execute('SELECT COUNT(*) FROM paper_workers WHERE enabled=1 AND expires>?', (now.timestamp(),)).fetchone()[0] \
                    if 'paper_workers' in tables else 0
            finally:
                db.close()
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            return [check('paper-db', 'Paper database integrity', 'FAIL', 'Ledger copy could not be checked (%s): %s' % (type(exc).__name__, path),
                          'Do not start the app against this ledger. Restore from a backup in the private backups folder.')], []
    if result != ['ok']:
        return [check('paper-db', 'Paper database integrity', 'FAIL', 'PRAGMA integrity_check reported problems on a copy of %s.' % path,
                      'Do not start the app against this ledger. Restore from a backup.')], []
    configs = [a.get('config', {}) for a in accounts if isinstance(a, dict)]
    checks = [check('paper-db', 'Paper database integrity', 'PASS', 'PRAGMA integrity_check ok on a temporary copy of %s (%d account(s)); original not modified. Stop the app before running this so the copy is consistent (db and -wal are copied; -shm is not, as SQLite rebuilds it from the -wal).' % (path, len(accounts)))]
    if leases:
        checks.append(check('ledger-lease', 'No active worker lease in ledger', 'BLOCKED', '%d unexpired worker lease(s) in the ledger copy; another app process may be running.' % leases,
                            'Owner: stop any other TradeLab process (or wait for the lease to expire) before arming.'))
    else:
        checks.append(check('ledger-lease', 'No active worker lease in ledger', 'PASS', 'No unexpired worker lease.'))
    return checks, configs


def session_config(configs):
    sys.path.insert(0, str(ROOT))
    import intraday_contract
    mine = [c for c in configs if c.get('strategy') == intraday_contract.VERSION]
    if not mine:
        return check('session-config', 'Session / square-off configuration', 'BLOCKED',
                     'No Intraday v1 paper account exists to validate (entry cutoff and square-off are per-account).',
                     'Owner: create an imported Intraday v1 account at /trader-paper with entryEnd before squareOff, both on 5-minute IST boundaries, squareOff <= 15:25.')
    bad = []
    for config in mine:
        try:
            intraday_contract.validate(config)
        except (ValueError, KeyError, TypeError) as exc:
            bad.append('%s: %s' % (config.get('symbol', '?'), exc))
    if bad:
        return check('session-config', 'Session / square-off configuration', 'FAIL', 'Invalid intraday_contract settings: ' + '; '.join(bad),
                     'Create a new account with valid settings; existing accounts cannot be edited into validity here.')
    return check('session-config', 'Session / square-off configuration', 'PASS',
                 '%d Intraday v1 account(s) pass intraday_contract.validate (cutoff/square-off on 5-minute IST boundaries, square-off <= 15:25).' % len(mine))


def calendar_check(path, configs, now):
    sys.path.insert(0, str(ROOT))
    if not path:
        return check('calendar', 'Session calendar covers today', 'BLOCKED', 'No calendar manifest supplied to this check.',
                     'Owner: pass --calendar PATH, and paste an attributed calendar manifest into the worker panel when arming (sample: docs/infy-paper-calendar-2026-11-20.json).')
    from market_contract import session_for
    today = now.astimezone(IST).date().isoformat()
    try:
        manifest = json.loads(Path(path).read_text(encoding='utf-8'))
        session = session_for(manifest, date=today, as_of=now.isoformat())
    except (OSError, json.JSONDecodeError) as exc:
        return check('calendar', 'Session calendar covers today', 'FAIL', 'Calendar unreadable (%s).' % type(exc).__name__)
    except ValueError as exc:
        status = 'BLOCKED' if 'Session unknown' in str(exc) else 'FAIL'
        return check('calendar', 'Session calendar covers today', status, 'Calendar for %s: %s' % (today, exc),
                     'Owner: obtain an attributed manifest that lists %s explicitly (holiday = null).' % today if status == 'BLOCKED' else '')
    import trading_calendar
    try:
        info = trading_calendar.validate(manifest, now.isoformat(), strict_sessions=False)
    except trading_calendar.CalendarError as exc:
        return check('calendar', 'Session calendar covers today', 'FAIL', 'Calendar not usable: %s' % exc,
                     'Owner: refresh the attributed calendar from its source and review its terms of use.')
    if not session['open']:
        return check('calendar', 'Session calendar covers today', 'BLOCKED', '%s is marked as a holiday/closed in the manifest.' % today,
                     'Owner: arm on a date the manifest lists as open.')
    close = dt.datetime.fromisoformat(session['end'])
    for config in configs:
        if config.get('strategy') == 'intraday-v1' and config.get('squareOff'):
            exit_open = dt.datetime.combine(close.date(), dt.time.fromisoformat(config['squareOff']), IST)
            if exit_open + dt.timedelta(minutes=5) >= close:
                return check('calendar', 'Session calendar covers today', 'FAIL',
                             'Square-off %s for %s completes at or after the session close %s.' % (config['squareOff'], config.get('symbol', '?'), close.time().isoformat('minutes')))
    return check('calendar', 'Session calendar covers today', 'PASS', 'Manifest %s lists %s as open %s-%s IST; square-off completes before close; %d trading days of runway through %s. This is attestation, not exchange verification.' % (
        info['version'], today, dt.datetime.fromisoformat(session['start']).time().isoformat('minutes'), close.time().isoformat('minutes'),
        info['runwayTradingDays'], info['lastDate']))


def storage_approval(env):
    if env.flag('KITE_DATA_STORAGE_APPROVED'):
        return check('storage-approval', 'Data-storage approval flag', 'PASS',
                     'KITE_DATA_STORAGE_APPROVED=true. Reminder: this is your own attestation of provider retention rights.')
    return check('storage-approval', 'Data-storage approval flag', 'BLOCKED',
                 'KITE_DATA_STORAGE_APPROVED is not true. Blocks: POST /api/paper-worker/start (app.py), saving history as CSV (market_data.py) and the automatic-selection start.',
                 'Owner: confirm your Kite data-retention rights, then set KITE_DATA_STORAGE_APPROVED=true in .env and restart the app. Do not set it without that confirmation.')


def market_hours(now):
    local = now.astimezone(IST)
    plausible = local.weekday() < 5 and dt.time(9, 15) <= local.time() < dt.time(15, 30)
    label = 'Approximate only (weekday and clock, no holiday calendar): IST now is %s %s.' % (local.date().isoformat(), local.strftime('%a %H:%M'))
    if plausible:
        return check('market-hours', 'Market plausibly open (approximate)', 'PASS', label + ' Within 09:15-15:30 on a weekday.')
    return check('market-hours', 'Market plausibly open (approximate)', 'BLOCKED', label + ' Outside weekday 09:15-15:30 IST.',
                 'Owner: arm during a confirmed NSE trading session (09:15-15:30 IST), after checking the NSE holiday list yourself.')


def replay(script, skip):
    if skip:
        return check('fixture-replay', 'Fixture recovery replay', 'BLOCKED', 'Skipped by --skip-replay.', 'Run without --skip-replay to execute scripts/fixture_recovery.py.')
    env = {k: v for k, v in os.environ.items() if not k.startswith(SECRET_PREFIXES)}
    env.update(TRADELAB_ENABLE_LIVE_ORDERS='false', KITE_API_KEY='', KITE_API_SECRET='')
    try:
        done = subprocess.run([sys.executable, str(script)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=240)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired) as exc:
        return check('fixture-replay', 'Fixture recovery replay', 'FAIL', 'Replay could not complete (%s).' % type(exc).__name__)
    if done.returncode == 0:
        return check('fixture-replay', 'Fixture recovery replay', 'PASS', 'scripts/fixture_recovery.py passed (temporary loopback servers and database; no internet, no broker).')
    tail = (done.stderr.strip().splitlines() or ['no error text'])[-1][:160]
    return check('fixture-replay', 'Fixture recovery replay', 'FAIL', 'Replay exited %d: %s' % (done.returncode, tail),
                 'Fix before arming; loopback sockets must be allowed on this computer.')


def run_checks(environ, project_root=ROOT, env_file=None, now=None, calendar=None, replay_script=None, skip_replay=False):
    project_root = Path(project_root)
    env = Env(environ, read_dotenv(env_file or project_root / '.env'))
    now = now or dt.datetime.now(IST)
    ledger, configs = paper_ledger(env, project_root, now)
    results = [live_lock(project_root, env), credentials(env), sdk(),
               check('broker-login', 'Zerodha login', 'BLOCKED', 'Interactive login cannot be verified offline; broker tokens live in memory only and a fresh app is disconnected.',
                     'Owner: start the app, open http://127.0.0.1:8765/ and click Connect Zerodha, then sign in yourself.'),
               data_dir(env, project_root), *ledger, worker_default(), session_config(configs), calendar_check(calendar, configs, now),
               replay(replay_script or ROOT / 'scripts' / 'fixture_recovery.py', skip_replay), storage_approval(env), market_hours(now)]
    return results


def render(results, now):
    lines = ['TradeLab paper-readiness preflight (offline: no network, no secret values, no broker contact)',
             'IST now: %s' % now.astimezone(IST).strftime('%Y-%m-%d %H:%M %a'), '']
    for item in results:
        lines.append('[%-7s] %s' % (item['status'], item['title']))
        lines.append('          ' + item['detail'])
        if item['ownerAction'] and item['status'] != 'PASS':
            lines.append('          Owner action: ' + item['ownerAction'])
    counts = {s: sum(1 for r in results if r['status'] == s) for s in ORDER}
    lines += ['', 'Summary: %(PASS)d PASS, %(BLOCKED)d BLOCKED, %(FAIL)d FAIL.' % counts,
              'This checks setup only. It places no order and is not evidence of profitability.']
    return '\n'.join(lines)


def main(argv=None, environ=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='print machine-readable JSON')
    parser.add_argument('--skip-replay', action='store_true', help='skip the fixture recovery replay')
    parser.add_argument('--replay-script', help=argparse.SUPPRESS)
    parser.add_argument('--project-root', default=str(ROOT))
    parser.add_argument('--env-file', help='.env path (default: <project root>/.env)')
    parser.add_argument('--calendar', help='session calendar manifest JSON to validate for today')
    parser.add_argument('--now', help='timezone-aware ISO time override (testing)')
    args = parser.parse_args(argv)
    now = dt.datetime.fromisoformat(args.now) if args.now else dt.datetime.now(IST)
    if now.tzinfo is None:
        parser.error('--now needs a timezone offset')
    results = run_checks(os.environ if environ is None else environ, args.project_root, args.env_file, now, args.calendar,
                         args.replay_script, args.skip_replay)
    failed = any(r['status'] == 'FAIL' for r in results)
    if args.json:
        counts = {s: sum(1 for r in results if r['status'] == s) for s in ORDER}
        print(json.dumps(dict(generatedAt=now.isoformat(), istDate=now.astimezone(IST).date().isoformat(), ok=not failed,
                              counts=counts, checks=results), indent=2))
    else:
        print(render(results, now))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
