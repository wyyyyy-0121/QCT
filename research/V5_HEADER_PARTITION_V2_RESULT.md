# FormulaGuard header-partition V2 public transfer result

Date: 2026-09-03

Status: stopped at the label-free coverage boundary; no revealed scoring,
candidate lock, external evaluation, or formal version is authorized

Protocol: `formulaguard_header_partition_predictions_v2`

## 1. Evidence identity

The implementation was committed at
`ec39c8905a85150b0f6a64e5499d8cc91f2642be`. The complete regression at that
commit passed with 648 tests, including one skip, and the affected Ruff check
passed.

Two formal label-free scans used the fixed Enron, Info1, Integer-corpus, and
Modified-EUSES observed-workbook cohorts:

- `results/header_partition_predictions_run_a`;
- `results/header_partition_predictions_run_b`.

The three artifacts in the two directories are byte identical. Their common
SHA-256 values are:

- `predictions.jsonl`:
  `04d3e23be0be527e74237d2ea819d3fe30f68d6ede087b12028a751ec5ae664d`;
- `scan_summary.json`:
  `910617a9004f7abaa1cf5deede57d5627c68f63deed40fe1768a3603a596cd3e`;
- `completion_receipt.json`:
  `a64567f5a448226ff235ec94afeaa159aafb36fa9b6d3fff96be3c7e70741cce`.

Both receipts report `formal_evidence=true`, `label_inputs=[]`, and
`protected_data_inputs=[]`. The scans read only cohort, workbook identity,
workbook SHA-256, and structure-cluster identity from the scoring-group file.

## 2. Label-free coverage result

The scans completed 96 byte-unique observed workbooks represented by 120
identity rows:

| Cohort | Unique workbooks | Certificate workbooks | Qualified blocks | Actions |
| --- | ---: | ---: | ---: | ---: |
| Enron | 25 | 0 | 0 | 0 |
| Info1 | 2 | 0 | 0 | 0 |
| Integer corpus | 34 | 0 | 0 | 0 |
| Modified EUSES | 35 | 0 | 0 | 0 |
| **Total** | **96** | **0** | **0** | **0** |

Eighty-eight workbooks abstained with `no_qualified_block`. Eight Integer-
corpus workbooks abstained with `structure_metadata_unavailable`. There were no
multiple-qualified-block anomalies, review candidates, formula-cell review
costs, or emitted actions.

## 3. Decision

The V2 channel has zero observable coverage on every public cohort, including
all 25 natural Enron workbooks. A channel that emits no certificate cannot
change a five-cell ranking, rescue a V4 miss, or produce a control action.
Revealed-label scoring is therefore unnecessary: all possible ranking metrics
are exactly equal to the unchanged baseline.

This is a coverage stop, not evidence that header semantics are generally
uninformative. The frozen implementation requires a narrow aggregate schema,
and none of the 96 observed workbooks satisfies it. The completed scans may not
be used to relax component counts, header lookback, aggregate width, repeated-
row requirements, or cohort-specific rules on these revealed inputs.

No candidate file is created, SpreadsheetBench 2 remains unreceived, and no
protected `240+120` package was listed, searched, hashed, or read. The next
research route must obtain training evidence that is mechanism-aligned with
natural formula revisions and must be independently preregistered before new
labels or temporal outcomes are materialized.
