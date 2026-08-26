# FormulaGuard V6 A/B/C development comparison

## Decision

All three preregistered development variants are complete and independently auditable. This comparison does not select a model: the frozen method specification reserves selection for the one-shot 360-event locked validation after all A/B/C predictions and matched ablations are on disk.

| Variant | Mechanism | Dev macro Top-5 | Dev MRR | Red-team macro Top-5 | Worst red-team type | Clean FPR | Enron MRR delta |
|---|---|---:|---:|---:|---:|---:|---:|
| V6-A | FFC | 87.92% | 0.4245 | 68.89% | 1.67% | 16.67% | -0.00000098 |
| V6-B | FFC+BSS | 100.00% | 0.4540 | 85.28% | 35.00% | 16.67% | -0.00000098 |
| V6-C | FFC+BSS+safety | 90.58% | 0.4388 | 85.28% | 35.00% | 16.67% | +0.00000000 |

## Mechanism interpretation

- BSS is strongly supported as a range mechanism: B minus A is +72.50% development range-boundary Top-5 and +16.39% red-team macro Top-5.
- The C safety constraints do not reduce the registered clean exception alarm rate (+0.00%) and leave red-team macro Top-5 unchanged (+0.00%).
- C is more conservative on development data: C minus B is -9.42% macro Top-5; the change is concentrated in absolute-reference cases (-56.50%).
- C exactly preserves V4 on the 30-event Enron retrospective check, while A/B share a one-rank tail regression. Enron remains retrospective and is not independent evidence.

## Integrity and next step

- all_independent_round_audits_passed: true
- shared_input_model_and_parameters: true
- prediction_label_isolation: true
- variant_identity_exact: true
- all_rounds_workers_24: true
- all_registered_event_counts_present: true
- No development result is used to change formulas, weights, thresholds, candidates or validation labels.
- Next: run the one-shot locked 360-event validation with all fixed variants and eight matched ablations.
