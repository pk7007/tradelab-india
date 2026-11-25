#!/usr/bin/env python3
"""Offline end-of-day (or weekly) paper report. Read-only: no order, login, network or engine start.

    python scripts/eod_report.py --day 2026-11-25
    python scripts/eod_report.py --week-ending 2026-11-27

Exit code: 0 PASS, 1 FAILED, 2 NO DATA, 3 bad arguments. Output goes to the private folder (default LOCALAPPDATA/TradeLabIndia/reports,
else data/private/reports), never to Git.
"""
import argparse
import datetime as dt
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import eod_report  # noqa: E402

CODES = {'PASS': 0, 'FAILED': 1, 'NO DATA': 2}


def _base():
    return Path(os.environ.get('LOCALAPPDATA', str(ROOT / 'data' / 'private'))) / 'TradeLabIndia'


def default_alerts(environ=None):
    """The incident inbox app.py writes: next to its portal database, named operational-alerts.sqlite."""
    environ = os.environ if environ is None else environ
    base = Path(environ.get('LOCALAPPDATA', str(ROOT / 'data' / 'private'))) / 'TradeLabIndia'
    return Path(environ.get('TRADELAB_PORTAL_DB', str(base / 'portal.sqlite'))).parent / 'operational-alerts.sqlite'


def main(argv=None, out=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--db', default=os.environ.get('TRADELAB_PAPER_DB', str(_base() / 'paper.sqlite')))
    parser.add_argument('--alerts', help='incident inbox; a path that does not exist makes the report FAILED')
    parser.add_argument('--out', default=str(_base() / 'reports'))
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--day', default=dt.date.today().isoformat())
    group.add_argument('--week-ending')
    args = parser.parse_args(argv)
    required = args.alerts is not None
    alerts = args.alerts or str(default_alerts())
    try:
        dt.date.fromisoformat(args.week_ending or args.day)
    except ValueError:
        out.write('Dates must be ISO (YYYY-MM-DD).\n')
        return 3
    if args.week_ending:
        end = dt.date.fromisoformat(args.week_ending)
        week = eod_report.build_week(args.db, [(end - dt.timedelta(days=n)).isoformat() for n in range(6, -1, -1)], alerts_path=alerts, alerts_required=required)
        folder = Path(args.out)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ('weekly-%s.md' % end.isoformat())).write_text(eod_report.render_week(week), encoding='utf-8')
        out.write('Weekly report %s: %s\n' % (end.isoformat(), week['status']))
        return CODES[week['status']]
    report = eod_report.build(args.db, args.day, alerts_path=alerts, alerts_required=required)
    path = eod_report.write(report, args.out)
    out.write('End-of-day report %s: %s (%s)\n' % (report['day'], report['status'], path))
    return CODES[report['status']]


if __name__ == '__main__':
    sys.exit(main())
