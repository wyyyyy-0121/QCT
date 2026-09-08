# V5 Structural Guard R2 RECALC PUBLIC prediction amendment

Status: RECALC PUBLIC received; SECRET not received.

This amendment records the transition from the PRE_RECALC engineering run in
`V5_STRUCTURAL_GUARD_R2_PUBLIC_PREDICTION_PROTOCOL.md` to the externally recalculated
PUBLIC input. It does not change the frozen V5 model, its parameters, candidate rules,
ranking, group boundaries, or rejection gates.

## Input commitment

- Archive: `V5_Structural_Guard_R2_PUBLIC_RECALC.zip`
- SHA-256: `b3a72f0110818c28a7a817df8f00e567d72158440dbc5cfea0a6fd5e88fd3fbd`
- Cases: 360 anonymous XLSX workbooks in 30 anonymous clusters
- Manifest status: `package-valid;formula-bearing;external-recalc-complete`
- Excel engine: version 16.0, build 20326, `Application.CalculateFullRebuild`
- Excel execution log: 360 unique rows, all `recalculated-and-saved`
- Labels or SECRET content: absent

The RECALC audit was independently checked against the PRE_RECALC input before
prediction. Both versions contain 8,826 formula cells. Excel changed 4,740 formula
texts in 228 workbooks, and every change is exactly explained by removal of redundant
single quotes around worksheet names. There are no non-formula value changes and no
worksheet or merged-range structure changes.

## Reporting correction

Runner commit `1fdc686` correctly generated deterministic prediction shards for either
input, but hard-coded PRE_RECALC wording into the metadata, summary, and lock. A RECALC
run made with that runner is therefore diagnostic only even when its shards are valid.
The reporting-only correction derives the evidence scope from the uniform manifest
integrity status. It also refuses mixed or unidentified recalculation stages.

The final RECALC lock must be generated twice from empty output directories with the
corrected committed runner. The two shard sets and deterministic lock artifacts must
match. SECRET remains inaccessible until those checks pass.

## Fixed commands

```bash
python scripts/run_v5_structural_guard_public_predictions.py \
  --public data/external/v5_structural_guard/raw/public_recalc/PUBLIC \
  --source-archive data/external/v5_structural_guard/raw/V5_Structural_Guard_R2_PUBLIC_RECALC.zip \
  --output results/v5_structural_guard_public_recalc/run_a_<runner_commit> \
  --workers 16

python scripts/run_v5_structural_guard_public_predictions.py \
  --public data/external/v5_structural_guard/raw/public_recalc/PUBLIC \
  --source-archive data/external/v5_structural_guard/raw/V5_Structural_Guard_R2_PUBLIC_RECALC.zip \
  --output results/v5_structural_guard_public_recalc/run_b_<runner_commit> \
  --workers 16
```
