# V5.1.1-development disclosed evaluation

This is a development-only evaluation on the already revealed
`V51_NATURAL_CONFIRMATION_SECRET_V1` cohort. It is not a new blind result and
must not be used as independent confirmation. The implementation is a new
lineage; the frozen `V5.1-development` source and result were not modified.

## Result

| Metric | V5.1.1-development |
| --- | ---: |
| Repair-case macro AP | 100.00% |
| Exact candidate coverage | 100.00% |
| Candidate location precision | 100.00% |
| Control workbook candidate FPR | 0.00% |
| Ambiguous workbook candidate rate | 0.00% |
| Accepted-group exact coverage | 100.00% |
| Accepted-group precision | 100.00% |
| Unsafe accepted groups | 0 |
| Singleton exact coverage | 100.00% |
| Contiguous-block exact coverage | 100.00% |
| Systematic-column exact coverage | 100.00% |

## Changes exercised

1. Percentage and ratio columns are excluded from margin-difference synthesis.
2. Unknown function-family changes are rejected before semantic synthesis.
3. Legal neutral suffixes such as `+0` are treated as equivalent formulas.
4. Tied or non-contiguous templates abstain unless an anchored region gate passes.
5. Role synthesis covers revenue/MRR products, closing reconciliation, averages,
   and margin/difference columns.

## Interpretation

The result verifies that the new implementation addresses the disclosed failure
modes in this generator. It is expected to be optimistic because the cohort's
families and mutations are now visible and the role registry was developed
against them. The next step is a fresh model lock followed by a new blind
PUBLIC/SECRET release; no parameter tuning may use that new SECRET after
release.
