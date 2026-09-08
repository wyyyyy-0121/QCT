# V5.1.4 constrained edge experiment protocol

Scope: retain V513 localization exactly; first audit missing repairs, then test
singleton edge proposals. No whole-column rewrite and no ranker training.

Candidate generation: endpoint singleton, at least three contiguous same-template
neighbors, translation agreement. Accept experimentally only when disjoint row
and column anchors agree on the same formula, with one shape-preserving edit.
Existing V512 accepted groups remain unchanged. Literal/expression changes need
review. Orthogonal cell sets are not necessarily independent business evidence.
After development exposed legal-operator false positives, the default mode is
propose_only. Orthogonal acceptance remains explicit opt-in for the preregistered
failed-hypothesis confirmation; do not present the default as stronger repair.

Development: all 144 disclosed fixtures, 25 retrospective real workbooks for rank
invariance, and 132 new development grids (six families, two clusters per family,
eleven categories). Inspect per-category failures before freezing. Do not select
only positive cases. Reuse verified historical baseline rankings; recompute repair.

Ablations: edge off (V513 composition), propose_only, orthogonal; each with
structural, review_only, reject_all, under both V4 and V511 backends. Policies only
change decisions. Candidate coverage is before acceptance. Denominator is all
detect_and_repair error cells; abstention labels are reported separately.

Confirmation: after implementation/tests/development, freeze source snapshot,
dependency versions, parameters, this protocol, generator and scorer. Generate
264 fresh grids (four clusters per family) using a new unpredictable seed after
freeze. This is a fresh-instance mechanism confirmation, NOT a new family holdout
or a natural-workbook generalization claim. Label intent is synthetic. The legal
operator category tests whether structural agreement can distinguish business
exceptions; do not remove this category to make safety pass. No post-reveal tuning.

Write a PUBLIC manifest containing only opaque IDs, workbook identity, cluster,
format and path. Generate labels separately. Prediction processes receive PUBLIC
only and never import labels. Commit all variant prediction shards/locks before
scoring; verify every hash and the source lock before label access. Score once.
No parameter changes or early outcome-based stopping during confirmation.

Engineering gates: zero rank, score-bit and formula-coverage changes; deterministic
double-run proposals/composition; full tests and static checks pass.
Efficacy gate: orthogonal exact accepted coverage strictly exceeds off in the
predeclared repair-required population; report single-axis results separately.
Safety gates: zero unsafe accepted groups in all workbooks, group precision >=95%,
control candidate FPR <=10%, abstention candidate rate <=10%. Every backend must
pass; review/reject-only zero actions do not count as efficacy. Report both overall
and edge-incremental actions. Any failed safety gate => DO_NOT_PROMOTE. An observed
zero count is not a population guarantee; include sample size and a binomial bound
with the independence limitation (templates are clustered).

If orthogonal agreement fails on legal exceptions, retain the failed experiment
and recommend additional externally justified constraints instead of changing its
labels, shrinking its denominator, or presenting proposal-only as a successful
automatic repair model. The delivery is implementation plus honest validation,
not a promise of a successful model upgrade. No production default change or
workbook edits are authorized.
