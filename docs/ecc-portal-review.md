# ECC-guided portal review — 19 November 2026

Used the installed ECC guide and code-reviewer checklist: inspect callers, reproduce concrete failures, prioritize money/data correctness and verify fixes. This was a code/test review, not an ECC-hosted external service or live broker audit.

## Confirmed fixes

- Duplicate news with future availability could overwrite an eligible article's availability metadata, producing a negative age. A failing regression reproduced it; eligible source records are now filtered against the research cutoff before restoring timestamps.
- Saving lower limits left old candidate quantities displayed. Candidate results are now invalidated when the saved settings revision changes. A JavaScript VM regression exercises the actual display function.
- The paper warning hardcoded ₹25 after editable settings changed. It now refers to the portal planning limit without misrepresenting a configured value. The engine still lacks per-trade protective stops.

150 Python tests pass, including two added portal regressions. Existing JavaScript regressions and portal syntax pass. `scripts/loss_audit.py` was rerun with invented data; base-cost final holdout remains 1.079% for SMA versus 2.319% for holding, with only two completed trades. This does not measure real Indian-market returns.

## Assessment

Subjective evidence-based readiness scores (not a probability of profit): research/paper prototype 5/10; autonomous real-money operation 2/10; demonstrated profitable edge unproven and not rateable. Five means usable within explicit offline boundaries; two means foundational code exists but critical integrations are absent. No overall 9/10 claim is justified.

The main gaps remain continuous permitted inputs, real forward observations, fundamental/valuation research, matched evaluation/paper sizing, authoritative broker funding and ownership, intraday square-off and protective exits. Existing paper accounts permit overnight positions and do not enforce the portal per-trade planning threshold. Live dispatch remains locked. Profitable operation cannot be inferred from passing software tests or UI quality.

Changes remain local; no credential inspection, real order or GitHub publication occurred. The review does not certify all security properties or every browser workflow.
