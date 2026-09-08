# V5.1.3-development: localization-preserving repair decisions

## Objective and boundaries

Rejecting or reviewing a repair must never remove the underlying formula cell,
change its localization score, or change its position in the complete ranking.
This release tests composition; it does not claim to invent a new core ranker.

Localization backends: V4 and V5.1.1 in the common frozen current parser runtime.
Repair backend: unchanged V5.1.2 structural acceptance. Policies: structural,
review-only, reject-all. No acceptance policy changes localization parameters.
There is no unsafe accept-all policy.

## Required proof

1. End-to-end API tests for both localization backends and all policies.
2. Extreme repair thresholds leave ranks, score bits, and formula coverage unchanged.
3. Stable tied ordering and immutable, independently materialized layer outputs.
4. Illegal discounts remain unaccepted; rejected suggestions remain separately
   reviewable while all localization entries are retained.
5. Both composition baselines on all 144 previously revealed fixtures and all
   25 Enron workbooks / 30 events. Report missing formula labels without omission.
6. Per-cell rank/score invariance, not only equality of aggregate MRR/AP.
7. Diagnose V5.1.2 rank drops from per-event records and actual evidence fields.
8. Validate provenance before cache reuse. Independently rerun the public API on
   a content-independent sample and compare it with the composed cached baseline.
9. Preserve existing frozen model, runner, scorer, and report artifacts.

## Cache and evidence policy

Previous run_a/run_b prediction locks, every shard, complete workbook identities,
source dependencies, and environment versions must be checked before reuse.
Frozen baseline ranking scores/order can be reused for composition testing;
the V5.1.2 repair layer is executed again. Run composition twice and verify exact
serialized equality. The report must distinguish cache-based composition checks
from fresh end-to-end model executions. Do not call this an independent blind trial.

Existing fixtures and Enron labels are disclosed development/retrospective data.
No claim about new repair generalization follows from preserving the old ranking.
Safety is evaluated separately with complete fixture labels; real repair precision
is unavailable. Historical V4 shared parser modules differ from the common runtime.

## Acceptance criteria for this engineering objective

- Zero changed ranks, score bits, or missing/extra formula cells in every policy.
- Structural accepted formulas/groups match the unchanged V5.1.2 repair layer.
- Review-only and reject-all produce zero accepted candidates, without ranking loss.
- Regression and full-suite checks pass; artifacts are nonempty and reproducible.

These criteria certify layer separation, not production promotion. V5.1.2's
22.39% fixture repair coverage and its unresolved edge/systematic cases remain
limitations unless separately improved and independently confirmed later.
