"""Bounded tick admission for viewing; never order or forward-fill authority."""
from collections import deque
import datetime as dt
import math

UTC = dt.timezone.utc


def finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError, TypeError):
        return False


class TickGuard:
    def __init__(self, token, *, max_age_seconds=15, future_tolerance_seconds=2):
        if type(token) is not int or token <= 0:
            raise ValueError('Invalid instrument token.')
        if (not finite_number(max_age_seconds) or not finite_number(future_tolerance_seconds)
                or not 0 < max_age_seconds <= 60 or not 0 <= future_tolerance_seconds <= 5):
            raise ValueError('Invalid tick freshness budget.')
        self.token = token
        self.max_age = max_age_seconds
        self.future = future_tolerance_seconds
        self.latest = None
        self.seen = set()
        self.history = deque()
        self.accepted = 0
        self.rejected = {}

    @staticmethod
    def sdk_stamp(value):
        if not isinstance(value, dt.datetime):
            raise ValueError('invalid-timestamp')
        # Kite 5.2.2 decodes these epoch fields with datetime.fromtimestamp:
        # naive values are host-local SDK wall time, not assumed India wall time.
        return value.astimezone(UTC)

    def reject(self, reason):
        self.rejected[reason] = self.rejected.get(reason, 0) + 1
        return None

    def observe(self, tick, received):
        if not isinstance(received, dt.datetime) or received.tzinfo is None:
            raise ValueError('Receipt time must be timezone-aware.')
        received = received.astimezone(UTC)
        if not isinstance(tick, dict) or type(tick.get('instrument_token')) is not int:
            return self.reject('invalid-instrument')
        if tick['instrument_token'] != self.token:
            return self.reject('wrong-instrument')
        price = tick.get('last_price')
        if not finite_number(price) or price <= 0:
            return self.reject('invalid-price')
        volume = tick.get('volume_traded')
        if volume is not None and (not finite_number(volume) or volume < 0):
            return self.reject('invalid-volume')
        try:
            exchange = self.sdk_stamp(tick.get('exchange_timestamp'))
            trade = self.sdk_stamp(tick['last_trade_time']) if tick.get('last_trade_time') is not None else None
        except (ValueError, OverflowError, OSError):
            return self.reject('invalid-timestamp')
        age = (received-exchange).total_seconds()
        if age < -self.future or (trade and (trade-received).total_seconds() > self.future):
            return self.reject('future-timestamp')
        if age > self.max_age:
            return self.reject('stale-exchange-time')
        if trade and trade > exchange + dt.timedelta(seconds=self.future):
            return self.reject('inconsistent-timestamps')
        if self.latest and exchange < self.latest:
            return self.reject('out-of-order')
        fingerprint = (exchange.isoformat(), trade.isoformat() if trade else None, price, volume)
        if fingerprint in self.seen:
            return self.reject('duplicate')
        self.seen.add(fingerprint)
        self.history.append(fingerprint)
        if len(self.history) > 1024:
            self.seen.remove(self.history.popleft())
        self.latest = exchange
        self.accepted += 1
        return dict(date=received.isoformat(), close=float(price),
                    exchangeTimestamp=exchange.isoformat(),
                    tradeTimestamp=trade.isoformat() if trade else None)

    def status(self):
        return dict(acceptedTicks=self.accepted, rejectedTicks=sum(self.rejected.values()),
                    rejectedByReason=dict(self.rejected), cacheEntries=len(self.history),
                    clockFutureToleranceSeconds=self.future, maxAgeSeconds=self.max_age,
                    executionAllowed=False)
