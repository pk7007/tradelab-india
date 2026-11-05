"""Offline, chronological comparison of a fixed price rule with buying and holding."""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
import random

from research import IST, timestamp, validate_rows


PROTOCOL = "sma5-20-next-open-v1"
FIELDS = ("open", "high", "low", "close", "volume")


def csv_candles(raw, symbol):
    """Read a single-instrument CSV with TradeLab's export headers."""
    if not isinstance(raw, str) or not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("Enter the symbol for this CSV file.")
    reader = csv.DictReader(io.StringIO(raw.lstrip("\ufeff"), newline=""), strict=True)
    try:
        names = reader.fieldnames or []
        if len(set(names)) != len(names) or not {"date", *FIELDS} <= set(names):
            raise ValueError("CSV needs unique headers including date, open, high, low, close, volume.")
        rows = []
        for line in reader:
            if None in line or len(rows) >= 50000:
                raise ValueError("Check CSV fields and the 50,000-bar limit.")
            rows.append({key: line[key] for key in ("date", *FIELDS)})
    except csv.Error as exc:
        raise ValueError("Invalid candle CSV.") from exc
    return {symbol.strip(): rows}


def _number(data, key, default, lower, upper):
    value = data.get(key, default)
    try:
        if isinstance(value, bool):
            raise ValueError
        value = float(value)
        if not lower <= value <= upper:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{key} must be a number from {lower} to {upper}.") from None
    return value


def _completed(rows, interval, cutoff):
    if not isinstance(rows, list) or len(rows) > 50000:
        raise ValueError("Provide an array of at most 50,000 candles.")
    try:
        validated = validate_rows(rows, cutoff)
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("Each candle needs a zoned date and numeric OHLCV.") from exc
    bars = []
    previous = None
    for row in validated:
        stamp = timestamp(row["date"])
        if interval == "day":
            if stamp.date() >= cutoff.date():
                continue
            if previous and previous.date() == stamp.date():
                raise ValueError("Daily candles must have distinct local trading dates.")
        else:
            if stamp + dt.timedelta(minutes=5) > cutoff:
                continue
            if (stamp.minute % 5 or stamp.second or stamp.microsecond or
                    not dt.time(9, 15) <= stamp.time() <= dt.time(15, 25)):
                raise ValueError("Use five-minute candle starts from 09:15 through 15:25 IST.")
            if previous:
                if previous.date() == stamp.date():
                    if stamp - previous != dt.timedelta(minutes=5):
                        raise ValueError("Missing five-minute candles within a trading session.")
                elif previous.time() != dt.time(15, 25) or stamp.time() != dt.time(9, 15):
                    raise ValueError("Missing five-minute candles at a session boundary.")
        if any(isinstance(row[key], bool) for key in FIELDS):
            raise ValueError("Boolean values are invalid OHLCV inputs.")
        values = {key: float(row[key]) for key in FIELDS}
        if values["volume"] <= 0 or values["low"] < 1e-6 or values["high"] > 1e9:
            raise ValueError("Require positive volume and prices in the supported range.")
        if row.get("halted") or row.get("reject"):
            raise ValueError("This evaluation requires bars without known halts or fill rejections.")
        bars.append({"date": stamp.isoformat(), **values})
        previous = stamp
    if len(bars) < 100:
        raise ValueError("At least 100 completed candles are required.")
    return bars


def _portfolio(bars, signals, start, end, capital, fee_bps, slip_bps):
    """signals[i] was determined before open i. Both legs end flat at the final open."""
    fee_rate = fee_bps / 10000
    slip_rate = slip_bps / 10000
    cash = peak = capital
    fees = slippage = basis = drawdown = 0.0
    quantity = trades = wins = active = 0
    for index in range(start, end):
        bar = bars[index]
        opening = bar["open"]
        target_long = index < end - 1 and (signals is None or signals[index])
        if target_long and quantity == 0:
            price = opening * (1 + slip_rate)
            quantity = math.floor(cash / (price * (1 + fee_rate)))
            fee = quantity * price * fee_rate
            basis = quantity * price + fee
            cash -= basis
            fees += fee
            slippage += quantity * (price - opening)
        elif not target_long and quantity:
            price = opening * (1 - slip_rate)
            fee = quantity * price * fee_rate
            proceeds = quantity * price - fee
            cash += proceeds
            fees += fee
            slippage += quantity * (opening - price)
            trades += 1
            wins += proceeds > basis
            quantity = 0
        equity = cash + quantity * bar["close"]
        if not math.isfinite(equity) or equity > 1e100:
            raise ValueError("Simulated equity exceeded the supported range. Check the price series.")
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
        active += quantity > 0
    return {
        "finalEquity": round(cash, 4),
        "returnPct": round(100 * (cash / capital - 1), 6),
        "maxDrawdownPct": round(100 * drawdown, 6),
        "completedTrades": trades,
        "winRatePct": round(100 * wins / trades, 4) if trades else None,
        "fees": round(fees, 4),
        "slippage": round(slippage, 4),
        "exposurePct": round(100 * active / (end - start - 1), 4),
    }


def _window(bars, signals, start, end, capital, fees, slip):
    strategy = _portfolio(bars, signals, start, end, capital, fees, slip)
    benchmark = _portfolio(bars, None, start, end, capital, fees, slip)
    return {
        "start": bars[start]["date"], "end": bars[end - 1]["date"], "bars": end - start,
        "strategy": strategy, "benchmark": benchmark,
        "excessReturnPct": round(strategy["returnPct"] - benchmark["returnPct"], 6),
    }


def evaluate(data):
    """Accept one symbol in {candles: {SYMBOL: [zoned OHLCV, ...]}, permitted: true}."""
    if not isinstance(data, dict) or data.get("permitted") is not True:
        raise ValueError("Confirm permission to use these candles for local analysis.")
    if "csv" in data and "candles" in data:
        raise ValueError("Supply either candles or CSV, not both.")
    universe = csv_candles(data["csv"], data.get("symbol")) if "csv" in data else data.get("candles")
    if not isinstance(universe, dict) or len(universe) != 1:
        raise ValueError("Evaluate one symbol per run.")
    symbol, rows = next(iter(universe.items()))
    if not isinstance(symbol, str) or not symbol.strip() or len(symbol) > 64:
        raise ValueError("Provide a symbol of 1 to 64 characters.")
    for key in ("capital", "costBps", "slippageBps", "interval"):
        if key not in data:
            raise ValueError(f"Specify {key} for this evaluation.")
    interval = data["interval"]
    source = data.get("source", "imported")
    if interval not in ("day", "5minute") or source not in ("imported", "synthetic"):
        raise ValueError("Use day or 5minute bars and an imported or synthetic source.")
    if not isinstance(data.get("asOf"), str):
        raise ValueError("Provide the asOf cutoff with its time zone.")
    cutoff = timestamp(data["asOf"])
    bars = _completed(rows, interval, cutoff)
    capital = _number(data, "capital", 100000, 0.01, 1e12)
    fees = _number(data, "costBps", 10, 0, 500)
    slip = _number(data, "slippageBps", 5, 0, 500)
    settings = {"protocol": PROTOCOL, "symbol": symbol, "source": source,
                "asOf": cutoff.isoformat(), "interval": interval, "capital": capital,
                "costBps": fees, "slippageBps": slip}
    canonical = json.dumps([settings, bars], sort_keys=True, separators=(",", ":"), allow_nan=False)
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    closes = [bar["close"] for bar in bars]
    signals = [False] * 20 + [
        math.fsum(closes[i-5:i]) * 4 > math.fsum(closes[i-20:i]) for i in range(20, len(bars))
    ]
    count = len(bars)
    first, second, hold = (count * k // 10 for k in (6, 7, 8))
    validation = [_window(bars, signals, a, b, capital, fees, slip)
                  for a, b in ((first, second), (second, hold))]
    holdout = _window(bars, signals, hold, count, capital, fees, slip)
    stressed = _window(bars, signals, hold, count, capital, 2 * fees, 2 * slip)
    return {
        **settings, "fingerprint": fingerprint, "completedBars": count,
        "developmentBars": first, "validation": validation, "holdout": holdout,
        "stressHoldout": stressed, "stressCostBps": 2 * fees, "stressSlippageBps": 2 * slip,
        "status": "synthetic demonstration" if source == "synthetic" else "historical simulation",
        "method": ("Fixed long-only SMA(5/20). Previous completed closes determine the next-open fill. "
                   "The first 60% supply price history. Two forward 10% windows precede the final 20% holdout. "
                   "Each window starts in cash and exits at its last open. Buy-and-hold uses identical "
                   "capital, whole shares, fees and slippage. Drawdown uses bar-close equity and final cash."),
        "limitations": [
            "Only one user-selected symbol and one fixed rule are evaluated. Reusing a holdout for tuning weakens the evidence.",
            "The source label and import permissions are caller-supplied. Dates, exchange holidays, dividends and corporate actions are unverified.",
            "All desired shares are assumed available at the modeled open. Liquidity, rejections, tax schedules and broker reconciliation are unverified.",
            "Positions may carry overnight, including on five-minute data. Intrabar drawdowns may exceed the reported drawdown.",
            "Historical and synthetic outcomes cannot establish future profits.",
        ],
    }


def demo_request():
    """Reproducible synthetic price path, unrelated to any market symbol."""
    rng = random.Random(4172)
    day = dt.datetime(2023, 1, 2, tzinfo=IST)
    close = 100.0
    bars = []
    while len(bars) < 300:
        if day.weekday() < 5:
            index = len(bars)
            opening = round(close * (1 + rng.uniform(-0.003, 0.003)), 4)
            drift = 0.002 * math.sin(index / 19)
            close = round(opening * (1 + drift + rng.uniform(-0.012, 0.012)), 4)
            bars.append({"date": day.isoformat(), "open": opening, "high": max(opening, close),
                         "low": min(opening, close), "close": close, "volume": 100000})
        day += dt.timedelta(days=1)
    return {"permitted": True, "source": "synthetic", "asOf": day.isoformat(), "interval": "day",
            "capital": 100000, "costBps": 10, "slippageBps": 5, "candles": {"DEMO": bars}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--demo", action="store_true", help="run the deterministic synthetic example")
    choice.add_argument("--input", metavar="PATH", help="read a local evaluation request as JSON")
    args = parser.parse_args()
    try:
        if args.demo:
            request = demo_request()
        else:
            with open(args.input, encoding="utf-8-sig") as handle:
                request = json.load(handle)
        print(json.dumps(evaluate(request), indent=2, allow_nan=False))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Evaluation failed: {exc}\n")
