# Structural Guard fresh blind comparison v1.1 result

## Technical summary

**Decision: DO_NOT_PROMOTE.** Frozen V5-R2 is not stronger than V4-R1 or
V5-v1 on this fresh 360-workbook synthetic blind cohort.

- Against V4-R1, R2 loses 19.72 percentage points of repair-case macro AP;
  the paired 30-cluster bootstrap 95% interval is -21.52 to -18.06 points.
- Against V5-v1, R2 has identical ranking AP (36.52%) but lower exact candidate
  repair coverage (2.74% versus 4.11%).
- All three models emit at least one cell candidate on every control workbook,
  so all fail the preregistered 20% control-workbook false-positive ceiling.
- R2 accepts no groups in repairable, ambiguous, or control cases.  This avoids
  unsafe automatic group repair, but its accepted-group repair coverage is 0%,
  far below the preregistered 50% floor.

This is an AI-administered internal blind result, not independent third-party
evidence.  The models, parameters, metrics, gates, runner, and scorer were
committed before the replacement generation seed was selected.  All three
PUBLIC predictions were run twice and hash-locked before SECRET reveal.

## Headline metrics

The repair set contains 180 workbooks and 2,190 erroneous formula cells.  The
control denominator is 120 workbooks.

| Frozen model | Repair macro AP | Exact candidate coverage | Candidate location precision | Control workbook FPR | Accepted-group exact coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| V4-R1 | 56.24% | 9.63% | 10.38% | 100.00% | n/a |
| V5-v1 | 36.52% | 4.11% | 10.00% | 100.00% | n/a |
| V5-R2 | 36.52% | 2.74% | 5.26% | 100.00% | 0.00% |

R2 passes only the relative control-FPR tie and the zero-unsafe-group gate.  It
fails the absolute control-FPR gate, both AP-superiority gates, the V4 exact
coverage non-inferiority gate, and both group-utility gates.

## Where the models differ

| Repair cohort | Error cells | V4-R1 exact repairs | V5-v1 exact repairs | V5-R2 exact repairs |
| --- | ---: | ---: | ---: | ---: |
| Singleton | 60 | 60 | 60 | 60 |
| Contiguous block | 390 | 145 | 30 | 0 |
| Systematic column | 1,740 | 6 | 0 | 0 |

R2's new group guard does not improve ranking over V5-v1 on this cohort; both
have exactly the same macro AP.  It also removes the 30 exact block candidates
that V5-v1 produced, while accepting no replacement groups.  V4-R1 remains
substantially better on contiguous blocks and has higher aggregate localization
quality, although its 100% control-workbook candidate rate means it is not a
safe automatic replacement either.

## Integrity evidence

- Frozen lock commit and tag target:
  `1e6a79f07b76fd4ee80a2e3ae263d1e649f61506`
- PUBLIC SHA-256:
  `2d965ec19c270fae2fc26ec6c2455d3376a9180dcb6dab49c7e3378413dfc1e4`
- PUBLIC-committed SECRET SHA-256:
  `13036e0c2da8430e5777637b62a522b3c48a7eb32680e83e5e72ce9a420b7bd7`
- V4-R1 prediction-lock SHA-256:
  `fdbe09eada0796293c36575a53275519540e39b969b2281fa57f8439e18c04bd`
- V5-v1 prediction-lock SHA-256:
  `4e2f0f6c0696a1382b50c38c5398ef4e2c894238a49908f01624836aa63df14f`
- V5-R2 prediction-lock SHA-256:
  `f204b2653a101efa78d883898f4fafc06c11adc9a1fbcd486f8943bb1fe70270`
- Both executions of every model produced the same lock.
- Post-reveal audit checked 240 original/mutated workbook pairs and 2,250
  declared changed cells.  The mutation ledger matched exactly; undeclared
  formula, non-formula, and sheet-structure differences were all zero.

Attempt 1 was stopped before reveal because V4 serialized its wall-clock timing
inside evidence, making byte hashes nondeterministic.  The v1.1 correction only
excluded `localization_seconds`; a label-free audit confirmed that all 360
rankings, scores, candidates, and other evidence were identical.  Attempt 1's
PUBLIC and SECRET were retired and a new seed produced this cohort.

## Scope, limitations, and interpretation

The cohort has 30 paired clusters, three header-language strata, and eight error
or ambiguity types per cluster, but it is generated from one declared tabular
workbook family.  The random values and anonymous identities are fresh, while
structural diversity remains narrower than a natural-workbook corpus.  This
limits external validity but does not explain away the within-cohort comparison:
all three frozen models receive the same workbooks and labels.

The evidence supports two separate conclusions:

1. R2 is not a promotion candidate over either V4-R1 or V5-v1.
2. V4-R1 is the strongest of these three on localization and exact repair in
   this cohort, but none of the three meets the preregistered control-selectivity
   requirement for safe automatic use.

## Recommended next step

Keep R2 frozen as a negative/diagnostic result.  Do not tune on this SECRET and
then reuse it as blind evidence.  A successor needs a new core that jointly
improves multi-cell coverage and suppresses control candidates, followed by a
new never-seen cohort and, ideally, an independently administered natural-file
confirmation set.

