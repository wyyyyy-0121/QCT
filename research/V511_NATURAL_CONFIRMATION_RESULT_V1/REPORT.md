# V5.1.1 natural-structure confirmation

Final decision: **PROMOTE_V5_1_1**. V5.1.1 passed every preregistered gate.

Models, thresholds, scorer, and gates were locked before the fresh seed and PUBLIC/SECRET release. Predictions were double-run and locked before SECRET reveal. This remains project-administered synthetic evidence, not independent third-party evidence.

## Results

| Model | Repair macro AP | Exact coverage | Candidate precision | Control FPR | Ambiguous rate | Group exact coverage | Group precision | Unsafe groups |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| v4_r1 | 84.86% | 16.96% | 13.86% | 100.00% | 100.00% | 0.00% | n/a | 0 |
| v5_v1 | 91.50% | 23.67% | 78.59% | 45.00% | 50.00% | 0.00% | n/a | 0 |
| v5_r2 | 79.95% | 10.85% | 17.92% | 52.50% | 57.50% | 6.90% | 16.28% | 15 |
| v5_1_development | 89.46% | 34.71% | 40.00% | 23.75% | 17.50% | 34.71% | 40.00% | 34 |
| v5_1_1_development | 100.00% | 100.00% | 100.00% | 0.00% | 0.00% | 100.00% | 100.00% | 0 |

## V5.1.1 structure strata

### singleton

| Model | Cases | Exact coverage | Macro AP |
| --- | ---: | ---: | ---: |
| v4_r1 | 40 | 100.00% | 100.00% |
| v5_v1 | 40 | 100.00% | 100.00% |
| v5_r2 | 40 | 100.00% | 85.71% |
| v5_1_development | 40 | 35.00% | 100.00% |
| v5_1_1_development | 40 | 100.00% | 100.00% |

### contiguous_block

| Model | Cases | Exact coverage | Macro AP |
| --- | ---: | ---: | ---: |
| v4_r1 | 40 | 63.00% | 77.66% |
| v5_v1 | 40 | 100.00% | 92.04% |
| v5_r2 | 40 | 35.00% | 78.95% |
| v5_1_development | 40 | 35.00% | 86.91% |
| v5_1_1_development | 40 | 100.00% | 100.00% |

### systematic_column

| Model | Cases | Exact coverage | Macro AP |
| --- | ---: | ---: | ---: |
| v4_r1 | 40 | 0.78% | 76.92% |
| v5_v1 | 40 | 0.00% | 82.46% |
| v5_r2 | 40 | 0.00% | 75.18% |
| v5_1_development | 40 | 34.63% | 81.47% |
| v5_1_1_development | 40 | 100.00% | 100.00% |

## Paired comparisons

- V5.1.1 minus v4_r1: AP delta 15.14% (95% CI 13.62% to 16.66%); PASS AP delta CI lower > 0, PASS exact coverage non-inferior >= -5pp, PASS control FPR <= 10%, PASS ambiguous rate <= 10%, PASS accepted group exact coverage >= 50%, PASS accepted group precision >= 95%, PASS zero unsafe accepted groups, PASS singleton exact coverage >= 90%, PASS contiguous block exact coverage >= 70%, PASS systematic column exact coverage >= 50%
- V5.1.1 minus v5_v1: AP delta 8.50% (95% CI 4.56% to 13.19%); PASS AP delta CI lower > 0, PASS exact coverage non-inferior >= -5pp, PASS control FPR <= 10%, PASS ambiguous rate <= 10%, PASS accepted group exact coverage >= 50%, PASS accepted group precision >= 95%, PASS zero unsafe accepted groups, PASS singleton exact coverage >= 90%, PASS contiguous block exact coverage >= 70%, PASS systematic column exact coverage >= 50%
- V5.1.1 minus v5_r2: AP delta 20.05% (95% CI 8.55% to 33.50%); PASS AP delta CI lower > 0, PASS exact coverage non-inferior >= -5pp, PASS control FPR <= 10%, PASS ambiguous rate <= 10%, PASS accepted group exact coverage >= 50%, PASS accepted group precision >= 95%, PASS zero unsafe accepted groups, PASS singleton exact coverage >= 90%, PASS contiguous block exact coverage >= 70%, PASS systematic column exact coverage >= 50%
- V5.1.1 minus v5_1_development: AP delta 10.54% (95% CI 3.44% to 18.90%); PASS AP delta CI lower > 0, PASS exact coverage non-inferior >= -5pp, PASS control FPR <= 10%, PASS ambiguous rate <= 10%, PASS accepted group exact coverage >= 50%, PASS accepted group precision >= 95%, PASS zero unsafe accepted groups, PASS singleton exact coverage >= 90%, PASS contiguous block exact coverage >= 70%, PASS systematic column exact coverage >= 50%

## Limitations

This is a synthetic cohort administered by the same project. A promotion decision would still require an independently administered natural-workbook confirmation.
