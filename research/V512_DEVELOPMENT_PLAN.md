# V5.1.2 development and validation plan

Status: implementation and validation in progress. Historical V5.1.1 sources,
model locks, and results remain historical evidence, not a general safety claim.

## Requirements

1. Reject header-only reconstruction of legal discounted revenue and uniform columns.
2. Provide a header-independent structural detection path with row/column regions.
3. Bind acceptance to the proposed template's actual anchors; reject candidate ties.
4. Accept a group only when every member independently passes; use full hashed IDs.
5. Preserve literals, function families, and expression topology in automatic
   acceptance; more complex changes receive a review proposal, not an accepted repair.
6. Score actual all-correct groups, with unsafe groups counted in every workbook.
7. Verify metadata, every prediction shard, identities, complete rankings, and both runs.
8. Freeze sources, parameters, and scoring gates before inspecting held-out outcomes.
9. Validate unseen formula/layout families and all 30 included existing Enron events.

## Evaluation scope fixed before outcome inspection

Development fixtures: product/revenue, legal discounts, neutral additions,
function exceptions, absolute references, vertical/horizontal copy patterns,
atomic-group failure, candidate ties, and protocol tampering.

Held-out structure fixtures: weighted formulas, tax-like arithmetic, ratios,
cross-sheet references, range aggregates, and horizontal projections. Include
singletons, blocks, majority-corrupted columns, no-anchor ambiguity, legal
exceptions, and regime changes. Fixtures are serialized workbook contents, not
independently sourced natural spreadsheets. The same project authors them;
this is a held-out stress evaluation, not independent third-party certification.

Real workbooks: the existing Enron manifest's included events (expected 30 in
25 workbooks). Prediction receives workbook data only. Scoring reports event
MRR, AP, hit@1/5/10, parser coverage, and emitted candidate counts. Existing
position labels do not establish complete clean-cell truth or correct repair
formulas. Safety and exact-repair precision are unavailable on this corpus.
These workbooks were used historically in this project, so results are retrospective.

New synthetic gates: control candidate FPR <= 10%; ambiguity candidate rate <=
10%; actual group precision >= 95%; unsafe accepted groups in all workbooks = 0;
exact coverage on repair-designated cases >= 50%. No-acceptance is undefined
precision, not 100%. Passing gates is not production promotion.

No threshold changes in response to held-out outcomes. Any later changes require
a new source lock and a new evaluation version. Negative findings are deliverables.

## Known limits to measure

An internally uniform erroneous column with no independent reference is not
identifiable from copy consistency alone. Correctly abstaining on that case must
not be reported as successful repair. Supported repair-designated majority-error
cases remain in the coverage denominator even if the method abstains.

Unknown syntax, legitimate expression changes, missing two-sided anchors, and
ambiguous regions remain observable review/abstention outcomes. Diagnostic scores
are not calibrated probabilities. Independent calibration and broader natural
repair truth are future requirements before automatic workbook edits.
