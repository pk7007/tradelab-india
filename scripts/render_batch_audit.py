"""Write a private human-readable audit from previously saved evidence."""
import argparse
import hashlib
import json
from pathlib import Path


def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def render(batch, audit_folder, cas_folder, output):
    batch,audit_folder,cas_folder=map(Path,(batch,audit_folder,cas_folder))
    audit=load(audit_folder/'audit.json')
    cas=load(cas_folder/'results.json')
    quality=load(batch/'data-quality-audit-v1.1.json')
    d=audit['development']
    lines=['# TradeLab India — independent loss audit, 20 November 2026','',
           '**Decision: no candidate promoted; real broker writes remain disabled.**',
           'The original 1,000-trade loss is verified. Calendar and promotion defects were repaired in source. The running main server was not restarted and retains its earlier implementation. Its paper worker was last verified stopped, flat, with no pending intent or costs; existing capital/risk configuration was not changed.','',
           '## Reconciliation and original experiment','',
           f"Independently grouped {d['completedTrades']} closed round trips / {audit['uniqueEntries']} unique episode-entry sequences. All {len(audit['originalComparisons'])} original trial ledgers and fee identities match. All frozen replay fills reproduce exactly after the repairs. No original economic result changed.",
           f"Gross before fees/slippage ₹{d['grossPricePnl']:,.2f}; fees ₹{d['explicitFees']:,.2f}; modeled slippage ₹{d['modeledSlippage']:,.2f}; net ₹{d['netPnl']:,.2f}.",
           f"Win rate {d['winRatePct']:.1f}%; mean ₹{d['expectancy']:.2f}; profit factor {d['profitFactor']:.4f}; average win ₹{d['averageWin']:.2f}; average loss ₹{d['averageLoss']:.2f}. Mean hold {d['meanHoldingMinutes']:.2f} minutes. Turnover ₹{d['turnover']:,.2f}.",
           f"Descriptive session bootstrap 95% mean interval ₹{d['expectancySessionBootstrap95'][0]:.2f} to ₹{d['expectancySessionBootstrap95'][1]:.2f}; this is not adjusted for serial dependence or model selection.",
           'Capital resets: 28 independent ₹10,000 accounts, each 20 sessions. Summed P&L is NOT a continuous account return. Development ran 2023-01-02–2025-04-15 (560 session observations). Zero-trade episodes, open quantities and per-episode drawdowns are retained in audit.json; a fabricated portfolio drawdown across resets is not reported.',
           'The source freezes all five original variants before the comparisons and selects by validation return before opening the July final. There is no external timestamp/signature proving execution order: source logic and saved artifacts support it, not an independent audit log. The July final is now consumed.','',
           '## Calendar and source integrity','',
           f"{quality['rows']:,} rows / {quality['observedSessions']} observed dates: every observed CTS timestamp grid matches the attributed session profile. No duplicate, missing-in-observed-session, unexpected, malformed OHLC, negative or zero volume rows were detected. Entire absent days still require an independent full calendar.",
           'All 84 exclusions: 75 complete CAS weekday sessions, 3 complete weekend sessions, 2 split disaster-recovery sessions and 4 Muhurat sessions. The legacy fixed-75-bar filter caused the final to end in July, not a demonstrated provider truncation.',
           'Instrument INFY / NSE / 408065; 5-minute, explicit +05:30 / Asia-Kolkata timestamps. CSV hash matches the frozen policy. Raw CSV and metadata remain private and unchanged.',
           'CAS applicability is security-specific: for applicable stocks, continuous trading ends at 15:15 and the final candle starts at 15:10. The new experiment uses a separately labelled 15:10 square-off. The original account retains 15:15 and must not be resumed under a corrected 15:15-close calendar.',
           'The holiday-aware validation manifest explicitly includes published holidays and closed weekends; absent weekdays are rejected, never inferred closed from absent prices.',
           'Corporate-action adjustment remains unverified. Official Infosys filings confirm dividends including the June 2026 final dividend and November 2026 interim dividend; that does not prove Kite adjustment policy or a complete action inventory. No adjusted tape was invented. Intraday closes reset daily; all original closed-trade groups were flat, so no overnight dividend return is claimed.','',
           '## Timing and loss attribution','',
           'Signals use a preceding completed close and a later modeled candle open. Full candle volume determines participation and high/low determines protective exits; those facts are known only at candle completion. This is retrospective OHLC replay, including the current candle worker, rather than executable quote-based forward evidence.',
           f"Development reentry counts: `{json.dumps(audit['developmentChurn']['counts'],sort_keys=True)}`. Only four entries were bullish-state entries without a fresh crossover; 257 were the first eligible 20-close window. A fresh-cross restriction alone therefore has little direct support as a cure. There were 451 same-session reentries, largely following moving-average exits.",
           '753 completed-bar exits account for about −₹24,080 net; 238 square-off/recovery exits net about +₹129, six targets about +₹902, three protective exits about −₹364. Costs overwhelm the small gross development edge. Validation gross results are also negative, so a weak signal is an additional confirmed issue. Sizing changes under cost stress mean that stress P&L differences are not solely a fee subtraction.',
           'No point-in-time market-regime series was supplied. Per-year, per-hour and exit-reason aggregates and examples are retained; a causal regime explanation remains untested. The 84 excluded sessions were complete, so “remove suspicious prices” is not a justified repair. Performance changes from calendar inclusion are shown on a different dated period and cannot be attributed solely to calendar code.','',
           '## Comparisons','',
           'Amounts are rupees. Gross excludes slippage and fees; fee and slippage columns are separate. Every non-development row starts with ₹10,000; development is 28 independent resets. Every row is rejected for promotion. Intervals are descriptive mean-net-per-trade session bootstrap ranges.','',
           '| Trial | Dates | Trades | Gross | Fees | Slippage | Net | Max DD % | Mean interval |',
           '|---|---|---:|---:|---:|---:|---:|---:|---|']
    def row(name,dates,r,dd):
        interval=r['expectancySessionBootstrap95']
        ci='unavailable' if interval[0] is None else f"{interval[0]:.2f} to {interval[1]:.2f}"
        drawdown='unrecorded' if dd is None else f'{dd:.2f}'
        lines.append(f"| {name} | {dates} | {r['completedTrades']} | {r['grossPricePnl']:.2f} | {r['explicitFees']:.2f} | {r['modeledSlippage']:.2f} | {r['netPnl']:.2f} | {drawdown} | {ci} |")
    dd=max(r['maxDrawdownPct'] for r in audit['originalComparisons'] if r['stage']=='development')
    row('Original development (max episode DD)','2023-01-02–2025-04-15',d,dd)
    row('Frozen replay after source repairs (same fills)','same 28 reset episodes',d,dd)
    for r in audit['originalComparisons']:
        if r['stage']!='development':row(r['stage']+' / '+r['variant'],'–'.join(r['sessions']),r,r['maxDrawdownPct'])
    for r in audit['exploratory']:
        row('Exploratory old validation / '+r['name'],'–'.join(audit['originalComparisons'][28]['sessions']),r,r['maxDrawdownPct'])
    dates=cas['registration']['validationDates']
    for r in cas['validation']:row('CAS / '+r['name'],dates[0]+'–'+dates[-1],r,r['maxDrawdownPct'])
    row('CAS selected candidate, doubled cost stress',dates[0]+'–'+dates[-1],cas['stress'],cas['stress'].get('maxDrawdownPct'))
    lines += ['', 'The doubled-cost stress trial also fails positive expectancy; all unresolved quantities and ledger checks remain explicit in the saved results.',
              'Three exact entry/exit candidates were registered before their comparisons. No fresh-cross, cooldown, news or volatility model was silently added to the active strategy. Multiple related comparisons and prior development exposure mean these results remain exploratory; there is no 9/10 profitability claim.',
              f"CAS reserve: {cas['registration']['reservedDates'][0]}–{cas['registration']['reservedDates'][-1]}, hash `{cas['registration']['reservedSha256']}`. No strategy outcome was evaluated on that reserve; all candidates failed validation first. Price-shape inspection is disclosed and this is not claimed to be an externally blinded holdout. An independent review must resolve the special-session calendar before any later reserve evaluation.",
              'The 15:10 CAS comparison is a new dated safety assumption, not a relabelled original baseline. The previous July final remains consumed.','',
              '## Fees and official references','',
              'The frozen 10 bps per side fee and 5 bps per side slippage are scenario assumptions. Current Zerodha intraday equity brokerage is 0.03% or ₹20 per executed order (lower), with separate STT, exchange charges, SEBI fees, GST and buy-side stamp duty. The report retains the original scenario, half-cost/double-cost reruns, and a separately labelled current-tariff fixed-fill counterfactual. Current tariffs are not retroactively certified for 2023–2026; contract-note rounding, subscription and incident costs remain excluded.',
              '- [Zerodha charges, checked 20 November 2026](https://zerodha.com/charges/)',
              '- [NSE CAS trading rules](https://www.nseindia.in/static/products-services/closing-auction-session)',
              '- [2026 NSE holiday circular, issued 12 December 2025](https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf)',
              '- [Infosys April 2026 dividend filing](https://www.infosys.com/investors/documents/exchange-filings/2026/outcome-board-meeting-23apr2026.pdf)',
              '- [Infosys October 2026 dividend filing](https://www.infosys.com/investors/documents/exchange-filings/2026/outcome-board-meeting23oct2026.pdf)',
              'Per-special-session circular links, timestamps and hashes are in the quality report.','',
              '## Confirmed defects and implemented fixes','',
              '- Calendar-aware ingestion now accepts complete 72-candle CTS sessions, validates bounds, and rejects omitted whole open days, unknown dates, gaps and revised bars. Worker arm rejects exits at/after close. Existing no-calendar accounts retain compatibility.',
              '- The legacy batch runner now refuses the silently truncated 72-bar partition rather than producing an unnoticed stale final window.',
              '- Final evidence cannot reuse shifted final windows or earlier validation exposure. Exposure reservations survive failed runs and restarts; ambiguous legacy exposure fails closed.',
              '- Paper promotion requires profitable candidate-specific executable quote evidence, receipts and equity marks, not candle receipt counts or losing baseline history. Current quote execution producer is absent, so production promotion stays blocked.',
              '- Evaluation fingerprints bind supplied calendars and report implementation hashes. Worker diagnostics retain safe failure codes and stages without provider text. The exact historical 13:25 failure is unrecoverable; a candle revision remains only a hypothesis.',
              '- Fixed numeric validation mistakenly applied to calendar timestamps, Windows database-test connection cleanup, and isolated news/cache paths in the HTTP restart drill.','',
              '## Verified causes of losses','',
              '- Costs and turnover outweigh the development gross gain; validation also loses before costs.',
              '- Moving-average exits dominate realized losses; every tested entry-hour group loses.',
              '- Changing target distance alone produced identical original validation fills; no target-based remedy established.','',
              '## Unresolved limitations','',
              '- OHLC fills do not prove real executable entries, stops, latency or available liquidity. Automated quote-based paper execution and candidate shadow observation are still missing.',
              '- Complete corporate-action/price adjustment verification, point-in-time universe and matched sector/regime research are absent.',
              '- Main backend still runs earlier code; no real-money activation or silent account rewrite occurred. Supervisor automation update could not be verified because the automation service was unavailable.',
              '- Future final evidence must remain reserved until rules and independent review are complete; descriptive bootstraps alone cannot justify promotion.','',
              '## Candidate decisions','',
              '- All original five configurations and all three new entry/exit variants: rejected. Smaller losses do not meet positive-expectancy requirements.',
              '- Noon entry on CAS validation lost least (about ₹909) but still failed expectancy, uncertainty and doubled-cost stress; no final opening or promotion.',
              '- Fresh crossover/cooldown/trend/news changes: not implemented as profit fixes without supporting evidence.','',
              '## Exact owner actions','',
              '- Keep the current paper worker stopped and live execution locked. Do not re-arm its old 15:15 square-off under the corrected 15:15 close.',
              '- Review a separate calendar-safe experimental account/configuration with unchanged ₹10,000 / ₹250 / ₹1,000 risk limits before activation. Earlier square-off is a new recorded choice, not an automatic change to the current account.',
              '- Restart the main backend to load reviewed source changes, then reconnect Zerodha if the session is lost. Verify the scheduled supervisor uses the corrected calendar and does not re-arm the old account; its update was not confirmed.',
              '- Supply/confirm provider adjustment documentation and retain private data locally. No additional AI API or Moneycontrol key is needed for the completed audit.',
              '- Require quote-based forward simulation implementation and candidate-specific positive evidence before reconsidering promotion. No candidate currently merits risking real funds.','',
              'Verification: 317 Python tests and all six JavaScript test files passed; isolated HTTP restart/disconnect/gap/duplicate/reconciliation drill passed with temporary databases and zero broker orders. Earlier interim artifacts are preserved; current evidence paths follow.','',
              f'- Original: `{batch}`',f'- Fill audit: `{audit_folder}`',f'- Calendar experiment: `{cas_folder}`',
              'Raw candles, credentials and private ledgers are not included in repository changes. This audit is not a GitHub push.']
    source_root=Path(__file__).resolve().parents[1]
    sources=['paper.py','paper_worker.py','intraday_evaluation.py','intraday_contract.py',
             'strategy_contract.py','strategy_lab.py','agent_handlers.py','scripts/batch_loss_audit.py',
             'scripts/cas_research_batch.py','scripts/data_quality_audit.py','scripts/render_batch_audit.py']
    manifest={name:hashlib.sha256((source_root/name).read_bytes()).hexdigest() for name in sources}
    lines += ['', '## Source and regression evidence', '']
    for name in ['docs/loss-audit-implementation.md']+sources+[
            'tests/test_loss_audit_regressions.py','tests/test_worker_loss_regressions.py',
            'tests/test_loss_accounting.py','tests/test_calendar_evaluation.py','tests/test_data_quality_audit.py']:
        lines.append(f'- [{name}]({(source_root/name).as_posix()})')
    with Path(output).with_suffix('.source-hashes.json').open('x',encoding='utf-8') as file:
        json.dump(dict(scope='Source snapshot at report rendering, not a signed execution attestation',sha256=manifest),file,indent=2)
    with Path(output).open('x',encoding='utf-8') as file:file.write('\n'.join(lines)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ('batch','audit','cas','output'):p.add_argument('--'+flag,required=True)
    a=p.parse_args();render(a.batch,a.audit,a.cas,a.output)
