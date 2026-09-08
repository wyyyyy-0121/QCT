# FormulaGuard FSPR preregistration

Date frozen: 2026-09-03

Protocol: `formulaguard_fspr_v1`

Research code: `FSPR` (Formula Syntax Pair Ranker)

Status: frozen before implementation, fitting, localization prediction, or
SpreadsheetBench 2 download

## 1. Question and prior-result boundary

`V4-R1` remains the only formal main ranker.  Model discovery, AETR, PCRC,
SFRI, and static-fifth have already stopped under their frozen gates.  Their
revealed localization labels cannot select another peer rule, feature
combination, threshold, or cohort exception.

FSPR asks a different question: can explicit faulty/correct formula-pair
supervision learn a formula-level defect prior which safely replaces V4's fifth
cell when the evidence is unusually strong?  Training uses no FormulaGuard
localization label and no peer-generated repair.  Inference receives the same
single observed workbook as V4 and the review budget remains five.

The maximum supported contribution is a bounded transfer result from explicit
formula-repair pairs to source localization.  Formula tokenization, feature
hashing, logistic regression, pairwise supervision, and fifth-slot reranking
are established techniques and are not claimed as inventions.

## 2. Frozen data boundary

### 2.1 Pair supervision

The only supervised training source is FoRepBench at Git commit
`d17e278092c59ec6faaa2d88730bdcbe48bb95f2`:

- `FoRepBenchmarks.json` SHA-256:
  `7dc32841e8b243653a2325b38fd651415ce00257780815d1785d25ac41fb28fb`;
- 618 faulty/correct pairs, 516 byte-distinct pairs, and 595 distinct context
  payloads were observed before this lock;
- 421 faulty formulas, 302 correct formulas, and 270 pairs are parseable by the
  current FormulaGuard parser;
- seven exact formula strings occur under both labels and must remain grouped.

The model may read only `data`, `faulty_formula`, and `correct_formula`.
Utterance, explanation, runtime-error label, validity explanation, confidence,
difficulty, item order, and all free text are forbidden model inputs.  The seed
dataset is excluded.

Rows are connected into one leakage group when they share a canonical context,
a canonical faulty formula, or a canonical correct formula.  Connected
components, not individual rows, are assigned to five stable SHA-256 folds.
No formula or context identity may cross a fold.

### 2.2 Label-free calibration

Threshold calibration uses only the already frozen SpreadsheetBench v1
input-only corpus:

- 607 retained byte-unique workbooks and 219 structure groups;
- corpus manifest SHA-256:
  `0e1228992fccf6b13961e397b944133db83dcde72b5372af5c36cd54306e71ed`;
- corpus receipt SHA-256:
  `743461a31faf9734d38cbcb43dbf2a23cc1cf30076b8d83ffe22d3d7d6d5e789`;
- intake manifest SHA-256:
  `bb01edd4a58f80a7f26f6b3051f3bdbc6983b2a5a47a23d185bcd07cf2a4f42d`.

Only the frozen `calibration` split may set the promotion threshold.  The
`internal_test` split measures label-free workbook action rate once.  Input
formulas, constants needed to classify referenced-value types, number formats,
and structural group IDs are allowed.  Instructions, answer workbooks, answer
positions, task text, V4 outcomes, and fault labels are forbidden.

### 2.3 Evaluation isolation

The 190 revealed FormulaGuard errors and 30 paired controls may be scored only
after the complete model, coefficient file, threshold, source, and label-free
gate receipt are committed.  They remain revealed transfer evidence and cannot
change FSPR afterward.

SpreadsheetBench 2 Debugging remains unopened external evidence.  Its dataset
archive must not be downloaded until the frozen public prediction and scoring
commit either passes the public gate or stops the line.  After download, input
workbook predictions must be locked before any golden workbook content is
opened.  No protected `240+120` directory may be listed, searched, hashed, or
read during FSPR.

## 3. Frozen representation

Each formula is converted to an anchor-independent token stream:

1. AST node, operator, function, arity, and argument-position tokens;
2. numeric-literal categories, with exact nontrivial numbers excluded;
3. reference and range tokens retaining sheet relation, relative/absolute axes,
   range orientation, and bounded span categories but excluding addresses;
4. referenced-value-type counts for numeric, text, blank, formula, error, and
   missing cells;
5. parse-supported, formula-length, AST-depth, reference-count, range-count,
   function-count, and operator-count buckets.

Formula text, cell address, sheet/workbook name, repository identity, corpus,
V4 score, peer support, dependency impact, cached target value, and all task
text are excluded.  Unsupported formulas receive lexical shape tokens and the
`UNSUPPORTED_AST` indicator rather than being dropped.

Unigrams and adjacent bigrams are signed-hashed with SHA-256 into 2,048 sparse
dimensions, then each row is L2 normalized.  Hashing behavior and feature order
must be unit tested and recorded in every model receipt.

## 4. Frozen learner and calibration

The learner is balanced binary logistic regression.  Each FoRepBench pair
contributes one faulty positive and one corrected negative with equal total pair
weight.  The only hyperparameter is `C` in `{0.1, 1.0, 10.0}`.  Five-fold
leakage-group cross-validation selects the highest mean pairwise accuracy,
breaking ties toward `1.0`, then `0.1`, then `10.0`.  Solver is `liblinear`,
maximum iterations are 2,000, and seed is `260903`.

The full model is refit on all 618 pairs.  Coefficients and intercept are saved
as canonical JSON; inference must reproduce scikit-learn decision values within
`1e-10` without importing scikit-learn.

For each SpreadsheetBench v1 calibration workbook, score every visible ordinary
formula outside V4 ranks 1-4.  The fixed promotion threshold is the
nearest-higher 90th percentile of that workbook's maximum FSPR logit.  A
workbook changes only when its maximum outside-prefix formula meets the
threshold and is not already V4 rank 5.

The complete candidate ranking is V4 ranks 1-4, the selected FSPR formula at
rank 5, then the remaining V4 order.  With no qualifying formula or no fifth
slot, the complete V4 ranking is returned unchanged.  No score fusion, cohort
gate, candidate formula, peer support, or post-label threshold is allowed.

## 5. Label-free gate

FSPR proceeds only if all conditions hold:

1. all 618 pairs and all leakage components are retained, with zero group
   overlap across folds;
2. out-of-fold pairwise accuracy is at least 75%, ROC AUC is at least 0.80, and
   at least four of five folds have pairwise accuracy at least 70%;
3. the full representation has no lower pairwise accuracy than syntax-only and
   context-only ablations;
4. the selected `C`, full coefficients, threshold, and every metric reproduce
   exactly in two independent processes;
5. SpreadsheetBench v1 internal-test workbook action rate is at most 15%, and
   no answer, task-text, fault-label, revealed-localization, or protected input
   appears in any receipt.

Failure stops FSPR before localization prediction.  Features, folds, `C`
values, threshold quantile, and gates cannot change after this lock.

## 6. Revealed public transfer gate

After a label-free pass, complete predictions are locked before scoring the
existing 190 errors and 30 controls.  FSPR proceeds to external evaluation only
if all conditions hold:

1. structure-group macro Top-5 exceeds V4 by at least 2 percentage points and
   MRR does not decrease;
2. there are at least five net Top-5 rescues and at most two V4 Top-5 losses;
3. Enron Top-5 and MRR do not decrease, while Historical 100, Integer, and
   Modified EUSES each regress by no more than 5 points;
4. paired-control workbook ranking-change rate is at most 15%;
5. complete inventory, five-cell budget, source hashes, prediction isolation,
   and two-process byte equality all verify.

This gate is a fixed migration screen, not independent confirmation.  Failure
stops FSPR and does not authorize SpreadsheetBench 2 download.

## 7. External SpreadsheetBench 2 gate

The external protocol and scorer must be committed before dataset download.
Every eligible Debugging task contributes one input workbook and one golden
workbook.  Changed formula cells are independently reconstructed after input
prediction lock.  Tasks with no same-address formula change are reported and
excluded from localization metrics; at least 80 eligible tasks are required.

FSPR authorizes a scoped version file only if every condition holds:

1. prediction and gold isolation, dataset/source hashes, complete formula
   inventory, and two-process byte equality all pass;
2. event Top-5 exceeds V4 by at least 5 percentage points and event MRR does not
   decrease;
3. at least five V4 misses become Top-5 hits, at most one V4 Top-5 hit is lost,
   and the one-sided exact sign-test p-value on rescues versus losses is at most
   0.05;
4. at least 80% of task groups have nonnegative Top-5 difference;
5. no task instruction, golden workbook, changed-cell label, or post-hoc task
   category enters ranking.

Only a complete pass authorizes
`research/V5_FSPR1_VERSION.json`, with version `V5-FSPR1` and the explicit scope
`single-workbook external debugging candidate`.  It does not authorize the
reserved name `V5-R1`, a natural-error generalization claim, production status,
or protected evaluation.  Any failed gate records a negative result and no
version file is created.
