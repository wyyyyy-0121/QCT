# V5 Structural Guard R2 RECALC PUBLIC result

Date: 2026-09-04

## Decision

The externally recalculated, label-free PUBLIC prediction is complete and locked.
Two independent runs are deterministic. SECRET data has not been received or read, so
accuracy, repair correctness, control false-positive rate, and the final generalization
decision remain deferred.

The label-free result retains the main PRE_RECALC risk signal: all 360 workbooks emit at
least one cell-level candidate while no group repair is accepted.

## Frozen scope

- Model: `v5-formulaguard-silent-source-r2`
- Model origin commit: `2232a870e3be089650ccd1676049e6c5c35cd692`
- Corrected prediction runner commit: `e44aba93711e9c4a50304167f4bb3b59fd3e66ca`
- PUBLIC archive: `V5_Structural_Guard_R2_PUBLIC_RECALC.zip`
- PUBLIC archive SHA-256: `b3a72f0110818c28a7a817df8f00e567d72158440dbc5cfea0a6fd5e88fd3fbd`
- Evidence scope: `label_free_public_recalc_prediction`
- Labels or SECRET data read: none
- Automatic workbook edits: none

The model module and its four direct dependencies are byte-identical to the model
origin commit. The reporting correction does not change model behavior or parameters.

## RECALC input audit

- 360 anonymous XLSX workbooks in 30 anonymous clusters
- 12 workbooks per cluster
- 8,826 formula cells
- All workbook hashes match both `manifest.csv` and `SHA256SUMS.txt`
- The extracted file set and bytes match the source archive
- No label-like fields, filenames, SECRET content, unsafe paths, or symbolic links
- Excel execution log contains 360 unique workbooks, all
  `recalculated-and-saved`
- Excel version 16.0 build 20326 used `Application.CalculateFullRebuild`

Independent PRE_RECALC-to-RECALC comparison found 4,740 formula-text changes in
228 workbooks. Every change is exactly explained by deletion of redundant single
quotes around worksheet names. There are no non-formula value changes and no workbook
structure or merged-range changes. All 8,826 recalculated formula caches are present
and none contains an error value.

## Reporting correction

Runner commit `1fdc686` produced valid deterministic shards but hard-coded PRE_RECALC
wording in every metadata, summary, and lock file. Its RECALC output is retained only as
a diagnostic run. Commit `e44aba9` derives the evidence scope from the manifest's
uniform recalculation status and rejects mixed or unknown stages. The full test suite
and `ruff check .` passed before the corrected runner was committed and pushed.

## Final reproducibility lock

Final runs:

- `results/v5_structural_guard_public_recalc/run_a_e44aba9`
- `results/v5_structural_guard_public_recalc/run_b_e44aba9`

Both runs used 16 worker processes and completed all 360 cases. Their shard directories
are byte-identical. Runtime is excluded from the deterministic lock.

- Run A prediction wall time: 0.905252 seconds
- Run B prediction wall time: 0.906581 seconds
- Combined shards SHA-256: `3fa8fd011281b0f1b276d2db62debcd96f6c4407b1cb520cf990e65bfbf72791`
- Prediction lock SHA-256: `665e07349431b2342516f5e4e21d6dcd157145c1d330dbbf607704e43a5ea9c7`
- Summary SHA-256: `342de2e6e270f668b97aac3d5d4fb1ee0db28d083c6992e2e4488978c16e3c0f`
- Metadata SHA-256: `6ccc1a653979d16d0350b1274a6f8283c2a8a268a784cf47fbbc098d7ee657f7`
- Complete formula ranking audit: passed
- Lock labels read: `[]`

## Label-free result

- Candidate formulas: 1,304 / 8,826 (14.7745%)
- Workbooks with at least one candidate: 360 / 360 (100%)
- Median candidates per workbook: 2
- Maximum candidates in one workbook: 21
- Accepted groups: 0
- Abstained groups: 54
- Rejection reason for all 54 groups: `semantic_not_improved`
- Candidate source: 1,304 cell-level, 0 accepted-group propagation
- Candidate edit kinds: 1,297 peer translation, 7 operator edit
- Candidate score range: 0.345 to 0.410
- Candidates with affected downstream constraints: 0
- Candidates with nonzero header-role penalty: 0

Candidate counts per workbook:

| Candidates | Workbooks |
| ---: | ---: |
| 1 | 120 |
| 2 | 120 |
| 3 | 30 |
| 4 | 57 |
| 9 | 3 |
| 19 | 8 |
| 20 | 15 |
| 21 | 7 |

Every cluster still contains one 19-to-21-candidate tail workbook. Twenty-seven
clusters contain two abstained group hypotheses; three clusters contain none.

## PRE_RECALC comparison

The formula recalculation and Excel normalization changed the deterministic shard hash.
The full ranking order and every score remain unchanged, but the candidate and group
outputs differ as follows:

- Cell candidates: 1,289 to 1,304, a net increase of 15
- Candidate coordinates changed in 3 / 360 workbooks
- Fifteen candidate coordinates were added and none removed
- Candidate formula text changed at 129 shared coordinates only by quote removal
- Group evidence changed in 6 / 360 workbooks
- Six previously abstained groups disappeared; no new group appeared
- Accepted groups remained 0

The six changed group cases occur in three multilingual clusters whose recalculated
formulas had redundant worksheet-name quotes removed. This is evidence that the frozen
model's group formation is sensitive to Excel's semantically equivalent formula-text
normalization. It must be disclosed in final interpretation; it is not a reason to edit
the frozen model after PUBLIC exposure.

## Interpretation and next gate

This run proves complete parsing, deterministic ranking, a valid RECALC input lock, and
no workbook mutation. It does not prove accuracy. The 360/360 candidate action rate and
the repeated high-candidate tail remain the principal safety risks. The normalization
sensitivity is an additional robustness limitation, although it affects only 6 cases'
group evidence and 3 cases' candidate coordinates in this PUBLIC set.

The next permitted input is the one-time SECRET label package corresponding exactly to
this RECALC PUBLIC commitment. Before scoring, its declared linkage and schema must be
verified without changing the locked predictions. Only then may AP, Top-K localization,
repair correctness, control false-positive rate, and the preregistered pass/fail decision
be calculated.
