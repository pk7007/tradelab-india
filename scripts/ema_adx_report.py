"""Offline research report for the EMA 20/50 + ADX intraday strategy. Reads local JSON files only.

Usage:
  python scripts/ema_adx_report.py --bars bars.json --config config.json [--actions actions.json] [--walk-forward]

`bars.json` is a list of completed 5-minute bars (date, open, high, low, close, volume; timezone-aware IST dates);
`config.json` holds the saved risk limits (see docs/strategy-ema-adx.md); `actions.json` is an optional list of
owner-supplied corporate actions. Prints JSON. No network, no broker, no orders, no profitability claim.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ema_adx_backtest as bt

MAX_BYTES = 20_000_000


def load(path):
    file = Path(path)
    if not file.is_file() or file.stat().st_size > MAX_BYTES:
        raise SystemExit('Input file missing or too large: %s' % file.name)
    try:
        return json.loads(file.read_text(encoding='utf-8'))
    except ValueError:
        raise SystemExit('Input is not valid JSON: %s' % file.name) from None


def run(args):
    bars, config = load(args.bars), load(args.config)
    if args.actions:
        bars = bt.adjust_for_actions(bars, load(args.actions))
    if args.walk_forward:
        report = bt.walk_forward(bars, config, minimum_train=args.minimum_train, test_size=args.test_size,
                                 label_horizon=args.label_horizon)
        for fold in report['folds']:
            fold['trades'] = [{k: v for k, v in t.items() if k in ('entryDate', 'exitDate', 'exitReason', 'quantity', 'netPnl')}
                              for t in fold['trades']]
        return report
    result = bt.backtest(bars, config)
    result.pop('equity')
    return result


def main(argv=None, out=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--bars', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--actions')
    parser.add_argument('--walk-forward', action='store_true')
    parser.add_argument('--minimum-train', type=int, default=300)
    parser.add_argument('--test-size', type=int, default=150)
    parser.add_argument('--label-horizon', type=int, default=75)
    args = parser.parse_args(argv)
    try:
        report = run(args)
    except ValueError as error:
        raise SystemExit('Cannot run: %s' % error) from None
    (out or sys.stdout).write(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
