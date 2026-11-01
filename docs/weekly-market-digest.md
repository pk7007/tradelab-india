# Weekly market digest

## Purpose and editorial rules

Provide a short, neutral index to noteworthy public-source updates relevant to the project. Every entry links to the original. The digest is informational and must not include financial recommendations, predictions, strategy suggestions, sensational wording, or full article text.

## Source review and workflow gates

Candidate endpoints are listed in `data/digest-sources.json`; all start disabled pending review of current source terms and endpoint behavior. RSS access does not itself grant republication rights. The workflow must remain gated until the owner reviews sources and confirms repository readiness.

- Manual dispatch requires `confirm_sources_reviewed=true`.
- Scheduled runs require repository variable `ENABLE_WEEKLY_DIGEST=true`.
- The weekly schedule is Monday 03:30 UTC, approximately Monday 09:00 IST (UTC+05:30). GitHub Actions uses UTC and may delay scheduled runs.
- The workflow writes `updates/YYYY-MM-DD.md` and `updates/README.md`, and commits only when generated files change. It does not publish externally.

## Content and reliability

Use feed metadata and only short excerpts explicitly permitted by source terms. Keep title, publisher, short neutral summary, publication date, category, and source link. Deduplicate by canonical URL or stable source ID. Report empty weeks and fetch/parse errors visibly in the digest and workflow logs. Do not silently drop failures. Keep credentials out of the workflow.

## Review checklist before enabling

1. Confirm each source's official endpoint, current terms, allowed automated access, excerpt limits, and attribution requirements.
2. Enable only sources with documented permission; otherwise omit them.
3. Inspect a manually triggered sample digest and the workflow permissions/commit behavior.
4. Confirm the repository is ready and set the schedule gate deliberately.
