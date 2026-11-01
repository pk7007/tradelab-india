# Metrics and events

## Principles

Collect the minimum data needed to evaluate usability and reproducibility. Prefer aggregate, consented prototype research. Do not collect broker credentials, account tokens, OTPs, UPI PINs, or private customer information.

## Candidate product measures

| Measure | Definition | Guardrail |
| --- | --- | --- |
| Replay task completion | Participants who reach the requested replay state | Report sample size and task wording |
| Assumption comprehension | Participants who correctly explain the shown simulation limits | Do not treat as investment knowledge certification |
| Provenance discovery | Participants who locate source and quality information | Record task context |
| Run reproducibility | Same versioned inputs produce same stored output | Define numerical tolerances before implementation |
| Review completion | Participants record and revisit a hypothetical decision | No performance or profit target |

These are proposed measures; no baseline or result exists yet.

## Candidate event schema

If telemetry is later justified, use minimal events such as `replay_started`, `replay_completed`, `plan_saved`, `review_opened`, and `assumptions_viewed`. Use pseudonymous identifiers, avoid free-text journal content, and document purpose, retention, consent, and deletion controls before collection.

## Prohibited analytics

Do not infer investment suitability, risk tolerance, or profitability from usage. Do not send journal text or personal financial records to third-party analytics.
