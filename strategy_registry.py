"""Which strategies may run where. Metadata only: it grants no authority and changes nothing.

A strategy becomes selectable for a PAPER account only through the paper engine's own validation
(`paper.PaperEngine.create`) and the owner's explicit account creation and start approval. This registry
records the current status so the gap is visible and tested; it never promotes, enables or starts anything.
"""
RESEARCH_BLOCKERS = (
    'The paper engine entry check (entry_review, paper, intraday_contract) is hard-wired to the SMA 5/20 rule.',
    'The engine resets its candle history every session; EMA50 needs 50 completed 5-minute bars (first defined '
    'about 13:25 IST), so little of the 14:30 entry window would remain.',
    'No walk-forward evidence on real, corporate-action-adjusted data exists; synthetic fixtures prove mechanics only.',
    'Owner approval is required to create and start a paper account with it; there is no automatic promotion.',
)

STRATEGIES = {
    'sma5-20-next-open-paper-v1': dict(status='paper', paperApproved=True, promoted=False, blockers=()),
    'intraday-v1': dict(status='paper', paperApproved=True, promoted=False, blockers=()),
    'ema20-50-adx14-cross-v1': dict(status='research-only', paperApproved=False, promoted=False,
                                    blockers=RESEARCH_BLOCKERS + ('Entry-only module: no exit rule or sizing.',)),
    'ema20-50-adx14-intraday-5m-v1': dict(status='research-only', paperApproved=False, promoted=False,
                                          blockers=RESEARCH_BLOCKERS),
}


def describe(name):
    entry = STRATEGIES.get(name)
    if entry is None:
        return dict(name=name, status='unknown', paperApproved=False, promoted=False,
                    blockers=('Unknown strategy version.',))
    return dict(name=name, **{**entry, 'blockers': list(entry['blockers'])})


def paper_allowed(name):
    """True only for strategies the paper engine already accepts. Never True for research-only ones."""
    info = describe(name)
    return info['paperApproved'] and info['status'] == 'paper', info['blockers']
