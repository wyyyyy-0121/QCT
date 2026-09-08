# FormulaGuard SFRI v1 revealed development result

Date scored: 2026-09-03

Status: stopped negative result; no bounded candidate or formal version is
authorized

Protocol: `formulaguard_shared_formula_region_integrity_v1`

## 1. Locked prediction evidence

The implementation was frozen at commit
`64dba193eb4196028274c93e5897da5f1ff0626c`.  The complete regression at that
commit passed with `621 passed, 1 skipped, 82 subtests passed`.  The affected
source Ruff check also passed.

Two formal label-free runs scanned the 96 byte-unique preregistered observed
workbooks:

- `results/sfri_predictions_run_a`;
- `results/sfri_predictions_run_b`.

Both runs completed 96/96 workbooks, emitted 96 hash-locked shards, recorded
empty `label_inputs` and `protected_data_inputs`, and were byte identical.  Both
receipts recorded:

- record set SHA-256:
  `470e113c9472513ea95aec48f59368fd954da80c24ff9e314148d255097e3850`;
- shard inventory SHA-256:
  `c4d83572766939d234a49e6f79376ab499f4a75e9c9c1bf7284f27d585a200a7`.

The scan found 50 locally valid declared shared-formula regions and eight
single-disagreement certificates.  All eight occurred in
`public:integer_corpus`; the other 88 workbooks abstained with
`no_eligible_region`.  No automatic workbook action was emitted.

## 2. Independent revealed scoring

The independent scorer was frozen at commit
`651b51d32dcd1af0f0fea8d99bbfb4c2ba14b043`.  Before reading labels it verified
both SFRI run directories, all 192 shard hashes, their byte equality, and the
existing frozen V4 baseline.  It then scored 120 events representing 96 unique
workbooks: 90 error events and 30 public controls.

The immutable score is in `results/sfri_v1_revealed_score`:

- `score_summary.json` SHA-256:
  `967a37f0198fe6ad5d55ee0e7da273fb7bc1ee83a1f30f0ad18bed875db9f9f4`;
- `event_scores.jsonl` SHA-256:
  `d5b9d3f8c90e4c0d24b99d09f1274b482e6ba28565f3dc4a5fbbadba0445c166`.

No protected `240+120` input was read.

## 3. Results

| Measure | V4-R1 | V4 plus SFRI fifth |
| --- | ---: | ---: |
| Event Top-1, 90 errors | 33.33% | 33.33% |
| Event Top-5, 90 errors | 54.44% | 55.56% |
| Event MRR, 90 errors | 0.44005 | 0.44135 |
| Structure macro Top-1, 42 groups | 30.71% | 30.71% |
| Structure macro Top-5, 42 groups | 51.67% | 52.26% |
| Structure macro MRR, 42 groups | 0.41037 | 0.41106 |

All eight certificates identified the labeled source cell, and all eight
translated candidates exactly matched the formula in the paired original
workbook after normalization.  The certificates covered two structure
clusters.  There were no certificates on the 30 control events representing
11 unique control workbooks.

Seven certified targets were already in V4 Top-5.  The only new Top-5 hit was
`integer_corpus_018`, whose source moved from V4 rank 12 to rank 5.  There were
zero Top-5 losses in every cohort.  Enron Top-5 remained 50.00% and Enron MRR
remained 0.38254.

## 4. Frozen gate decision

| Gate | Result |
| --- | --- |
| At least 6 certificate workbooks in at least 2 clusters | Pass: 8 in 2 |
| Certificate precision at least 90%, no control false certificate | Pass: 100%, 0 false controls |
| Candidate formula accuracy at least 90% | Pass: 8/8, 100% |
| At least 2 net Top-5 rescues and at least 1 newly hit cluster | **Fail: 1 net rescue, 1 cluster** |
| Zero Top-5 losses overall and by cohort | Pass: 0 |
| Enron non-degradation and public control action rate 0% | Pass |
| Prediction and scoring integrity | Pass |

Because the preregistration requires every gate to pass, SFRI v1 stops here.
The positive precision and repair evidence does not authorize lowering the
two-rescue requirement after scoring, moving the candidate above rank 5, or
adding a cohort exception.  No bounded V4-plus-SFRI candidate file was created,
and this result is not a formal `V5-R1`.
