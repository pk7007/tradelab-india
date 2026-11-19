"""Shared completed-close signal and assumed fill contract; no execution authority."""
import math

VERSION = 'sma5-20-next-open-v1'


def target_long(closes):
    """Only completed closes may be supplied; the result applies to the next open."""
    return len(closes) >= 20 and math.fsum(closes[-5:]) * 4 > math.fsum(closes[-20:])


def assumed_fill(opening, units, side, fee_bps, slippage_bps):
    """Full-fill model. Caller controls sizing and rejects unavailable liquidity."""
    if side not in ('BUY', 'SELL'):
        raise ValueError('Unsupported fill side.')
    values = (opening, units, fee_bps, slippage_bps)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError('Invalid modeled fill inputs.')
    if opening <= 0 or units < 0 or int(units) != units or not 0 <= fee_bps <= 1000 or not 0 <= slippage_bps <= 1000:
        raise ValueError('Modeled fill outside supported range.')
    price = opening * (1 + slippage_bps / 10000 if side == 'BUY' else 1 - slippage_bps / 10000)
    return price, units * price * fee_bps / 10000
