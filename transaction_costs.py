"""Versioned NSE resident-retail cost planning; never a live settlement authority."""
import datetime as dt
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP, localcontext
from types import MappingProxyType

VERSION = 'zerodha-nse-retail-2026-04-01-v1'
EFFECTIVE_FROM = dt.date(2026, 4, 1)
VERIFIED_THROUGH = dt.date(2026, 11, 22)
PAISE = Decimal('0.01')
RUPEE = Decimal('1')
ZERO = Decimal('0')
SOURCES = (
    'https://nsearchives.nseindia.com/content/circulars/FA73061.pdf',
    'https://nsearchives.nseindia.com/content/circulars/FATAX73524.pdf',
    'https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies',
    'https://zerodha.com/charges',
    'https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/how-is-the-securities-transaction-tax-stt-calculated',
)
# Fractions of turnover, not percentages. Exchange and IPFT are split so IPFT
# is not accidentally charged twice. Current NSE combined outflows are
# 307/183/3553 rupees per crore, including the 0.01 rupee IPFT contribution.
RULES = MappingProxyType({
    'equity-intraday': ('0.000030699', '0.00025', '0.00003'),
    'equity-delivery': ('0.000030699', '0.001', '0.00015'),
    'equity-futures': ('0.000018299', '0.0005', '0.00002'),
    'equity-options': ('0.000355299', '0.0015', '0.00003'),
})
IPFT_RATE = Decimal('0.000000001')
SEBI_RATE = Decimal('0.000001')
GST_RATE = Decimal('0.18')
BROKERAGE_RATE = Decimal('0.0003')
BROKERAGE_CAP = Decimal('20')


class UnsupportedCosts(ValueError):
    """The stated instrument, date or account needs an unverified charge rule."""


def _amount(value, name, *, low=ZERO, high=Decimal('1000000000000')):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError(name + ' must be an explicit decimal string, integer or Decimal.')
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError('Invalid ' + name + '.') from None
    if not result.is_finite() or not low <= result <= high:
        raise ValueError(name + ' outside supported numerical bounds.')
    return result


def _date(value):
    if type(value) is not str:
        raise ValueError('as_of must be an ISO calendar date.')
    try:
        day = dt.date.fromisoformat(value)
    except ValueError:
        raise ValueError('as_of must be an ISO calendar date.') from None
    if day.isoformat() != value:
        raise ValueError('as_of must use YYYY-MM-DD.')
    if not EFFECTIVE_FROM <= day <= VERIFIED_THROUGH:
        raise UnsupportedCosts('No source-verified schedule for this date; review a new version.')
    return day


def schedule_status(as_of):
    day = _date(as_of)
    return dict(version=VERSION, effectiveFrom=EFFECTIVE_FROM.isoformat(),
        verifiedThrough=VERIFIED_THROUGH.isoformat(), asOf=day.isoformat(),
        supportedExchange='NSE', supportedSegments=list(RULES),
        accountType='resident-individual', liveEligible=False,
        sources=list(SOURCES))


def estimate_order(order, *, as_of, slippage_bps, other_charges_including_tax,
                   dp_charge_including_tax=None):
    """Plan one executed order's aggregate fills, not each individual fill.

    price is per share/contract unit (option premium for equity-options);
    quantity is the full executed unit count, not number of lots.
    All nonstandard charges and slippage must be explicitly supplied.
    Partial fills sharing a broker order ID must be aggregated by the caller
    before applying the per-executed-order brokerage cap.
    """
    day = _date(as_of)
    if not isinstance(order, dict):
        raise ValueError('An explicit order mapping is required.')
    if order.get('costVersion') != VERSION:
        raise UnsupportedCosts('An explicit supported costVersion is required.')
    if order.get('exchange') != 'NSE' or order.get('accountType') != 'resident-individual':
        raise UnsupportedCosts('Only verified NSE resident-individual tariff is implemented.')
    segment = order.get('segment')
    if not isinstance(segment, str) or segment not in RULES:
        raise UnsupportedCosts('Segment tariff is unsupported.')
    if order.get('settlement') != 'normal-trade':
        raise UnsupportedCosts('Exercise, assignment, physical delivery and MTF costs are unverified.')
    side = order.get('side')
    if side not in ('BUY', 'SELL'):
        raise ValueError('Specify BUY or SELL.')
    quantity = order.get('quantity')
    if type(quantity) is not int or not 1 <= quantity <= 1000000000:
        raise ValueError('quantity must be a positive whole unit count.')
    price = _amount(order.get('price'), 'price', low=Decimal('0.00000001'))
    slip = _amount(slippage_bps, 'slippage_bps', high=Decimal('1000'))
    other = _amount(other_charges_including_tax, 'other_charges_including_tax')
    if segment == 'equity-delivery' and side == 'SELL':
        if dp_charge_including_tax is None:
            raise UnsupportedCosts('Delivery sell requires an explicit applicable DP debit charge.')
        dp = _amount(dp_charge_including_tax, 'dp_charge_including_tax')
    else:
        dp = ZERO if dp_charge_including_tax is None else _amount(dp_charge_including_tax, 'dp_charge_including_tax')
        if dp != ZERO:
            raise ValueError('DP charge applies only to equity-delivery sells in this model.')
    with localcontext() as context:
        context.prec = 40
        turnover = price * quantity
        exchange_rate, stt_rate, stamp_rate = map(Decimal, RULES[segment])
        brokerage = (ZERO if segment == 'equity-delivery' else BROKERAGE_CAP
                     if segment == 'equity-options'
                     else min(BROKERAGE_CAP, turnover * BROKERAGE_RATE))
        exchange = turnover * exchange_rate
        ipft = turnover * IPFT_RATE
        sebi = turnover * SEBI_RATE
        stt = turnover * stt_rate if side == 'SELL' or segment == 'equity-delivery' else ZERO
        stamp = turnover * stamp_rate if side == 'BUY' else ZERO
        gst = (brokerage + exchange + ipft + sebi) * GST_RATE
        raw = dict(brokerage=brokerage, stt=stt, exchange=exchange, ipft=ipft,
                   sebi=sebi, gst=gst, stampDuty=stamp, slippage=turnover*slip/10000,
                   otherChargesIncludingTax=other, dpIncludingTax=dp)
        modeled = {key: value.quantize(RUPEE if key == 'stt' else PAISE,
                                       rounding=ROUND_HALF_UP)
                   for key, value in raw.items()}
        reserved = {key: value.quantize(RUPEE if key == 'stt' else PAISE,
                                       rounding=ROUND_CEILING)
                    for key, value in raw.items()}
        return dict(version=VERSION, asOf=day.isoformat(), exchange='NSE',
            segment=segment, side=side, quantity=quantity, turnover=turnover,
            rawComponents=raw, components=modeled, reserveComponents=reserved,
            total=sum(modeled.values(), ZERO), reserveTotal=sum(reserved.values(), ZERO),
            estimateOnly=True, liveEligible=False, executionAllowed=False,
            assumptions=[
                'One executed order after aggregating all of its fills.',
                'Presentation rounds each line half-up; STT to rupee, others to paise.',
                'Broker contract-note aggregation and minimum charges are not reproduced.',
                'Risk reserve rounds each nonnegative line upward; it can overestimate.',
                'Delivery sell DP and all other nonstandard charges are explicit caller inputs.',
                'Rate verification is limited to the schedule date range.',
            ])


def require_live_eligible(result):
    """Cost estimates alone cannot certify a strategy or live order."""
    raise UnsupportedCosts('Broker settlement reconciliation and live cost promotion remain unverified.')
