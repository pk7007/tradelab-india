#!/usr/bin/env python3
"""Write improvement proposals from recorded research experiments. Read-only on the registry; changes nothing else.

    python scripts/propose_improvements.py

Defaults: registry %LOCALAPPDATA%/TradeLabIndia/research.sqlite (TRADELAB_RESEARCH_DB overrides), output
%LOCALAPPDATA%/TradeLabIndia/proposals/proposals.jsonl. Exit code 0 = ran (new or none), 1 = could not run,
2 = registry not found (nothing recorded yet, or a wrong path).
Every proposal needs your review; none is ever applied automatically.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import improvement_proposals  # noqa: E402


def _base():
    return Path(os.environ.get('LOCALAPPDATA', str(ROOT / 'data' / 'private'))) / 'TradeLabIndia'


def main(argv=None, out=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--registry', default=os.environ.get('TRADELAB_RESEARCH_DB', str(_base() / 'research.sqlite')))
    parser.add_argument('--out', default=str(_base() / 'proposals' / 'proposals.jsonl'))
    args = parser.parse_args(argv)
    if not Path(args.registry).exists():
        out.write('Experiment registry not found at %s; nothing to propose. Check the path.\n' % args.registry)
        return 2
    try:
        new = improvement_proposals.propose(args.registry, args.out)
    except (OSError, ValueError, RuntimeError) as error:
        out.write('Proposals not written: %s\n' % error)
        return 1
    out.write('%d new proposal(s) written to %s. Nothing was changed; each needs your review.\n' % (len(new), args.out))
    for proposal in new:
        out.write('- experiment %s: %s. %s\n' % (proposal['experimentId'], proposal['rule'], proposal['suggestion']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
