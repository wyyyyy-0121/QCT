# FormulaGuard V6 locked validation audit

## Technical summary

The 360-event locked validation is internally consistent and reproducible, but no V6 variant is eligible for freezing. V6-B is the strongest locator (macro Top-5 100.00%, MRR 0.3177, six-type minimum Top-5 100.00%), yet all three variants exceed the 10% clean-control alarm cap at 16.67%. V6-A/B also fail the exact Enron non-decrease rule, while V6-C is outperformed by a registered ablation and collapses on absolute-reference cases. The selection receipt therefore records `selected_variant=None` and `freeze_allowed=false`.

## V6-B dominates the synthetic localization task but fails deployment safety

| Method | Top-1 | Top-3 | Top-5 | Macro Top-5 | Weakest type | MRR | Exact repair |
|---|---:|---:|---:|---:|---:|---:|---:|
| V4 | 0.83% | 4.44% | 11.11% | 11.11% | 0.00% | 0.1006 | 87.22% |
| V6-A | 0.83% | 66.67% | 83.33% | 83.33% | 0.00% | 0.2795 | 83.33% |
| V6-B | 0.83% | 83.33% | 100.00% | 100.00% | 100.00% | 0.3177 | 100.00% |
| V6-C | 0.83% | 83.33% | 84.72% | 84.72% | 8.33% | 0.2967 | 100.00% |

V6-B improves paired MRR over V4 by +0.2171; the independently reproduced 95% interval is [0.2083, 0.2258]. Its paired macro Top-5 interval is [85.83%, 91.94%]. These are valid internal synthetic results, not evidence of independent real-world superiority.

## Clean exceptions invalidate all three freeze candidates

Each variant triggers 40 alarms among 240 correct workbooks (16.67%). All 40 occur in the deliberately valid `exception` structure, while the other clean structures have zero alarms. This concentration identifies a systematic modeling error: alternating but intentional formula families are treated as anomalous and promoted. It is not random noise and cannot be dismissed by averaging.

## The ablation pattern exposes synthetic alignment risk

The `semantics_only` ablation obtains Top-1 and MRR of 100% for A, B and C on all 360 events. That signal uses no labels at localization time, so the result is not evidence of label leakage. However, it shows that the deterministic validation generator produces errors that are perfectly separable by the same semantic regularities built into V6. Consequently, the large V6-B gain is useful mechanism evidence but is too optimistic as a generalization estimate. A third-party dataset with unseen templates is essential.

## Scope, data and metric definitions

- Grain: one event-method row; 360 events × 28 methods = 10,080 unique rows.
- Balance: six mutation families with 60 events each; no historical revealed 100-case data is included.
- Top-k: the true source formula is ranked at or above k; MRR is mean reciprocal source rank; EXAM is source rank divided by formula count.
- Macro Top-5: unweighted mean of six per-type Top-5 rates; weakest type is the minimum of those six rates.
- Clean alarm: any semantic promotion on one of 240 correct control workbooks.
- Uncertainty: paired event bootstrap, 10,000 draws, seed 20260819.

## Integrity and label-separation checks passed

The public and secret precommit hashes, 720-workbook inventory, V4/V6/method source hashes, 360 complete prediction shards, combined shard digest, 24-worker receipt, 28-method coverage, raw metric identities, aggregate summaries, bootstrap intervals, clean alarms, Enron receipts and selection gates were independently recomputed. Prediction metadata records `label_files_read=[]`; the secret label hash was released only after the complete-ranking receipt existed. No audit discrepancy was found.

## Registered gate failures

- V6-A: worst_type_top5_at_least_70_percent, range_boundary_top5_at_least_75_percent, clean_false_alarm_at_most_10_percent, enron_mrr_not_below_v4
- V6-B: clean_false_alarm_at_most_10_percent, enron_mrr_not_below_v4
- V6-C: worst_type_top5_at_least_70_percent, clean_false_alarm_at_most_10_percent, not_outperformed_by_key_ablation_over_0_02

## Limitations and robustness

This is a deterministic internal synthetic validation, not a third-party blind study. The perfect semantics-only result is the main robustness warning. Enron contains only 30 retrospective events and A/B fail its exact safety gate by a numerically tiny one-rank tail change. The clean-control failure is larger and practically important. Because the thresholds and stop rule were preregistered, changing them after seeing these results would invalidate the locked decision.

## Recommended next steps

1. Do not run `run_v6_freeze.cmd`; preserve the null selection receipt and all negative evidence.
2. Do not tune V6 or open V7 within this protocol. Retain V4-R1 as the frozen main model and present V6 as a mechanism experiment with a clear safety failure.
3. Do not request the 600-case third-party V6 package because no model was frozen. If a future separately preregistered study is approved, redesign ambiguity handling before obtaining new labels.
4. Use the BSS range-boundary result and the clean-exception counterexample as the strongest scientifically honest V6 contributions.

## Further questions

- Can a future model recognize legitimate multi-regime formula blocks without learning from the locked controls?
- How much of V6-B's gain persists on independently authored workbooks whose formula families were not generated by the V6 benchmark code?
- Can range-boundary semantics be added as a non-ranking review explanation instead of a main-rank promotion?
