# FormulaGuard FCRL U1 corpus gate result

Date: 2026-08-31
Protocol: `formulaguard_fcrl_u1_v1`
Result: **FAIL BEFORE TRAINING**
Implementation commit: `20c9d5c073693faa6958774d60e870275a1c8fd1`

## Frozen execution

The 607 retained SpreadsheetBench v1 input-only workbooks were processed with 24
workers under `research/V5_FCRL_U1_IMPLEMENTATION_FREEZE.md`.  The builder rechecked
the DRFV and intake manifests, every retained XLSX byte hash, split identity, and
structure-group isolation before constructing any target.  It completed all 607
workbook shards without reading answer workbooks, task values, fault labels, V4
rankings, SpreadsheetBench 2, or protected inputs.

Local artifact identities:

- corpus receipt SHA-256:
  `0a90210ab2bbb967b748f1da7e5da4469dd3707e42137b156e3882c06f79b07f`;
- target manifest SHA-256:
  `b36f71cc89f1faee455cadccefe44388be3656ef56635022d16f4b3fa30fcb15`;
- target inventory SHA-256:
  `3e21faa39f2b06b1b6e4a30d9ea57fffd5ca7378b2c8fed0dd311bd67f6a81d0`;
- builder metadata SHA-256:
  `268d9274b639255392a60d402371359afeaa885ea1623eb362218e46a73b83c8`.

## Aggregate coverage

The input contained 96,375 visible formula candidates.  The frozen adapter retained
11,635 targets (12.07%):

| Split | Targets | Workbooks with targets | Required groups | Groups with targets | Missing groups |
| --- | ---: | ---: | ---: | ---: | ---: |
| train | 7,932 | 239 | 153 | 82 | 71 |
| calibration | 1,778 | 57 | 33 | 20 | 13 |
| internal test | 1,925 | 67 | 33 | 23 | 10 |
| total | 11,635 | 363 | 219 | 125 | 94 |

There were 244 retained source workbooks with no accepted target.  The largest
aggregate rejection classes were `reference_outside_component` (23,759),
`unsupported_formula_function` (23,120), and `unsupported_formula_syntax` (20,011).
Other counts were `stable_cap_not_examined` 14,484, `cross_sheet_reference` 3,234,
`formula_without_reference` 93, `mandatory_crop_limit` 27, and
`formula_token_limit` 12.  These categories plus retained targets exactly account for
all 96,375 visible candidates.

Retained targets had 21,653 reachable reference tokens out of 23,570 (91.87%).  This
is a diagnostic only: the prerequisite group-coverage gate failed, so U1 formula
prediction accuracy was not scored.

## Gate decision

The frozen protocol requires every one of the 153/33/33 structure groups to retain
at least one target.  Only 82/20/23 did.  FCRL therefore fails before decoder
training.  No decoder checkpoint, calibration result, candidate lock, internal-test
prediction, localization experiment, or protected evaluation was produced.

The empty groups may not be removed, the parser/function set may not be enlarged,
and the split or coverage rule may not be changed using these observed counts.  FCRL
is stopped and cannot be named `V5-R1`.  The negative result establishes that the
current auditable QCT-to-ForTaP subset does not cover the frozen public corpus broadly
enough for the registered cross-structure evaluation.
