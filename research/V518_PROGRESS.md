# V518 execution progress

## Completed gates

- Stage 0: V517 baseline committed and pushed as
  `664548931de01fd186f61d04dbe23855efeb693c`; remote HEAD checked equal.
  Baseline full suite: 906 passed, 1 skipped, 91 subtests passed (183.96 s).
  All 70 V517 persisted records and uniqueness proofs replayed successfully.
- G1: conditional numeric derivation and runtime boundary documented;
  31 outward-bound, tolerance, subnormal and completion tests passed.
- G2/G3: combined numeric/model/protocol suite: 98 passed (46.14 s), including
  2/8/9/10/12-cell exhaustive ladder, multi-option domains, unchanged ranking,
  unknown computation, candidate dependencies, and evidence tampering.
- G4: all 24 predeclared workbooks improved on both backends (48 comparisons).
  Same-budget V517 refused; V518 found the exact unique repair. Actual V516
  exhaustive reference checked 393216 states. Zero unsafe groups; all new
  certificates replayed. See `V518_G4_V1/result.json` and its artifact hashes.
- G5: all 48 development workbooks, 576 diagnoses, verified before label
  scoring. Each backend: V518 432/873 correct cells, V517 and numeric_off 0/873;
  18 correct accepted groups and zero unsafe groups. Complete population retained.
- Serial benchmark: 72 measurements, six modes, both backends, 16/24/32 cells,
  two repetitions, completed before concurrent batch/test runs.
- Full frozen-code pytest: 1004 passed, 1 skipped, 91 subtests passed (280.55 s).

## Confirmation And Final Audit

Stage 6: 428 source/test/protocol files frozen at
2026-09-06T11:37:54.003266+00:00; 144 confirmation workbooks generated after
freeze at 2026-09-06T11:37:54.252249+00:00. All 1728 predictions were locked,
verified before label scoring, and scored successfully. Each backend: 672/2724
correct cells, 24 accepted groups, zero unsafe groups. Rankings and candidates
unchanged. All 72 strata retain their two instances. Final raw-data audit passed.
Source lock SHA-256:
`d8f692bababe4a9781a3aa8e87099ed4572c7447ea3a066ea6701512d83c2c0e`.
Delivery includes source, tests, protocols, reports, compact evidence and locks.
Large raw releases and predictions remain in ignored results directories.
