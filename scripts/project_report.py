"""Offline project status report (Markdown). Runs local checks only: no network, no broker, no model call.

Usage:
    python scripts/project_report.py                 # print to stdout
    python scripts/project_report.py --write         # reports/status-YYYY-MM-DD.md (git-ignored)
    python scripts/project_report.py --out PATH      # write to PATH
    python scripts/project_report.py --since 2026-11-01 --strict

Overall status is PASS only if every present check passed. One exception: a paper_readiness FAIL whose only
failing item is the missing broker package (kiteconnect) is labelled 'FAILED (environment)', listed, and does not fail
the overall status, because the scheduled CI report installs only requirements-dev.txt. Any other readiness FAIL
(live lock, ledger, worker armed by default, ...) fails the report. BLOCKED readiness items are owner actions, not failures.

The report states check results and carried findings only. It never rates strategy performance.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAIL_LINES = 25
TAIL_CHARS = 2500
CHECK_TIMEOUT = 900

# Readiness FAIL ids caused by the runner's installed packages, not by project state. They are shown
# as 'FAILED (environment)' and do not fail the overall status (the CI report installs only requirements-dev.txt).
ENVIRONMENT_FAIL_IDS = {'kiteconnect'}

PASS, FAILED, ERROR, NA = 'PASS', 'FAILED', 'ERROR', 'not available'

SECRET_KEY = r'[\w.-]*(?:api[_-]?key|secret|token|passwd|password|access[_-]?key|credential|auth)[\w.-]*'
SECRET_PATTERNS = [
    (re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)', re.S), '[REDACTED]'),
    (re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}'), 'Bearer [REDACTED]'),
    (re.compile(r'(?i)\b(' + SECRET_KEY + r')(["\']?\s*[:=]\s*)("[^"\n]*"|\'[^\'\n]*\'|[^\s,;]+)'), r'\1\2[REDACTED]'),
    (re.compile(r'\bxox[abprs]-[A-Za-z0-9-]{8,}'), '[REDACTED]'),
    (re.compile(r'\bAIza[0-9A-Za-z_-]{30,}'), '[REDACTED]'),
    (re.compile(r'\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{16,}'), '[REDACTED]'),
    (re.compile(r'\bgithub_pat_[A-Za-z0-9_]{16,}'), '[REDACTED]'),
    (re.compile(r'\bsk-[A-Za-z0-9_-]{16,}'), '[REDACTED]'),
    (re.compile(r'\bAKIA[0-9A-Z]{16}\b'), '[REDACTED]'),
    (re.compile(r'\b[A-Fa-f0-9]{32,}\b'), '[REDACTED]'),
]
CLAIM_RE = re.compile(r'(?i)profitab\w*|\bguarantee\w*|\blive[- ]ready\b|\bprofit factor\b|\bsure[- ]shot\b|\brisk[- ]free\b')
NEGATION_RE = re.compile(r"(?i)\b(?:not|no|never|nor|without|cannot|can't|isn't|aren't|unobserved|unverified)\b")

DISCLAIMER = [
    'No profitability is established or implied. Nothing here rates strategy performance.',
    'No live-readiness is established. Passing offline checks does not authorise broker orders, strategy promotion or changed loss limits.',
    'No live Zerodha run was observed. Broker login stays owner-only and no broker access was used.',
    'No real model call was made. No network access was used by this script.',
    'Offline checks cover code defects, syntax and fixture-based tests only; they say nothing about forward paper evidence.',
]

FIXED_STEPS = [
    'Owner-only Zerodha login and a supervised paper session during market hours (market-dependent activation deferred until Monday, 23 November 2026).',
    'Collect forward paper evidence over real sessions before drawing any conclusion about a strategy.',
    'Close the live safety gaps listed in the audit (for example flatten-on-kill versus relabelling the research risk gate) before any path could reach live dispatch.',
    'Keep the independent review cycle from AGENTS.md for each completed task.',
]


def scrub(text):
    text = str(text)
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def clean(text):
    return scrub(text)


def find_claim_lines(text):
    """Lines containing a performance-claim phrase that is not negated on the same line."""
    return [line.strip() for line in str(text).splitlines() if CLAIM_RE.search(line) and not NEGATION_RE.search(line)]


def missing_tool(rc, output):
    return rc in (126, 127) or bool(re.search(r'No module named|command not found|No such file or directory: .(?:node|git)', str(output)))


def default_runner(cmd, cwd, timeout=CHECK_TIMEOUT):
    done = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, errors='replace')
    return done.returncode, (done.stdout or '') + (done.stderr or '')


class Check:
    def __init__(self, name, status, detail='', output='', required=True):
        self.name, self.status, self.detail, self.output, self.required = name, status, detail, output, required
        self.notes = []
        self.env_only = False

    @property
    def blocking(self):
        if self.status == NA:
            return False
        return self.status != PASS and not self.env_only

    @property
    def label(self):
        return 'FAILED (environment)' if self.env_only else self.status


def tail(text):
    lines = [line.rstrip() for line in str(text).strip().splitlines()]
    out = '\n'.join(lines[-TAIL_LINES:])
    return out[-TAIL_CHARS:]


def run(runner, cmd, root, timeout=CHECK_TIMEOUT):
    """Return (rc, output, error_text). Any runner exception becomes an error, never a pass."""
    try:
        rc, output = runner(cmd, root, timeout)
        output = output or ''
        if missing_tool(rc, output):
            first = (output.strip().splitlines() or [''])[-1][:200]
            return None, output, 'tool not available (exit %s): %s' % (rc, first)
        return rc, output, None
    except Exception as exc:  # noqa: BLE001 - every failure must be shown, not hidden
        return None, '', '%s: %s' % (type(exc).__name__, exc)


COUNT_RE = re.compile(r'(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|warnings?|deselected|rerun)\b')


def parse_pytest_counts(output):
    """Counts from the pytest summary line (last line that has 'in <time>'), None if absent."""
    for line in reversed(str(output).strip().splitlines()):
        if re.search(r'\bin \d+(\.\d+)?s\b', line):
            counts = {}
            for number, word in COUNT_RE.findall(line):
                key = 'errors' if word.startswith('error') else 'warnings' if word.startswith('warning') else word
                counts[key] = counts.get(key, 0) + int(number)
            return counts
    return None


def fmt_counts(counts):
    return ', '.join('%d %s' % (v, k) for k, v in counts.items()) or 'no tests ran'


def check_pytest(runner, root):
    cmd = [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider']
    rc, output, err = run(runner, cmd, root)
    if err:
        return Check('pytest', ERROR, err)
    counts = parse_pytest_counts(output)
    if counts is None:
        return Check('pytest', ERROR, 'could not parse a pytest summary (exit code %s)' % rc, output)
    detail = fmt_counts(counts)
    if rc == 0 and counts.get('passed', 0) > 0 and not counts.get('failed') and not counts.get('errors'):
        return Check('pytest', PASS, detail)
    if rc == 0:
        return Check('pytest', ERROR, detail + ' (no passing tests recorded)', output)
    return Check('pytest', FAILED if rc == 1 else ERROR, '%s (exit code %s)' % (detail, rc), output)


def check_ruff(runner, root):
    rc, output, err = run(runner, [sys.executable, '-m', 'ruff', 'check', '.'], root)
    if err:
        return Check('ruff', ERROR, err)
    if rc == 0:
        return Check('ruff', PASS, 'no findings')
    found = re.search(r'Found (\d+) error', output)
    detail = 'exit code %s' % rc
    if found:
        detail = '%s finding(s)' % found.group(1)
    if rc not in (1,) and not found:
        return Check('ruff', ERROR, detail, output)
    return Check('ruff', FAILED, detail, output)


def check_bandit(runner, root):
    cmd = [sys.executable, '-m', 'bandit', '-q', '-r', '.', '-c', 'pyproject.toml', '--severity-level', 'high']
    rc, output, err = run(runner, cmd, root)
    if err:
        return Check('bandit (high severity)', ERROR, err)
    if rc == 0:
        return Check('bandit (high severity)', PASS, '0 high-severity issues')
    issues = len(re.findall(r'Issue:', output))
    if rc == 1:
        return Check('bandit (high severity)', FAILED, '%d high-severity issue(s)' % issues, output)
    return Check('bandit (high severity)', ERROR, 'exit code %s' % rc, output)


def check_files(runner, root, name, files, make_cmd):
    if not files:
        return Check(name, ERROR, 'no files found')
    bad, errors = [], []
    for path in files:
        rc, output, err = run(runner, make_cmd(path), root)
        if err:
            errors.append((path, err))
        elif rc != 0:
            bad.append((path, output))
    ok = len(files) - len(bad) - len(errors)
    detail = '%d/%d passed' % (ok, len(files))
    if not bad and not errors:
        return Check(name, PASS, detail)
    parts = ['%s: %s' % (path.name, tail(out)) for path, out in bad] + ['%s: %s' % (path.name, e) for path, e in errors]
    status = ERROR if errors and not bad else FAILED
    return Check(name, status, detail + '; failing: ' + ', '.join(p.name for p, _ in bad + errors), '\n---\n'.join(parts))


def plugin_json(output):
    try:
        data = json.loads(output)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def check_structure(runner, root):
    name = 'structure_check'
    path = root / 'scripts' / 'structure_check.py'
    if not path.is_file():
        return Check(name, NA, 'scripts/structure_check.py is not in this checkout', required=False)
    rc, output, err = run(runner, [sys.executable, str(path), '--json'], root)
    if err:
        return Check(name, ERROR, err, required=False)
    data = plugin_json(output)
    counts = data.get('counts') if data else None
    if rc is None or rc >= 2:
        return Check(name, ERROR, 'exit code %s' % rc, output, required=False)
    if not data or not isinstance(counts, dict) or not isinstance(counts.get('integrity'), int) or not isinstance(data.get('findings'), list):
        return Check(name, ERROR, 'unparseable output or missing counts.integrity/findings (exit code %s)' % rc, output, required=False)
    integrity, info = counts['integrity'], counts.get('info', 0)
    detail = 'integrity %d, info %s' % (integrity, info)
    if integrity > 0 or rc != 0:
        lines = []
        for finding in data['findings']:
            if isinstance(finding, dict) and finding.get('severity', 'integrity') == 'integrity':
                lines.append('%s %s' % (finding.get('check', '?'), finding.get('path', '?')) + (':%s' % finding['line'] if finding.get('line') else ''))
        return Check(name, FAILED, detail + ' (exit code %s)' % rc, '\n'.join(lines), required=False)
    return Check(name, PASS, detail, required=False)


def check_readiness(runner, root):
    name = 'paper_readiness'
    path = root / 'scripts' / 'paper_readiness.py'
    if not path.is_file():
        return Check(name, NA, 'scripts/paper_readiness.py is not in this checkout', required=False)
    rc, output, err = run(runner, [sys.executable, str(path), '--json'], root)
    if err:
        return Check(name, ERROR, err, required=False)
    data = plugin_json(output)
    if rc is None or rc not in (0, 1) or not data or not isinstance(data.get('checks'), list) or not isinstance(data.get('counts'), dict):
        return Check(name, ERROR, 'unparseable output or missing checks/counts (exit code %s)' % rc, output, required=False)
    items = [c for c in data['checks'] if isinstance(c, dict)]
    failing = [c for c in items if c.get('status') == 'FAIL']
    blocked = [c for c in items if c.get('status') == 'BLOCKED']
    counts = data['counts']
    detail = '%s PASS, %s BLOCKED, %s FAIL' % (counts.get('PASS', 0), counts.get('BLOCKED', 0), len(failing))
    notes = ['%s: %s %s' % (c.get('title', c.get('id', '?')), c.get('detail', ''), c.get('ownerAction', '')) for c in blocked]
    if failing:
        out = '\n'.join('%s: %s %s' % (c.get('title', c.get('id', '?')), c.get('detail', ''), c.get('ownerAction', '')) for c in failing)
        check = Check(name, FAILED, detail, out, required=False)
        check.env_only = all(c.get('id') in ENVIRONMENT_FAIL_IDS for c in failing)
    elif rc == 1:
        return Check(name, ERROR, 'exit code 1 but no FAIL item listed', output, required=False)
    else:
        check = Check(name, PASS, detail + ' (BLOCKED items need owner actions, not failures)', required=False)
    check.notes = notes
    return check


def collect_checks(root, runner):
    root = Path(root)
    checks = [check_pytest(runner, root), check_ruff(runner, root), check_bandit(runner, root)]
    node_tests = sorted((root / 'tests').glob('*.test.js'))
    checks.append(check_files(runner, root, 'node tests (tests/*.test.js)', node_tests, lambda p: ['node', str(p.relative_to(root))]))
    web_js = sorted((root / 'web').glob('*.js'))
    checks.append(check_files(runner, root, 'node --check web/*.js', web_js, lambda p: ['node', '--check', str(p.relative_to(root))]))
    checks.append(check_structure(runner, root))
    checks.append(check_readiness(runner, root))
    return checks


def section_bullets(path, heading_pattern, limit=12):
    try:
        text = Path(path).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None
    lines, capture, items = text.splitlines(), False, []
    for line in lines:
        if line.startswith('#'):
            if capture:
                break
            capture = bool(re.search(heading_pattern, line, re.I))
            continue
        if capture:
            match = re.match(r'\s*(?:[-*]|\d+[.)])\s+(.*)', line)
            if match:
                items.append(match.group(1).strip())
            elif items and line.startswith('  ') and line.strip():
                items[-1] += ' ' + line.strip()
    return [i if len(i) <= 220 else i[:217] + '...' for i in items[:limit]]


def carried_findings(root):
    root = Path(root)
    sources = [
        ('docs/current-state-audit-2026-11-23.md', r'material risks|limits'),
        ('docs/tooling.md', r'open items'),
    ]
    result = []
    for rel, pattern in sources:
        result.append((rel, section_bullets(root / rel, pattern)))
    return result


def changes_since(runner, root, since, limit=20):
    if since:
        cmd = ['git', 'log', '--oneline', '--since=' + since]
        label = 'since %s' % since
    else:
        rc, output, err = run(runner, ['git', 'describe', '--tags', '--abbrev=0'], root)
        tag = output.strip().splitlines()[0].strip() if (not err and rc == 0 and output.strip()) else ''
        if tag:
            cmd, label = ['git', 'log', '--oneline', tag + '..HEAD'], 'since tag %s' % tag
        else:
            cmd, label = ['git', 'log', '--oneline', '-%d' % limit], 'last %d commits (no tag found)' % limit
    rc, output, err = run(runner, cmd, root)
    if err or rc != 0:
        return label, None, err or 'git log failed (exit code %s)' % rc
    return label, [line for line in output.splitlines() if line.strip()], None


def latest_rating(root, report_dir='reports'):
    ratings = sorted((Path(root) / 'docs').glob('rating-*.md'))
    if not ratings:
        return None
    return Path(os.path.relpath(ratings[-1], Path(root) / report_dir)).as_posix()


def build_report(root, runner=default_runner, today=None, since=None, report_dir='reports'):
    """Return (markdown, overall_status). Overall PASS only if every present check passed."""
    root = Path(root)
    today = today or datetime.date.today()
    checks = collect_checks(root, runner)
    blocking = [c for c in checks if c.blocking]
    overall = 'PASS' if not blocking else 'FAIL'
    out = ['# TradeLab status report %s' % today.isoformat(), '']

    out += ['## Summary', '', 'Overall status: %s' % overall, '']
    shown = [c for c in checks if c.status != NA]
    out.append('%d of %d checks passed.' % (sum(c.status == PASS for c in shown), len(shown)))
    if blocking:
        out.append('Not passing: ' + ', '.join('%s (%s)' % (c.name, c.label) for c in blocking) + '.')
    env = [c.name for c in checks if c.env_only]
    if env:
        out.append('Environment-only failures (shown, not counted against overall status): ' + ', '.join(env) + '.')
    na = [c.name for c in checks if c.status == NA]
    if na:
        out.append('Optional checks not available: ' + ', '.join(na) + '.')
    out.append('')

    out += ['## Checks', '', '| Check | Status | Result |', '|---|---|---|']
    for c in checks:
        out.append('| %s | %s | %s |' % (clean(c.name), c.label, clean(c.detail).replace('|', '/').replace('\n', ' ')))
    out.append('')
    for c in checks:
        if c.status in (FAILED, ERROR) and c.output.strip():
            out += ['### %s output (tail)' % clean(c.name), '', '```', clean(tail(c.output)).replace('```', "'''"), '```', '']

    for c in checks:
        if c.notes:
            out += ['### %s: blocked items needing owner action' % clean(c.name), ''] + ['- ' + clean(n) for n in c.notes] + ['']

    label, commits, err = changes_since(runner, root, since)
    out += ['## Changes since last report/tag', '', 'Range: %s' % clean(label), '']
    if commits is None:
        out.append('- git history not available: %s' % clean(err))
    elif not commits:
        out.append('- none')
    else:
        out += ['- ' + clean(c) for c in commits]
    out.append('')

    out += ['## Carried findings', '']
    carried_items = []
    for rel, bullets in carried_findings(root):
        if bullets is None:
            out.append('- %s not found or unreadable' % rel)
        elif not bullets:
            out.append('- %s: no matching list found' % rel)
        else:
            out.append('- From %s:' % rel)
            for b in bullets:
                out.append('  - ' + clean(b))
                carried_items.append(clean(b))
    out.append('')

    out += ['## Recommended next steps', '']
    n = 0
    for c in blocking:
        n += 1
        out.append('%d. Fix failing check: %s (%s).' % (n, clean(c.name), c.status))
    for c in checks:
        if c.env_only:
            n += 1
            out.append('%d. Environment: %s reports a missing package in this runner (see its output); install requirements.txt in the owner environment. Not counted against the overall status.' % (n, clean(c.name)))
    for item in carried_items:
        n += 1
        out.append('%d. Carried finding: %s' % (n, item))
    for step in FIXED_STEPS:
        n += 1
        out.append('%d. %s' % (n, step))
    out.append('')

    body = '\n'.join(out)
    flagged = find_claim_lines(body)
    if flagged:
        out += ['## Wording to review', '', 'These lines contain a performance-claim phrase that is not negated. They are shown unchanged for a person to review.', ''] + ['- ' + line for line in flagged] + ['']

    rating = latest_rating(root, report_dir)
    out += ['## Latest rating pointer', '', '[%s](%s)' % (rating, rating) if rating else 'none', '']

    out += ['## What this report does not establish', ''] + ['- ' + line for line in DISCLAIMER] + ['']
    return '\n'.join(out), overall


def write_step_summary(path, overall, report):
    """Append the verdict and the Summary/Checks sections to $GITHUB_STEP_SUMMARY (no-op when unset)."""
    if not path:
        return
    head = report.split('## Changes since')[0]
    try:
        with open(path, 'a', encoding='utf-8') as handle:
            handle.write('### Status report: %s\n\n%s\n' % (overall, head))
    except OSError:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--out', help='write the report to this path (default: stdout)')
    parser.add_argument('--write', action='store_true', help='write to reports/status-YYYY-MM-DD.md')
    parser.add_argument('--since', help='list commits since this date (YYYY-MM-DD); default last tag or last 20')
    parser.add_argument('--strict', action='store_true', help='exit 1 unless overall status is PASS')
    args = parser.parse_args(argv)
    today = datetime.date.today()
    target = args.out or (str(ROOT / 'reports' / ('status-%s.md' % today.isoformat())) if args.write else None)
    report_dir = os.path.relpath(Path(target).resolve().parent, ROOT) if target else '.'
    report, overall = build_report(ROOT, default_runner, today=today, since=args.since, report_dir=report_dir)
    write_step_summary(os.environ.get('GITHUB_STEP_SUMMARY', ''), overall, report)
    if target:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding='utf-8')
    else:
        sys.stdout.write(report)
    print('Overall status: %s%s' % (overall, ' -> ' + target if target else ''), file=sys.stderr if not target else sys.stdout)
    return 1 if args.strict and overall != 'PASS' else 0


if __name__ == '__main__':
    raise SystemExit(main())
