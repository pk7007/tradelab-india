# Decision log and roadmap

## Decisions

| Date | Decision | Reason/status |
| --- | --- | --- |
| 2026-10-31 | Treat TradeLab India as a simulation and research product | No live orders, broker connection, financial advice, profit promises, or regulatory approval claims |
| 2026-10-31 | Initially defer application stack | Superseded by owner request for a local Zerodha connector |
| 2026-10-31 | Leave the license undecided | Project owner must choose; no license file is included |
| 2026-10-31 | Gate digest automation pending source review | Public feeds and copyright terms do not by themselves settle reuse permission |
| 2026-10-31 | Owner changed scope to a local Zerodha Kite Connect app | One broker first; manual orders only, server-side secrets, live submission disabled by default |

## Phased roadmap and responsibilities

| Phase | Work | Primary responsibilities |
| --- | --- | --- |
| 0. Product framing | Brief, boundaries, risks, decisions | Product Manager, Compliance Reviewer |
| 1. Research | Interviews, alternatives, evidence and assumptions | Product Manager, Designer, Researcher |
| 2. Prototype | Synthetic-data flow, task comprehension and iteration | Designer, Product Manager |
| 3. Simulation MVP | Replay, hypothetical plans, costs, journal | Frontend, Backend, Quant Researcher |
| 4. Data verification | Rights, timestamps, quality, reproducibility | Data Engineer, Quant Researcher, QA/Reliability |
| 5. Trust and polish | Accessibility, privacy, failure states, documentation | Designer, Security, QA/Reliability |
| 6. Portfolio case study | Actual research, decisions, findings, limitations | Product Manager, all responsibility areas |
| 7. Weekly digest | Reviewed source registry and linked summaries | Backend/Data, Product Manager, Compliance Reviewer |
| 8. Broker expansion / deployment | Review broker terms, current exchange requirements, security and qualified compliance before each expansion or any hosted service | Product, Security, Compliance Reviewer |

For a solo project, these are responsibilities, not evidence of a staffed or certified team. Record unresolved decisions as they arise; do not invent research results.

## Owner decision: commit attribution (23 November 2026)

The repository owner asked that GitHub not show Claude as a contributor. Coding agents commit under the owner's own git identity and add no co-author, session or other AI attribution lines to commit messages or pull request text. Commits `9c3333e`, `7bf32ca` and `2128aa3` follow this; the first two were rewritten with the owner's approval and a force-with-lease push of that unmerged branch.

## Continuation audit (23 November 2026, evening)

See `docs/continuation-audit-2026-11-23.md`. Two offline-reproduced defects were fixed: the AI news
completer sent `temperature`, which the pinned SDK rejects (every enabled call failed), and
`ResearchRiskGate.kill()` could emit an infinite merged exit quantity. The autobahn advisories
pinned by `kiteconnect==5.2.2` are reported, not suppressed or upgraded; accepting or mitigating them is an owner decision pending an upstream release.
