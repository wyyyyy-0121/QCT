# V5-Core R2-R1 Retrospective Gate Interpretation

**Status:** post-run development interpretation; not a revised preregistration.

## Immutable original result

The original R2-R1 retrospective receipt remains authoritative:

`results/v5_core_r2_r1_retrospective_full/r2_retrospective_audit.json`

It reports `hard_gate_passed: false` solely because
`improvement_spans_at_least_four_error_types` is false.  That receipt must not
be edited, regenerated, or described as a passed preregistered experiment.

## What the failed implementation actually measured

The runner counted an error type as “improved” only when the **Full**
counterfactual stage moved at least one event above its own R2-Source rank.
It did not measure improvement over the original R2 model, V4, or a baseline.

On 480 development events, R2-R1 Source had the following Top-1 counts:

| Error type | Source Top-1 | Full rank changes |
|---|---:|---:|
| Absolute reference | 80/80 | 0 |
| Copy offset | 80/80 | 0 |
| Function replacement | 59/80 | 0 |
| Operator | 80/80 | 0 |
| Range boundary | 49/80 | 5 upward, 0 downward |
| Reference shift | 79/80 | 1 upward, 0 downward |

The counterfactual stage is deliberately restricted to a small observational
uncertainty set and is explicitly prohibited from displacing high-confidence
formulas.  Therefore, in four already-saturated types it had no legitimate
rank slot to improve.  The failed count is `2`, because only range boundary and
reference shift had safe upward moves; it is not evidence of a two-type source
localizer.

## Actual R2-R1 source recovery relative to original R2

On the same 480-event development protocol, original R2 Source versus R2-R1
Source changed the two previously weak mechanisms as follows:

| Error type | Original R2 Source Top-5 | R2-R1 Source Top-5 |
|---|---:|---:|
| Function replacement | 63.75% | 100.00% |
| Range boundary | 96.25% | 97.50% |

The other four types were already 100% Top-5 under original R2.  R2-R1 did
not use the old labels at inference time, but this comparison is still a
development result and cannot support an independent-performance claim.

## Remaining warning: boundary-protection tension

The `ablate_no_boundary` retrospective ablation has MRR `0.96458`, versus
R2-R1 Full MRR `0.94530` (difference `0.01929`).  It remains narrowly inside
the predeclared 0.02 guardrail, but it is evidence that boundary protection
may suppress correct rank improvements in the controlled data.  We will not
delete this ablation or claim that protection is uniformly beneficial.

## Decision

No additional parameter sweep is authorized from this receipt.  The next
permitted analysis is a **revealed-data pressure test** of the already-fixed
R2-R1 configuration on the historical 100-case cohort and Enron’s 30 events.
It addresses the boundary-protection warning without calling either cohort
blind or using it for a new tuning loop.  Only after this safety test is
recorded can the project decide whether R2-R1 is worth a genuinely new
independent confirmation set.
