"""Provider-neutral research evidence checks. No network or execution capability.

Passing validation establishes schema/citation/time consistency, not the truth
of prose or a tradable edge. Evidence registries must be built by trusted import
adapters; a model must never supply its own registry.
"""
from dataclasses import dataclass
import math
import re
from urllib.parse import urlsplit

from research import timestamp


class ProviderUnavailable(RuntimeError):
    """Research cannot proceed without a selected, connected provider."""


@dataclass(frozen=True)
class DisconnectedResearchProvider:
    name: str = 'disconnected'

    def research(self, *_args, **_kwargs):
        raise ProviderUnavailable('No research provider is connected. No trade decision is produced.')


def _text(value, label, limit=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('Invalid ' + label)
    return value.strip()


def _stamp(value):
    try:
        return timestamp(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError('Evidence timestamps require a valid timezone-aware date.') from None


def validate_ai_research(output, evidence_registry, symbols, as_of, max_age_seconds):
    """Return copied, research-only content with trusted citation metadata.

    Schema: {symbol, status: research|no_trade, facts: [{text,citations}],
    inferences: [{text,citations}], missing: [text]}. Unknown fields, including
    orders/limits/confidence, are rejected. Prose is inert untrusted text: callers
    must render it as text and never execute it, treat it as settings, or turn it
    directly into an order. This checker does not infer semantic entailment.
    """
    keys = {'symbol', 'status', 'facts', 'inferences', 'missing'}
    if not isinstance(output, dict) or set(output) != keys:
        raise ValueError('Research output has unsupported or missing fields.')
    if not isinstance(symbols, (list, tuple, set, frozenset)) or not symbols or any(
            not isinstance(s, str) or not re.fullmatch(r'[A-Z0-9&-]{1,30}', s) for s in symbols):
        raise ValueError('Use a trusted exact-symbol allowlist.')
    if output['symbol'] not in symbols:
        raise ValueError('Unknown research symbol.')
    if output['status'] not in ('research', 'no_trade'):
        raise ValueError('Unknown research status.')
    if (isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, (int, float))
            or not math.isfinite(max_age_seconds) or max_age_seconds <= 0):
        raise ValueError('Specify a positive finite evidence age limit.')
    cutoff = _stamp(as_of)
    if not isinstance(evidence_registry, dict) or len(evidence_registry) > 10000:
        raise ValueError('Invalid trusted evidence registry.')
    trusted = {}

    def citation(identity):
        identity = _text(identity, 'citation ID', 128)
        record = evidence_registry.get(identity)
        if not isinstance(record, dict):
            raise ValueError('Citation does not exist in trusted evidence registry.')
        url = _text(record.get('url'), 'source URL', 2048)
        try:
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError()
            # Accessing port also rejects malformed port syntax.
            parsed.port
        except ValueError:
            raise ValueError('Evidence requires an HTTPS source without embedded credentials.') from None
        provider = _text(record.get('provider'), 'provider', 128)
        known_symbols = record.get('symbols')
        if not isinstance(known_symbols, list) or output['symbol'] not in known_symbols:
            raise ValueError('Citation is not attributed to the research symbol.')
        published, available = _stamp(record.get('publishedAt')), _stamp(record.get('availableAt'))
        information_time = max(published, available)
        if information_time > cutoff:
            raise ValueError('Citation was unavailable at the research cutoff.')
        # Old reporting is not refreshed merely by downloading it again today.
        if (cutoff - published).total_seconds() > max_age_seconds:
            raise ValueError('Citation is too old for this research policy.')
        trusted[identity] = dict(id=identity, url=url, provider=provider,
                                 publishedAt=published.isoformat(), availableAt=available.isoformat())
        return identity

    result = dict(symbol=output['symbol'], status=output['status'])
    for field in ('facts', 'inferences'):
        statements = output[field]
        if not isinstance(statements, list) or len(statements) > 30:
            raise ValueError('Research statements must be bounded lists.')
        copied = []
        for statement in statements:
            if not isinstance(statement, dict) or set(statement) != {'text', 'citations'}:
                raise ValueError('Statements require text and citations only.')
            sources = statement['citations']
            if not isinstance(sources, list) or not 1 <= len(sources) <= 10:
                raise ValueError('Each statement requires bounded source citations.')
            ids = [citation(identity) for identity in sources]
            if len(set(ids)) != len(ids):
                raise ValueError('Duplicate citation IDs.')
            copied.append(dict(text=_text(statement['text'], 'research statement'), citations=ids))
        result[field] = copied
    missing = output['missing']
    if not isinstance(missing, list) or len(missing) > 30:
        raise ValueError('Missing evidence must be a bounded list.')
    result['missing'] = [_text(item, 'missing evidence', 500) for item in missing]
    if result['status'] == 'research' and not result['facts']:
        raise ValueError('Research status requires sourced factual claims.')
    result.update(asOf=cutoff.isoformat(), sources=list(trusted.values()),
                  authority='research-only', executionAllowed=False,
                  verification='Schema, allowlist and evidence timing checked; semantic claims remain unverified.')
    return result
