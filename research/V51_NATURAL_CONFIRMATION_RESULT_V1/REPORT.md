# V5.1-development natural-structure confirmation

Final decision: **DO_NOT_PROMOTE_V5_1**. V5.1 failed one or more preregistered safety, structure, or paired utility gates.

This is a fresh synthetic confirmation cohort administered by the same project. Model trees, thresholds, scorer, and gates were locked before the seed and PUBLIC/SECRET release; all predictions were double-run and locked before SECRET reveal.

## Results

| Model | Repair macro AP | Exact coverage | Candidate precision | Control FPR | Ambiguous rate | Group exact coverage | Group precision | Unsafe groups |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| v4_r1 | 84.10% | 17.46% | 13.86% | 100.00% | 100.00% | 0.00% | n/a | 0 |
| v5_v1 | 91.50% | 23.67% | 78.59% | 45.00% | 50.00% | 0.00% | n/a | 0 |
| v5_r2 | 79.95% | 10.85% | 17.92% | 52.50% | 57.50% | 6.90% | 16.28% | 15 |
| v5_1_development | 89.46% | 34.71% | 40.00% | 23.75% | 17.50% | 34.71% | 40.00% | 34 |

## V5.1 structure-stratum results

### singleton

| Model | Cases | Exact coverage | Macro AP |
| --- | ---: | ---: | ---: |
| v4_r1 | 40 | 100.00% | 100.00% |
| v5_v1 | 40 | 100.00% | 100.00% |
| v5_r2 | 40 | 100.00% | 85.71% |
| v5_1_development | 40 | 35.00% | 100.00% |

### contiguous_block

| Model | Cases | Exact coverage | Macro AP |
| --- | ---: | ---: | ---: |
| v4_r1 | 40 | 65.00% | 75.61% |
| v5_v1 | 40 | 100.00% | 92.04% |
| v5_r2 | 40 | 35.00% | 78.95% |
| v5_1_development | 40 | 35.00% | 86.91% |

### systematic_column

| Model | Cases | Exact coverage | Macro AP |
| --- | ---: | ---: | ---: |
| v4_r1 | 40 | 0.90% | 76.68% |
| v5_v1 | 40 | 0.00% | 82.46% |
| v5_r2 | 40 | 0.00% | 75.18% |
| v5_1_development | 40 | 34.63% | 81.47% |

## Paired comparisons

- V5.1 minus v4_r1: AP delta 5.36% (95% CI -2.61% to 12.20%); gates: FAIL AP delta CI lower > 0, PASS exact coverage non-inferior >= -5pp, FAIL control FPR <= 10%, FAIL ambiguous rate <= 10%, FAIL accepted group exact coverage >= 50%, FAIL accepted group precision >= 95%, FAIL zero unsafe accepted groups, FAIL singleton exact coverage >= 90%, FAIL contiguous block exact coverage >= 70%, FAIL systematic column exact coverage >= 50%
- V5.1 minus v5_v1: AP delta -2.04% (95% CI -11.83% to 7.04%); gates: FAIL AP delta CI lower > 0, PASS exact coverage non-inferior >= -5pp, FAIL control FPR <= 10%, FAIL ambiguous rate <= 10%, FAIL accepted group exact coverage >= 50%, FAIL accepted group precision >= 95%, FAIL zero unsafe accepted groups, FAIL singleton exact coverage >= 90%, FAIL contiguous block exact coverage >= 70%, FAIL systematic column exact coverage >= 50%
- V5.1 minus v5_r2: AP delta 9.51% (95% CI 3.18% to 16.43%); gates: PASS AP delta CI lower > 0, PASS exact coverage non-inferior >= -5pp, FAIL control FPR <= 10%, FAIL ambiguous rate <= 10%, FAIL accepted group exact coverage >= 50%, FAIL accepted group precision >= 95%, FAIL zero unsafe accepted groups, FAIL singleton exact coverage >= 90%, FAIL contiguous block exact coverage >= 70%, FAIL systematic column exact coverage >= 50%

## Limitations

The cohort is synthetic and not independent third-party evidence. A PASS would justify a separately administered external confirmation, not replacement of the historical baseline by itself. A FAIL is diagnostic evidence and does not alter frozen historical results.
