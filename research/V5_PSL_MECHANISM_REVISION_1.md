# V5-PSL mechanism revision 1: static anchor and repair verification

Date fixed: 2026-08-30
Status: fixed before implementation and before any revision-run result

## Scope

This is the single permitted post-pressure structural revision of the
development candidate. Its output identity is `V5-PSL-dev1-rev1`; this remains
a development name and must not be shortened to `V5-R1`. The revision uses the
same 90 revealed public cases only after its implementation and gates are
committed. No third-party PUBLIC or SECRET content may be read.

The revision follows the root cause in
`V5_PSL_PARAMETER_TUNING_FAILURE_1.md`. It is not another parameter search.
There is one implementation, one complete public run and one independent
recomputation audit. Failure ends this research line.

## Ranking contract

The complete formula ranking is anchored to the existing label-free static
score: 0.60 formula anomaly plus 0.40 graph anomaly. Scores are ordered
descending with canonical cell identity as the final tie-break. General input
response families remain in the evidence report but cannot promote or demote a
cell. Candidate generation and repair results cannot alter the complete
ranking. Thus the `full` and `no_perturbation` complete rankings must match
exactly, while their action policies differ.

Only the static Top-5 is eligible for repair verification. Each cell receives
at most two label-free candidate formulas and each candidate uses at most 12
matched placebo edits. A repair family is countable only with at least eight
successfully evaluated placebo controls. Existing fixed strength thresholds
remain unchanged:

- strong: empirical tail at most 0.10, effect at least 0.20 and stability at
  least 0.75;
- weak: empirical tail at most 0.20, effect at least 0.10 and stability at
  least 0.60.

The finite-sample empirical tail remains `(1 + exceedances) / (1 + controls)`.
No threshold is relaxed when too few matched controls exist. Candidate
selection, ranking keys and serialized non-runtime floats are quantized to 12
decimal places before a decision or exact-reproduction comparison.

## Action contract

`verified repair` means a weak or strong repair-specific family satisfying the
minimum-control rule. General response families alone never trigger action.

- `localized`: exactly one static Top-5 cell has a verified repair, it is the
  static Top-1 cell, and either its repair family is strong or it is weak while
  the static Top-1 minus Top-2 score margin is at least 0.15;
- `review`: at least one static Top-5 cell has a verified repair but the
  localization rule does not hold; action is the static Top-5;
- `abstain_unidentifiable`: the workbook is supported but no verified repair
  exists;
- `unsupported`: the existing scenario-count and evaluation-coverage rules
  fail.

The `no_identifiability_gate` ablation reviews the static Top-5 for every
supported workbook. `no_role_conditioning` keeps the same ranking and action
rules with unconditioned peers. `no_downstream_placebo` removes repair
verification and therefore cannot create a verified repair. `no_perturbation`
keeps the same static ranking and reviews Top-5 for every supported workbook.

## Revision-run gates

All original public-pressure integrity and performance gates remain. The
revision adds final-aligned selective safeguards on the 60 identifiable public
errors and 30 regular controls:

- localized coverage is at least 30% of identifiable errors;
- Top-1 among localized identifiable errors is at least 75%;
- Top-5 among localized identifiable errors is at least 95%;
- localized control rate is at most 5%;
- actionable control rate is at most 15%;
- global error Top-5 is at least 60%;
- review efficiency is not below `no_perturbation`;
- at least four of the five fixed original-workbook folds have global error
  Top-5 at least 50% and control actionable rate at most 25%;
- complete semantic recomputation is exact after runtime fields are removed.

The final 240+120 scorer is clarified before any external content is opened:
`localized_top1` and `localized_top5` use localized identifiable errors as
their denominators, as implied by "localized accuracy" and selective-risk
terminology. Overall identifiable Top-1 and Top-5 remain separately reported;
they are not relabeled as localized accuracy. Unsupported cases cannot enter
the localized numerator or denominator. This resolves the prior contradiction
between the plain-language gate and the implementation's metric names without
using any external result.
