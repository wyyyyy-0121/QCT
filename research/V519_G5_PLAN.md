# G5 Round Plan: Development, Cost And Frozen Confirmation

Recorded before G5 work; entry requires G4 success. Preserve the original
144-workbook confirmation matrix and six modes on both backends.

## Before Freeze

1. Build a separate generator for the 12 planned cohorts: true pair, chain,
   fan-in, shared bridge, candidate-only dependency, coupled ambiguity, coupled
   no-solution, oversized component, independent unique, weak bounds, invalid
   approval and originally satisfied constraints. Each must retain its actual
   intended formula/error population, even when the policy must abstain.
2. Preflight all cohorts and families at small declared sizes; verify candidate
   domain size, true coupling where claimed and generator-only business totals.
   Any generator defect is recorded and corrected before freeze, not replaced by
   an unrelated easier cohort. Add independent differential/protocol tests.
3. Development matrix: 36 workbooks (3 families x 12 cohorts x size 12, one fixed
   development seed). Add 15 scale probes (product, sizes 16/24/32, component
   sizes 2/3/4/8/9; 9 is the 512-state component-cap pressure case). These 51
   workbooks are development evidence, with six modes and both backends.
4. Modes: V518 baseline, V519 main, components disabled, low budget, review_only,
   reject_all. Budgets remain 10000 nodes / 4096 leaves / 4096 preparations /
   256 component states; low budget changes only the node cap to 1.
5. Serial performance: product true-pair cases at 16/24/32, both backends,
   five repetitions comparing V518 baseline and V519 main, alternating mode
   order by repetition (60 measurements). Recompute ranking per repetition,
   reuse it equally within that repetition. Report rank/diagnosis/replay/
   serialization/total times and RSS high-water; do not claim XLSX I/O timing.
   The six-mode ablation is measured in development, not conflated with this
   two-mode serial comparison. Additional profiler observations separate
   candidate preparation, bound/table preparation and residual search work;
   profiler overhead is reported independently from unprofiled timing.
6. Complete all source/test/protocol revisions and check development coverage,
   strict ranking/candidate preservation and zero unsafe groups before freeze.

## Freeze And Confirmation

Freeze all executed Python sources, tests, configuration, dependency/runtime
identity, numeric rules and stage protocols. Generate a new seed only afterwards.
The matrix is 3 families x 12 cohorts x sizes 24/32 x two repetitions = 144
workbooks; six modes x two backends = 1728 diagnoses. No reseeding, exclusions,
new constraints or budget increases after freeze.

Inputs and labels are separate. Predict without reading labels, hash-lock the
entire expected shard population, then recompute ranks/candidates and independently
replay every unique claim before writing label-reveal authorization. The scorer
rebuilds the expected matrix from the frozen specification and retains all
error cells, including abstentions and timeouts, in coverage denominators.

Pass conditions: complete predeclared population, unchanged execution sources,
zero unsafe accepted groups, all unique proofs replayed, no ranking/candidate
changes, and strictly greater correct-cell coverage than V518 on each backend.
Failures remain recorded. A post-reveal correction requires a new experiment;
the original confirmation is never overwritten or retrospectively declared passed.

These remain known-generator synthetic experiments. Repeat backends and repeated
instances do not create independent real-world evidence. True business approval
correctness and third-party workbook validation remain outside this synthetic claim.
