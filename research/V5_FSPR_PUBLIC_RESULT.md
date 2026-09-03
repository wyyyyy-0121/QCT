# FormulaGuard FSPR public transfer result

Date scored: 2026-09-03

Status: stopped negative result after frozen-V4 protocol failure; external
SpreadsheetBench 2 evaluation and a version artifact are not authorized

Protocol: `formulaguard_fspr_v1`

## 1. Label-free result and locked predictions

FSPR was preregistered at commit `d3bfd80` and implemented at commit `57eed46`.
The two label-free runs and model were locked at commit `4c3dcf5`.  They retained
all 618 FoRepBench pairs in 392 leakage groups, selected `C=10`, and obtained
83.66% out-of-fold pairwise accuracy and 0.94364 ROC AUC.  All five folds were
at or above 70% pairwise accuracy.  Syntax-only and context-only pairwise
accuracy were 81.72% and 29.77%, respectively.  Pure-Python logits agreed with
scikit-learn within `2.66e-15`, and the SpreadsheetBench v1 internal-test action
rate was 0/91.  Both runs were byte identical and passed the preregistered
label-free gate.

The public predictor and scorer were committed before label access at
`cdfb442`.  Two formal prediction runs were locked at `c722ea0`.  Both covered
220 events represented by 196 unique observed workbooks and were byte
identical.  Their common `predictions.jsonl` SHA-256 is
`b13efec6cad70a64f7461a154719153e2cf2d9711c46da03cbd24e0eff65ffff`.
The predictor declared 11 fifth-slot changes relative to the V4 rankings it
computed during those runs.  No revealed localization, answer-workbook,
task-text, or protected input entered prediction.

## 2. Frozen V4 baseline audit

The first local scoring output produced an unexpected Enron V4 Top-5 of 46.67%
and MRR of 0.37737.  The immutable V4-R1 baseline previously reported 50.00%
and 0.38254.  This discrepancy was audited before accepting the score.

The authoritative post-lock audit is implemented at commit `e31b8e5` and stored
in `results/fspr_public_frozen_v4_audit`.  It verified both locked prediction
runs and all 196 frozen V4 shards before reading the existing public labels.
The frozen combined-shard SHA-256 is
`b6ad4b46058e7c5b966bd8faa4b790f52c33a87fa03631fa744fe4a1df28d1f6`.
The audit artifacts are:

- `audit_summary.json` SHA-256:
  `8d6cf5f5357be85c30fe5d3d5b584b1da2bac92ce0205ac4db7eba83d363ff1f`;
- `event_scores.jsonl` SHA-256:
  `4873e3924d0bcd6c0e396c2902a447881912455b571c45a8e75eed4379d581b0`;
- `workbook_baseline_audit.jsonl` SHA-256:
  `90634dc9ac4d9924f32da3abb2ba6aec2571cdc450d48f1683e0c58810118330`.

All 196 formula inventories matched.  Only 172/196 embedded V4 rankings matched
the frozen V4 ranking, however, and only 180/196 preserved the actual frozen
V4 Top-4.  The 24 full-ranking mismatches comprised 12/25 Enron, 5/34 Integer,
and 7/35 Modified EUSES workbooks.  Historical 100 and Info1 matched in full.

The cause is a missing dependency boundary in the FSPR predictor.  It called
`v4_scores(workbook)` again instead of consuming the immutable V4 shards.  The
old V4 receipt fixed `formulaguard/localize.py`, whose SHA-256 still matches,
but did not fix `formulaguard/workbook.py`.  Commit `c6229ae` subsequently made
`IF` evaluation lazy, legitimately changing counterfactual evaluations and
some V4 rankings.  FSPR therefore reproduced the current evaluator twice, not
the preregistered frozen V4 ranking.  The earlier local score that treated the
embedded ranking as V4 is diagnostic only and is not authoritative evidence.

## 3. Locked-ranking metrics against frozen V4-R1

The audit did not change or rerun the model or either locked prediction.  It
scored the locked FSPR complete ranking against the immutable V4-R1 ranking.

| Cohort / aggregation | V4 Top-5 | Locked FSPR Top-5 | V4 MRR | Locked FSPR MRR |
| --- | ---: | ---: | ---: | ---: |
| All 190 errors, event micro | 57.89% | 57.89% | 0.40965 | 0.40897 |
| All 137 structures, macro | 58.91% | 58.32% | 0.39607 | 0.39491 |
| Enron, 30 errors | 50.00% | 46.67% | 0.38254 | 0.37733 |
| Historical 100 | 61.00% | 61.00% | 0.38228 | 0.38228 |
| Info1, 2 errors | 0.00% | 0.00% | 0.04340 | 0.04019 |
| Integer, 29 errors | 34.48% | 34.48% | 0.32208 | 0.32208 |
| Modified EUSES, 29 errors | 82.76% | 86.21% | 0.64487 | 0.64602 |

There was one Top-5 rescue and one loss, for zero net rescues.  Relative to the
frozen V4 ranking, FSPR changed 3/11 public control workbooks, or 27.27%.  The
structure-macro Top-5 difference was -0.584 percentage points and the
structure-macro MRR difference was -0.001161.  Enron lost 3.33 percentage
points of Top-5 and 0.005206 MRR.

## 4. Frozen gate decision

| Gate | Result |
| --- | --- |
| Structure-macro Top-5 at least +2pp and MRR non-decreasing | **Fail: -0.584pp and -0.001161** |
| At least 5 net Top-5 rescues and at most 2 losses | **Fail: 0 net rescues**; pass: 1 loss |
| Enron Top-5 and MRR non-decreasing | **Fail: -3.33pp and -0.005206** |
| Historical, Integer, and Modified EUSES each regress by at most 5pp | Pass |
| Control workbook ranking-change rate at most 15% | **Fail: 3/11, 27.27%** |
| Frozen V4 reference and immutable Top-4 integrity | **Fail: 24 full and 16 prefix mismatches** |
| Two locked prediction runs byte identical | Pass |

FSPR stops at the public transfer gate.  The integrity failure alone is
terminal, and the frozen-baseline metrics independently fail the effect,
Enron-safety, and control-safety gates.  Because labels are now revealed, the
predictor cannot be changed to read the old shards and rerun under this
preregistration.  No SpreadsheetBench 2 data was downloaded, no
`V5_FSPR1_VERSION.json` was created, and no protected `240+120` input was
listed, searched, hashed, or read.
