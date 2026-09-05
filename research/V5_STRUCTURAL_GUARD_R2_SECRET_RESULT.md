# V5 Structural Guard R2 RECALC SECRET result

Date: 2026-09-04

## Decision

The RECALC PUBLIC blind-prediction cycle is complete. The locked V5 Structural Guard
R2 result does not support promotion as a safe group-repair model.

This is an engineering decision, not a claimed preregistered pass/fail result. The
PUBLIC package did not contain a commitment to the later SECRET archive hash, and no
cohort-specific promotion thresholds were committed before SECRET release. The score
is nevertheless reproducible and descriptive because the model and all 360 complete
rankings were hash-locked before labels were received.

The central result is asymmetric:

- the cell-level ranker is excellent on singleton and insufficient-context cases;
- the group path accepts no repair group at all, including the 180 cases marked
  `detect_and_repair`;
- the cell-level proposal path emits candidates on all 120 control workbooks.

No post-SECRET tuning, threshold change, exclusion, or replacement cohort is permitted
for this frozen result.

## Commitments and reproducibility

- Model origin commit: `2232a870e3be089650ccd1676049e6c5c35cd692`
- Prediction runner commit: `e44aba93711e9c4a50304167f4bb3b59fd3e66ca`
- Scorer commit: `08797eeebac3e14fa9032774c8cd901d38698523`
- RECALC PUBLIC SHA-256: `b3a72f0110818c28a7a817df8f00e567d72158440dbc5cfea0a6fd5e88fd3fbd`
- SECRET RELEASE SHA-256: `ad1ab23233d13de81d2c5c22fd3884cedfa3a6fc387b6d07d4995c2ff604bd81`
- Prediction lock SHA-256: `665e07349431b2342516f5e4e21d6dcd157145c1d330dbbf607704e43a5ea9c7`
- Combined prediction shards SHA-256: `3fa8fd011281b0f1b276d2db62debcd96f6c4407b1cb520cf990e65bfbf72791`
- Scoring receipt SHA-256: `deaa0d08d7887886109cd260c1c8a4ee6bc8fca12eddec61796cf45ab053655d`
- Case-score CSV SHA-256: `cea412f8f11a70cf2e5a1d7ce266979338a5c9ad2c0803613cb0cde15e687765`

Both independent prediction locks produce byte-identical scoring receipts and
case-score CSV files.

## SECRET audit

- 360 unique labels match all 360 RECALC PUBLIC case IDs
- 30 cluster IDs and every case-to-cluster assignment match PUBLIC
- 240 error cases and 120 controls
- 240 unique mutation-log records match the 240 error cases
- 240 original workbooks match the 240 error cases
- 1,556 labeled changed formula cells
- Original, mutation-log, and PUBLIC formulas agree at all labeled cells after the
  already-audited Excel worksheet-quote normalization
- No undeclared formula differences, non-formula differences, or structural
  differences were found in the 240 original-to-mutated comparisons
- Unsafe ZIP paths and symbolic links: none

Cohort composition:

| Type | Cases | Error cells |
| --- | ---: | ---: |
| singleton | 60 | 60 |
| contiguous block | 60 | 330 |
| systematic column | 60 | 1,106 |
| ambiguous, insufficient context | 30 | 30 |
| ambiguous, tied templates | 30 | 30 |
| controls | 120 | 0 |

Custodian decisions are 180 `detect_and_repair`, 120 `abstain`, and 60
`no_action`.

## Localization and candidate result

| Cohort | Macro AP | Top-5 hits | Exact candidate repairs | Candidate location precision | Accepted groups |
| --- | ---: | ---: | ---: | ---: | ---: |
| singleton | 100.00% | 60/60 (100.00%) | 60/60 (100.00%) | 60/120 (50.00%) | 0 |
| contiguous block | 46.30% | 99/330 (30.00%) | 15/330 (4.55%) | 15/255 (5.88%) | 0 |
| systematic column | 76.54% | 174/1,106 (15.73%) | 0/1,106 (0.00%) | 0/120 (0.00%) | 0 |
| ambiguous, insufficient context | 100.00% | 30/30 (100.00%) | 30/30 (100.00%) | 30/60 (50.00%) | 0 |
| ambiguous, tied templates | 15.56% | 15/30 (50.00%) | 0/30 (0.00%) | 23/599 (3.84%) | 0 |
| all 240 error cases | 70.15% | 378/1,556 (24.29%) | 105/1,556 (6.75%) | 128/1,154 (11.09%) | 0 |

For the 180 `detect_and_repair` cases alone, there are 1,496 true error cells.
The model gives 75 exact cell-level candidates (5.01% coverage) and accepts zero
groups. Group-propagated candidate cells and exact group repairs are both zero.

The high systematic-column AP must not be interpreted as operational repair success.
Most formula cells in those workbooks are labeled errors, so a broadly elevated block
can rank well, while the fixed review budget captures only 174/1,106 at Top-5 and the
candidate path repairs 0/1,106 exactly.

## Control and abstention result

The two action layers have different safety behavior and must not be conflated:

| Measure | Result |
| --- | ---: |
| Control workbooks with any cell candidate | 120/120 (100.00%) |
| Candidate cells in controls | 150/2,962 formula cells (5.06%) |
| Accepted groups in controls | 0 |
| Automatic workbook edits | 0 |
| Should-abstain cases with any cell candidate | 120/120 (100.00%) |
| Accepted groups in should-abstain cases | 0 |

Thus the group gate prevents automatic group repair everywhere, including controls and
ambiguous cases, but it does so by eliminating group coverage rather than by accurately
separating repairable from non-repairable groups. The cell-level proposal layer remains
unsafe as an unfiltered workbook-level alarm because it triggers on every control and
every should-abstain case.

## Evidence limitations

1. PUBLIC did not contain a precommitment to the SECRET archive hash. The received
   SECRET is strongly linked by complete case/cluster identity and formula-ledger
   agreement, but it is not cryptographically proven to be the uniquely precommitted
   SECRET package.
2. The scorer was committed after SECRET release. It reuses the repository's existing
   AP, Top-K, and exact-formula conventions and changes no predictions, but this is not
   equivalent to a precommitted scorer.
3. The cohort is fully synthetic and AI-administered, not an independent-human
   third-party study.
4. `SECRET/provenance_and_license/NOTICE.md` still says external recalculation is
   pending. That text is stale relative to the separately supplied Excel RECALC audit
   and execution log; the RECALC files themselves were verified before prediction.
5. No V4 or other-model predictions were locked on this PUBLIC before SECRET release.
   Running them now would be a revealed-label retrospective comparison, not a blind
   model-selection result.

## Consequence for the project

This V5 instance remains a frozen negative/diagnostic result. It should not replace the
existing historical reference based on this cohort. The SECRET cohort must not be used
again as independent evidence for a tuned successor.

A future redesign may use these labels only as disclosed development evidence. A new
claim requires a new model core, a scorer and thresholds committed before data release,
a PUBLIC package that commits the SECRET hash, and a fresh never-seen confirmation
cohort. The redesign must jointly solve group coverage and cell-level control
selectivity rather than relaxing the current gate in isolation.
