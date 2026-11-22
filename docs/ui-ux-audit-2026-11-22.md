# UI and UX audit

22 November 2026. Reviewed the Auto Trading home page, Settings, news, evaluation,
paper imports/account setup and the advanced control room through source
inspection and the connected in-app browser. No trading controls or saved
financial settings were submitted during the audit.

## Changes delivered

| Finding | Change | Evidence |
| --- | --- | --- |
| News displayed long UTC timestamps and mixed publication with research availability. | Publication uses Today, Yesterday or a short date followed by a twelve-hour IST time. Collection and research availability retain their own labels. | Browser showed Published Today, 12:10 PM IST and Published Yesterday, 3:09 PM IST. Regression covers the IST midnight boundary, offsets, old dates and unavailable times. |
| Source retry schedules, mapping and categories dominated the news reading flow. | Headline, publisher, summary and publication time form the basic card. Source health and per-item research details are disclosures. | Connected browser verified both simplified cards and available details. |
| Setup explanations and calendar version strings repeated on the main session view. | Grouped broker/data readiness, advisory context, calendar and role details under Session setup and diagnostics. | Home browser snapshot shows controls, saved limits and account information before optional diagnostics. |
| Idle sessions displayed an entry-review placeholder without an entry to inspect. | Show entry review when a session is enabled or an actual review exists. | Source conditions retain actual review outcomes and active waiting states. |
| Trade history used raw UTC dates. | Applied the same IST presentation to main-page event times. | Browser showed 20 Nov 2026, 3:08 PM IST for the stored creation event. |
| Refreshes could close news details or lose keyboard focus. | Preserve expanded news details and focused links/summaries across successful refreshes. Failed refreshes remove stale headlines and return focus to Refresh news. Preserve expanded session disclosures. | Regression checks failure focus recovery and stale removal. Success focus behavior inspected in source. |
| A broad live region covered frequently rebuilt account details. | Kept specific status regions and removed the whole overview live region. | Source inspection. Full assistive-technology acceptance remains pending. |
| Account selector used implementation terminology. | Renamed it Paper account / saved settings. | Verified in the connected browser. |

## Further changes recommended

These findings remain proposals. Their implementation needs a separate coherent
screen redesign and user acceptance rather than removing fields indiscriminately.

| Priority | Surface and issue | Recommended change |
| --- | --- | --- |
| P2 | Home contains ten equal-weight metrics, repeated account descriptions and machine terms such as disarmed and ingestion. | Give cash, net result, shares and remaining daily allowance the strongest emphasis. Keep active stop/target, pending exit and unresolved exposure visible. Put secondary accounting explanations behind account details. Use plain status labels. |
| P2 | The older News Monitor is an import tool and says its feed is disconnected while home news has a running collector. | Rename it Imported news analysis and provide a clear route to current Market news. Distinguish each tool's actual data source. |
| P2 | Home, advanced control room, trader suite and evaluation use different navigation and presentation conventions. | Use consistent names and a clear return to Auto Trading. Group secondary research tools under an advanced menu. |
| P2 | Paper account setup exposes multiple models, many fields and long operational paragraphs before account creation. | Introduce guided setup with a review step showing the selected model, budget and assumptions. Preserve existing accounts and deliberate model choices. |
| P2 | Calendar JSON, instrument tokens, raw state and research JSON are required in advanced workflows. | Offer validated pickers and file imports where a supported source exists. Retain raw inputs in advanced mode. |
| P2 | News can expand into a long list with repeated summaries and related articles. | Add a modest initial page size, more-headlines control and optional symbol/source filters. Preserve source attribution and revision distinctions. |
| P2 | Evaluation asks for technical units and timezone-aware input. | Keep short explanations beside fields and offer supported date/time inputs. Show a readable result summary before detailed evidence. |
| P2 | Settings has many independent operational sections. | Group limits and connection first, then collapse maintenance, agent controls and experiments into advanced settings. |
| P2 | Some non-news advanced timestamps remain raw. | Apply explicit IST formatting to human-facing labels while retaining exact source times in exports and evidence. |

## Verification and review limits

All eight JavaScript regression files passed, including the new news-time checks
and the updated stale-news/focus regression. Both edited scripts passed Node
syntax checks, and whitespace checks passed. Python behavior was not changed by
this UI batch, and the full Python suite was not rerun.

Browser inspection covered the connected home page, open Settings, live news
cards and the evaluation, paper-account, imported-news and advanced pages.
Financial settings and order controls were not submitted. Source inspection
covered the remaining shared trader-suite rendering. Individual tool workflows
were not exhaustively exercised. No formal WCAG conformance, screen-reader,
load, zoom or mobile-device acceptance claim is made.

Independent cleanup review scored 9/10 with no critical or high-severity issue.
The reviewer identified the failed-news-refresh focus issue, which was repaired
and regression-tested. Broader interface maturity was estimated at 7–7.5/10
because advanced screens remain technical and representative user acceptance
is incomplete. These are UI engineering judgments. Trading performance and
profitability were outside this audit.

The news timing and main-page cleanup are saved locally and were observed in
the running site. Further recommendations above remain pending.
