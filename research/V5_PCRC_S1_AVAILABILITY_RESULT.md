# FormulaGuard PCRC S1 candidate-availability result

Date: 2026-09-02
Protocol: `formulaguard_pcrc_v1`
Preregistration lock: `276bb8d`
Implementation lock and context-parser correction: `7278de8`, `f3dd4d6`
Receipt: `results/pcrc_corpus_v1/corpus_receipt.json`
Receipt SHA-256: `9ee07fcbac3c20912773c3416d232971b38ae275125dd2fc840954c5615ea1c3`

## Scope and integrity

The 24-worker builder processed all 607 retained SpreadsheetBench v1 input-only
workbooks across the frozen 153/33/33 structure-group split. A first attempt stopped
when a parseable target had an unsupported string-bearing formula in its context. The
implementation correction maps unsupported **context** formulas to one fixed token;
target and repair candidates remain parser-supported. Seven focused tests passed before
the corrected run. No completed corpus result existed before the fix.

The corrected build completed 607/607 workbooks. A second process validated every
existing shard and reproduced the receipt. The receipt records empty answer-workbook,
fault-label, and protected-data inputs; it also records that no raw formula string,
raw numeric value, or target formula token was persisted in the context.

## Result

| Split | Structure groups | Selected targets | Targets with peer hard negatives | Hard-negative candidates |
| --- | ---: | ---: | ---: | ---: |
| train | 153 | 16,111 | 5,246 | 13,231 |
| calibration | 33 | 3,637 | 1,127 | 2,864 |
| internal test | 33 | 3,499 | 1,476 | 2,671 |
| **total** | **219** | **23,247** | **7,849** | **18,766** |

The preregistered S1 availability condition requires at least 2,000 eligible
hard-negative targets across at least 25 internal-test structure groups. The group
count is available, but only 1,476 targets have a distinct executable peer repair
candidate. The event-count condition fails before any model, learning-rate run,
checkpoint, calibration metric, or internal-test prediction is produced.

## Reconciliation with the exploratory count

The preregistration disclosed an earlier 200-target audit with 2,303 internal-test
targets having a broader local alternative. The completed PCRC implementation applies
the separately frozen executable peer generator: parser-supported formula-shape match,
translation to the target, at most four hypotheses, and token-level removal of
equivalent candidates. Those restrictions retain 1,476 targets. The earlier number was
therefore a feasibility estimate for a wider candidate class, not the prospective PCRC
result. Replacing PCRC candidates with the wider class would reproduce the already
failed semantic-compatibility route and is not allowed.

## Decision

PCRC v1 fails S1 availability and stops before training. The 2,000-target condition,
candidate generator, token schema, and split remain unchanged. The three learning-rate
runs, calibration, internal-test scoring, public transfer, SpreadsheetBench v2 intake,
and protected evaluation are not authorized.

This result does not show that neural compatibility is impossible. It shows that the
specific candidate-distribution alignment meant to distinguish PCRC from the failed
semantic model removes too many self-supervised internal-test targets for its frozen
evidence requirement. PCRC cannot be called `V5-R1` or a model breakthrough.
