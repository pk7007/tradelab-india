# Open-source benchmark study — 23 November 2026

## Purpose and method

Identify **transferable repository presentation and developer-experience patterns** for TradeLab India. This is not a source-code quality audit or a claim that TradeLab matches the projects below.

On 23 November 2026, public GitHub repository metadata was checked for the following 15 repositories. Current README structures were also inspected for **Freqtrade, NautilusTrader, TradingAgents, Microsoft Qlib, OpenAlgo, FastAPI and Backstage**. Other entries are **metadata-only references** and must not be presented as deeply reviewed. GitHub stars are deliberately excluded as a quality score.

| Repository | Reference area | Inspection level | Candidate lesson for TradeLab |
| --- | --- | --- | --- |
| [QuantConnect Lean](https://github.com/QuantConnect/Lean) | Multi-language trading engine | Metadata | Clearly separate engine scope from strategy performance |
| [Freqtrade](https://github.com/freqtrade/freqtrade) | Trading bot documentation | README | Prominent disclaimer, features, quick start and support paths |
| [Hummingbot](https://github.com/hummingbot/hummingbot) | Trading automation ecosystem | Metadata | Study the separation of operations, connectors and strategies later |
| [Backtrader](https://github.com/mementum/backtrader) | Backtesting | Metadata | Contrast deterministic replay with market-readiness claims |
| [Zipline Reloaded](https://github.com/stefan-jansen/zipline-reloaded) | Python backtesting | Metadata | Make evaluation inputs, assumptions and reproducibility visible |
| [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | Event-driven architecture | README | Link conceptual architecture, setup, examples, security and versioning |
| [Jesse](https://github.com/jesse-ai/jesse) | Trading workflows | Metadata | Assess first-run usability and examples in a future deeper study |
| [VectorBT](https://github.com/polakowo/vectorbt) | Quantitative research | Metadata | Separate bulk research tooling from execution guarantees |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | Multi-agent research | README | Explain the distinct analyst/decision roles and their handoffs |
| [FinRL](https://github.com/AI4Finance-Foundation/FinRL) | Financial reinforcement learning | Metadata | Require research baselines and out-of-sample evidence before claims |
| [Microsoft Qlib](https://github.com/microsoft/qlib) | Quant research workflows | README | Surface a coherent research workflow before advanced options |
| [vn.py](https://github.com/vnpy/vnpy) | Trading systems | Metadata | Compare modular extensibility in a future detailed review |
| [OpenAlgo](https://github.com/marketcalls/openalgo) | India-focused open-source trading ecosystem | README | Offer clear feature taxonomy, onboarding links and broker boundaries |
| [FastAPI](https://github.com/fastapi/fastapi) | Developer documentation | README | Use a short, reproducible first example with links to deeper docs |
| [Backstage](https://github.com/backstage/backstage) | Developer experience | README | Maintain a short landing page with separate onboarding, governance and security paths |

## Findings grounded in the inspected READMEs

1. **A first-time reader needs a route, not a document dump.** The inspected projects tend to surface their purpose, quick start, capabilities and deeper documentation directly from the README.
2. **Names and trust boundaries matter.** The TradingAgents README distinguishes agent roles; TradeLab should distinguish *implemented handlers*, *optional research context* and *unconnected AI proposals*.
3. **Usability includes safe setup.** Freqtrade and NautilusTrader give new readers a visible path from explanation to installation and development guidance. TradeLab should provide an offline demo that needs no brokerage key.
4. **Architecture should be explainable.** TradeLab's simulation, research, local data and optional broker reads need a concise conceptual picture linked to the detailed capability map.
5. **Don't copy a feature list into a claim of parity.** The referenced projects target different markets, architectures and maturity levels; TradeLab is a local single-user prototype with live dispatch locked.

## Proposed changes, acceptance evidence and priority

| Priority | TradeLab gap | Recommended change | Verification |
| --- | --- | --- | --- |
| P1 | Strong README, but entry points are dense and technical | Add a short capability/status summary, portfolio tour and developer setup | Every linked page exists; a new reader can find the synthetic demo without credentials |
| P1 | Some docs imply live dispatch is unlockable by a flag | Make safety statements consistent with the current server-side lock | README, security and contributor docs agree |
| P1 | Product brief is a historical MVP snapshot | Label its historical scope and link to current capability map | Reader can distinguish past proposals from shipped functions |
| P2 | No verified screenshot set or short demo recording is checked in | Capture genuine synthetic-demo visuals and a sanitized demonstration | Media depicts actual UI and never exposes private broker data |
| P2 | No LICENSE file was observed at the repository root | Owner chooses and adds an appropriate license after reviewing third-party obligations | LICENSE exists and contributor terms are explicit |
| P2 | Limited independent user testing | Run fresh-install and contributor onboarding tests on supported platforms | Commands, logs and user observations are recorded |

## Evidence and limits

The GitHub metadata check confirmed the named repositories and their public descriptions/maintenance timestamps on the review date. README-level observations are restricted to the seven explicitly inspected projects. This report **does not** inspect all source code, test suites, security findings, CI execution history or release processes of the references; do not infer 9/10 quality from their popularity.

TradeLab's own [22 November engineering assessment](full-audit-2026-11-22.md) and [feature map](feature-status.md) remain the source of truth for current functionality. External license terms differ (including copyleft-licensed projects); reuse ideas, not code or assets, without an explicit license review.
