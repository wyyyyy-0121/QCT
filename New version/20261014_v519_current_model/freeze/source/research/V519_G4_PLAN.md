# G4 Round Plan

This plan is recorded in advance; implementation/execution begins after G3 and
API compatibility tests pass. The goal is the original 13-cell true-dependency
engineering milestone, not a new easy-case selection.

1. Freeze the 12-workbook matrix: product/ratio/weighted, pair/chain, seeds
   engineering-0/engineering-1, 13 binary candidate cells each (8192 states).
2. Use the G1 independent business-arithmetic generator without modifications.
   Recompute both complete rankings; run V518 and V519 at their unchanged default
   node/leaf/preparation limits. Record the one-call initial-preparation accounting
   difference and component-node units rather than implying identical CPU work.
3. Run actual V516 exhaustive reference with 8192 evaluations per comparison.
   This is a separately funded oracle, not the budgeted baseline.
4. Require all 12 workbooks to improve on both backends: V518 budget refusal,
   V519 complete unique correct group, full-domain oracle agreement and successful
   independent replay. Require zero ranking/candidate changes and unsafe groups.
5. Save all inputs, predictions, reference audits, timing, hashes and results.
   Backend duplicates remain 24 comparisons of 12 workbooks.
6. Record the result before writing/executing the G5 development/confirmation
   plan. A failed case remains in the result; do not select replacement seeds.
