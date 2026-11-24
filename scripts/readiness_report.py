#!/usr/bin/env python3
"""Machine-readable live-trading readiness report. Offline and read-only: no order, login, network or state change.

    python scripts/readiness_report.py                       # JSON to stdout
    python scripts/readiness_report.py --markdown            # human summary
    python scripts/readiness_report.py --trades trades.json --capital 100000 --forward-days 12 --shadow-days 0

Forward and shadow days must be real elapsed sessions counted by the owner; they are never inferred from backtests.
`--trades` is a JSON list of completed trades [{"day": "YYYY-MM-DD", "net": rupees after all costs}, ...].
Exit code 0 always means only "report produced"; read `decision` and `blockers`. Exit 3 is bad input.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import live_readiness  # noqa: E402

MAX_BYTES = 20_000_000


def _load(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Input file is too large.')
    return json.loads(path.read_text(encoding='utf-8'))


def build(args):
    evidence = _load(args.evidence)['criteria']
    perf = None
    trades = []
    digest = None
    if args.trades:
        trades = _load(args.trades)
        perf = live_readiness.performance(trades, capital=args.capital)
        digest = hashlib.sha256(Path(args.trades).read_bytes()).hexdigest()
    report = live_readiness.assess(evidence, perf, args.forward_days, args.shadow_days, root=ROOT, trades_digest=digest)
    if perf:
        low, high = live_readiness.bootstrap_expectancy(trades, seed=1)
        report['statistics'] = dict(expectancyInterval95=[low, high],
                                    riskOfRuin8pct=live_readiness.risk_of_ruin(trades, capital=args.capital, ruin_fraction=0.08, seed=1))
    return report


def markdown(report):
    lines = ['# Live-trading readiness', '', '- Score: %s/100 (%s)' % (report['score'], report['classification']),
             '- Decision: **%s**' % report['decision'], '- Live trading permitted by this report: no (eligibility only)', '',
             '| Domain | Score |', '|---|---:|']
    lines += ['| %s | %s/%s |' % (name, d['score'], d['max']) for name, d in report['domains'].items()]
    lines += ['', '## Hard blockers', ''] + ['- %s: %s. %s' % (b['id'], b['status'].upper(), b['detail']) for b in report['blockers']]
    lines += ['', '## Criteria without verified evidence', ''] + ['- ' + c for c in report['missingEvidence']]
    return '\n'.join(lines) + '\n'


def main(argv=None, out=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--evidence', default=str(ROOT / 'docs' / 'readiness-evidence.json'))
    parser.add_argument('--trades')
    parser.add_argument('--capital', type=float, default=100000.0)
    parser.add_argument('--forward-days', type=int, default=0)
    parser.add_argument('--shadow-days', type=int, default=0)
    parser.add_argument('--markdown', action='store_true')
    args = parser.parse_args(argv)
    if args.forward_days < 0 or args.shadow_days < 0:
        out.write('Day counts cannot be negative.\n')
        return 3
    try:
        report = build(args)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        out.write('Readiness input refused (%s).\n' % type(error).__name__)
        return 3
    out.write(markdown(report) if args.markdown else json.dumps(report, indent=2, allow_nan=False) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
