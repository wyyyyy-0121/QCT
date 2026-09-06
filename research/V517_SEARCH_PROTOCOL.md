# V5.1.7 development: complete candidate-space scaling

## Scope

Keep the V516 domain exactly: direct approved aggregate-member cells with bounded
V514 edge proposals, signature deduplication, and the no-change option. Keep the
entire V4 or V511 localization tuple, scores, evidence, and candidate portfolio.
No default ranker replacement, workbook edits, or changes to frozen model sources.

The first milestone is multiple unique cases beyond 256 assignments, with the
same domains and solutions checked by the existing V516 exhaustive implementation.
Then measure 24 and 32 candidate cells, including unfavorable search structures.
This is engineering/development evidence, not new independent confirmation or
real-business safety evidence. Historical confirmation data are regression only.

## Mechanism and proof

Build the union of original and candidate reference graphs. Bound optimization
requires each aggregate member's value to depend on no other candidate variable,
including through unchanged formula cells. A cycle back to a candidate also fails
this check. Validate every option with the existing completeness-aware evaluator.

The first exact bound engine supports integer-valued floating outputs, with sum
of maximal absolute contributions <= 2**52. Every possible aggregate sum is then
exactly representable in binary64, including intermediate sums. Use original
math.isclose tolerances at both interval endpoints. Do not round noninteger
values or assume individual candidate deltas compose through formula dependencies.
Noneligible inputs use bounded exhaustive traversal of the unchanged domain.

DFS either evaluates a complete assignment or excludes a prefix whose entire
remaining interval cannot satisfy one approved constraint. Unique acceptance
requires a complete partition of the original Cartesian domain and exactly one
satisfying leaf. Two solutions suffice to reject uniqueness, but do not establish
an exact total solution count. Unknown evaluation and exhausted budgets cannot
authorize new joint actions. The original-satisfies and no-authority behaviors
retain V516 semantics, with legacy actions explicitly outside joint authorization.

The certificate contains ordered terminal prefixes and the excluding constraint
indices, bound to workbook, candidate domain, documents, approvals and date.
Replay rebuilds the bound tables, checks prefix intervals for gaps/overlaps,
evaluates unpruned leaves and checks the atomic solution. Hash equality or a
complete flag alone is insufficient. Full localization equality is checked
separately against the same backend. Preparation, traversal, leaf evaluation,
pruned assignments and wall-clock costs are reported separately.

## Validation gates

- Exhaustive differential tests: identical domain and unique solution; zero/many
  classifications agree (two witnesses need not count every solution).
- More than 256 states: multiple families and instances with unchanged candidates,
  ranking, and exact accepted formulas, independently replayed certificates.
- Controls: ambiguous, no solution, cancellation, already-satisfied, fractional
  values, dependency coupling, tolerance boundaries, unknown evaluation, low
  budgets, invalid approvals and all repair policies.
- Certificate tampering: missing/duplicate prefixes, false prune, domain/input
  edits, incomplete flag, and altered actions must fail verification.
- After the milestone: 24/32 candidate measurements for extremal unique cases and
  mixed-sign unique cases with overlapping subtotal constraints, plus ambiguity
  and exhausted budgets. Keep all cases and refusal outcomes in the report.
- Full pytest and Ruff after implementation; preserve existing frozen files.

Large-space certificate replay is not exhaustive enumeration. Do not describe it
as such, or generalize favorable sum-bound results to arbitrary formula repair.
Dependency-component decomposition is deferred: the existing organization-total
constraint couples departments, so splitting by sheet would be unsound.
