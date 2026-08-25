# V6 data-gate failure R1

Date: 2026-08-25

This is a pre-prediction engineering failure record. It is not a model result
and must not be presented as a completed V6-A round.

## What happened

The first `run_v6_round.cmd a --workers 24` invocation generated all three
development layers and then stopped at the preregistered dataset hard gate,
before `results/v6_development_a` or any model prediction was created.

- Development: 1,200 generated, 1,185 valid, 15 invalid.
- Red team: 360 generated, 352 valid, 8 invalid.
- Clean controls: 240 generated, 240 structurally accepted.
- All 23 invalid records failed only `sink_value_unchanged`.
- The cross-split leakage audit itself passed.

The failed development and red-team dataset manifests had SHA-256 values
`55e59a32fafad1f87589295d5e07ce688035ef72d200d169e52375b4b8713417`
and `0905b47d3544c79f7f634f1216a0af797130545a7b775ecad85eaf816c8b3beb`.

## Root cause

Every invalid record was a `reference_shift` or `copy_offset` mutation. The
generator drew adjacent B-column inputs independently, so a few workbooks had
`B[row-1] == B[row]`. Replacing the reference changed formula text but not the
source value or downstream sink, violating the registered requirement that a
silent source error must have real downstream propagation.

## Repair boundary

The repair changes only synthetic input generation: B-column values now use a
seeded affine cycle with period 41, longer than every generated input block, so
adjacent values cannot be equal. C/D values remain random. Error classes,
formula templates, topology, depth, method code, candidates, thresholds and V6
ranking logic are unchanged.

No invalid case is excluded or relabeled. Because no predictions existed, the
three generated directories may be replaced in full under the new generator
hash and re-audited before V6-A starts.
