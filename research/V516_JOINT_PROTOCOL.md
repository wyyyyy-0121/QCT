# V5.1.6 joint repair and ambiguity experiment

Preserve full localization and V515's bounded edge candidate generator. Compare
V515 and V516 on exactly the same workbook/constraint/approval inputs. No real
business data is required for this synthetic experiment and no real-world safety
claim follows from it. Historical models, snapshots, parameters and reports remain.

Joint search includes the no-change choice for every candidate cell. Default
max_states=256. Compute the complete Cartesian-product size before enumerating;
if it exceeds budget, accept nothing under the joint mechanism. Never limit to
fewer changed cells and call a surviving answer globally unique. A unique solution
requires full enumeration, successful evaluation of every state, and exactly one
state satisfying all approved constraints. Multiple solutions => review, zero =>
abstain, incomplete evaluation => review. All original constraints already true
=> no new change, including cancelling errors. Uniqueness is confined to the
declared candidate space, not all possible formulas or business interpretations.
The candidate space uses unchanged bounded edge proposals at direct aggregate
member cells, plus no-change; arbitrary upstream formula rewrites are not searched.

Treat the approved aggregate set as a coupled transaction. Existing legacy
accepted actions are not silently committed alongside a joint solution. With valid
constraints, output only the uniquely verified transaction; with no approved
constraints retain the previous candidate-only/legacy behavior and label that
scope. Every member of an accepted group must be correct for group-level credit.

Required development tests and generated cohorts: joint-only two-error recovery,
multiple valid combinations, cancelling errors, cancellation resolved by fixed
category subtotals, no solution, clean/legal exception, stale/conflicting approval,
numeric collision, oversized candidate space, and incomplete evaluation. Totals
and subtotals are defined for fixed whole regions/categories before corruption,
not one desired-answer equation per corrupted cell. Report complete population
coverage, group precision, unsafe groups, abstention/status counts, search states,
runtime and candidate coverage. Ranking/score/coverage changes must remain zero.

Develop and run ablations first, then freeze source, tests, generator, scorer and
this protocol. Generate a new seeded confirmation population only after freeze,
commit predictions before revealing labels, and compare V515/V516 plus low-budget,
review-only and reject-all ablations. Gate: joint-only exact coverage improves;
zero unsafe accepted groups; ambiguous/cancelling-without-extra-evidence/over-budget
cases never accepted; accepted group precision >=95%; localization invariant.
Do not remove hard negatives or tune after confirmation reveal. A passing result
is conditional synthetic evidence only, with sample-size and clustering caveats.

Fixed populations: six arithmetic template families, twelve cohorts, two clusters
per family in development (144 inputs), five new clusters per family in confirmation
(360 inputs). Candidate generation is unchanged. All repair-required errors remain
in the denominator, including nine-error over-budget workbooks and numeric
collisions; ambiguous/cancelling/conflicting cases are separately scored abstention
cases, with any accepted group counted unsafe. There is no post-hoc easy-case-only
score. The predeclared qualified subset is reported only as supplemental context.
Runtime measurements are per-diagnosis elapsed time under a 24-worker experiment,
not isolated CPU or production latency benchmarks. Count states as the primary
search-cost measure. Maximum budget is 256; the low-budget ablation fixes it to 1.
The evaluated counter describes enumerated assignments (or one original state
when already satisfied); it excludes preparation, double-run repetition and the
preflight original-constraint check for a budget-rejected case.
