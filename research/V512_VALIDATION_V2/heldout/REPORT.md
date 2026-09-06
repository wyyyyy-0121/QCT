# V5.1.2 validation

Evidence scope: held_out_structure_fixtures

| Model | AP | Exact coverage | Global exact candidate precision | Whole-group precision | Unsafe groups | Control FPR | Ambiguity |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| v512 | 84.27% | 22.39% | 100.00% | 100.00% | 0 | 0.00% | 0.00% |
| v511 | 83.97% | 0.00% | n/a | n/a | 0 | 0.00% | 0.00% |
| v4 | 85.07% | 35.45% | 3.51% | n/a | 0 | 100.00% | 100.00% |

Decision: DO_NOT_PROMOTE

## V5.1.2 strata

| Cohort | Cases | Exact coverage | Unsafe groups |
| --- | ---: | ---: | ---: |
| alternating | 12 | n/a | 0 |
| block | 12 | 100.00% | 0 |
| clean | 12 | n/a | 0 |
| legal_constant | 12 | n/a | 0 |
| legal_discount | 12 | n/a | 0 |
| legal_regime | 12 | n/a | 0 |
| no_anchors | 12 | n/a | 0 |
| one_side | 12 | 0.00% | 0 |
| short | 12 | n/a | 0 |
| singleton | 12 | 100.00% | 0 |
| systematic | 12 | 0.00% | 0 |
| unsupported | 12 | n/a | 0 |

The same project authored these held-out fixtures. They test formula/layout transfer relative to development fixtures, not independent natural-workbook generalization. Gates were frozen before outcome inspection. No threshold tuning on these results is allowed.

Parser coverage: 2696/2708 formula cells.

Both runs and every bound prediction shard were checked before label reading. Inputs and historical model sources were not edited.
