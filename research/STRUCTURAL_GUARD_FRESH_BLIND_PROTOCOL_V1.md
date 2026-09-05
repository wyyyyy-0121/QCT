# Structural Guard fresh blind comparison protocol v1

Status: preregistered before dataset generation

## Question

Does the frozen `v5-formulaguard-silent-source-r2` model provide a safer and
more useful replacement than both the frozen V4-R1 baseline and the frozen
V5-v1 (`v5-formulaguard-silent-source-r1`) candidate on a fresh synthetic
workbook cohort?

This is an AI-administered internal blind test, not an independent third-party
validation.  The models are frozen before the random dataset seed is chosen.
PUBLIC predictions are hash-locked before SECRET labels are opened by the
scorer.

## Frozen models

| Name | Git object | Entry point |
| --- | --- | --- |
| V4-R1 | `freeze-v4-r1` | `formulaguard.localize.v4_scores` |
| V5-v1 | `ce7576354c0a4298019ee8bbbfc575fd68cff4da` | `formulaguard.v5_structural_guard.v5_structural_guard_scores` |
| V5-R2 | `2232a870e3be089650ccd1676049e6c5c35cd692` | `formulaguard.v5_structural_guard.v5_structural_guard_scores` |

The machine-readable lock records resolved commits, source-tree hashes,
function signatures, and default parameters.  Each prediction run extracts the
exact committed tree into a temporary directory.  It refuses a model whose
resolved commit or tree hash differs from the lock.

## Fresh cohort

- 360 XLSX workbooks in 30 anonymous clusters, 12 cases per cluster.
- Three language strata: English, Simplified Chinese, and Spanish (10 clusters
  each).
- Per cluster: two singleton errors, two contiguous-block errors, two
  systematic-column errors, one insufficient-context ambiguity, one tied-pattern
  ambiguity, two clean regular controls, one legal exception, and one
  unsupported-formula stress control.
- The six singleton/block/systematic cases are `detect_and_repair`; the two
  ambiguous cases are `abstain`; the four controls are `no_action`.
- All workbooks are generated from new layouts and values after this protocol is
  committed.  No prior Structural Guard benchmark workbook is copied.

The generator first builds SECRET, then writes the SECRET archive SHA-256 into
PUBLIC before packaging PUBLIC.  The release receipt commits both archive
hashes.  PUBLIC contains no labels, expected formulas, cohort names, or decision
fields.

## Metrics

All formulas are normalized by removing whitespace and upper-casing.

- Per-case average precision (AP) over the complete formula ranking.
- Macro AP over the 180 `detect_and_repair` cases.
- Exact candidate repair coverage: correctly proposed formulas divided by true
  erroneous cells in `detect_and_repair` cases.
- Candidate location precision on `detect_and_repair` cases.
- Control workbook candidate false-positive rate: fraction of the 120
  `no_action` workbooks with one or more candidate formulas.
- Ambiguous workbook candidate rate over the 60 `abstain` cases.
- For V5-R2 only: accepted-group exact coverage and accepted-group precision,
  derived from its frozen group evidence.

Uncertainty for model deltas uses a paired cluster bootstrap with 10,000 draws
and seed `20260904`.  A two-sided percentile 95% interval is reported.

## Preregistered promotion rule

V5-R2 is stronger enough to replace a comparator only if every applicable gate
passes:

1. Macro-AP delta on `detect_and_repair` cases is positive and its paired
   cluster-bootstrap 95% lower bound is greater than zero.
2. Exact candidate repair coverage is non-inferior: R2 minus comparator is at
   least -5 percentage points.
3. Control workbook candidate false-positive rate is no higher than the
   comparator and is at most 20% in absolute terms.
4. R2 accepted-group exact coverage is at least 50% of repair-required cells.
5. R2 accepted-group precision is at least 95%.
6. R2 accepts zero groups in `abstain` and `no_action` cases.

R2 replaces the historical baseline only if it passes against both V4-R1 and
V5-v1.  Any failed gate yields `DO_NOT_PROMOTE`.  No threshold tuning, case
exclusion, dataset regeneration, or model edit is allowed after PUBLIC
prediction begins.

## Execution order

1. Commit and push this protocol, the machine lock, generator, runner, and
   scorer while the repository is clean.
2. Choose one random generation seed and generate exactly one PUBLIC/SECRET
   release.
3. Run each frozen model twice with 24 workers.  Require byte-identical
   prediction locks for the two runs.
4. Record all three prediction lock hashes in a reveal authorization file.
5. Only then run the SECRET scorer and write the technical result report.

