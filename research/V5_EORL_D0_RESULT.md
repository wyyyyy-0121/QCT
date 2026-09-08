# FormulaGuard EORL D0 mechanism-availability result

Date: 2026-09-01  
Protocol: `formulaguard_eorl_d0_v1`  
Preregistration lock: `ab22ec2`  
Implementation lock and correction: `b31bef1`, `f942b0b`  
Reproduction receipt: `results/eorl_d0/reproduction_receipt.json`
Posthoc topology audit: `9a673de`, `results/eorl_d0/topology_followup_receipt.json`

## Scope

D0 tests whether the preregistered expected-output task can be constructed broadly
enough and whether frozen peer repairs at known source formulas can reduce the output
residual. It is an oracle mechanism-availability audit, not a deployable localizer or
a main-model result. Full EORL ranking was forbidden until D0 passed.

The first attempted run stopped before task construction because byte-identical
control workbooks are represented by one canonical profile path. The implementation
correction changed profile resolution from path equality to the already frozen
`unit_id` plus workbook SHA-256 identity; all 90 event identities matched. The fix was
committed as `f942b0b` before any D0 result was produced and did not change an output,
repair, metric, threshold, or gate.

## Reproduced result

| D0 quantity | Observed | Required | Status |
| --- | ---: | ---: | --- |
| eligible error events | 26/60 | >=40 | failed |
| eligible error structure groups | 6/17 | >=12 | failed |
| eligible controls | 30/30 | >=24 | passed |
| source-residually-recoverable errors | 18 | >=24 | failed |
| source-residually-recoverable groups | 6 | >=8 | failed |
| retained error base residual | positive in 26/26 | required | passed |
| retained control base residual | zero in 30/30 | required | passed |
| LibreOffice stable-sample agreement | 11/12 (91.67%) | >=90% | passed |
| independent-process reproduction | byte-identical | required | passed |
| protected/forbidden prediction inputs | 0 | 0 | passed |

The two independent runs produced byte-identical tasks, scoring records, cross-engine
records, and receipts. Their shared receipt SHA-256 is
`132a5e2fccadaeed8a0306dde2af8848ae2a1497df47081cb668d71af5c91f8b`.
The reproduction receipt SHA-256 is
`9a63fd39b41a6fb0c064e3cef4977c9695bc7a6bdffefa600e6f5ffd8483a382`.

## Coverage diagnosis

| Public cohort | Total events | Eligible tasks | Eligible error groups | Recoverable errors | Recoverable groups |
| --- | ---: | ---: | ---: | ---: | ---: |
| Info1 | 2 | 0 | 0 | 0 | 0 |
| Integer corpus | 44 | 15 controls, 0 errors | 0 | 0 | 0 |
| Modified EUSES | 44 | 15 controls, 26 errors | 6 | 18 | 6 |

All 34 ineligible errors failed because no visible formula sink was a strict dependency
descendant of the recorded source formula. They did not fail because of evaluator
errors, nonnumeric values, missing formulas, visibility, or unchanged output values.
The preregistered sink proxy therefore narrows the user-selected-output contract to a
topology that is absent from all Integer/Info1 errors in this public set.

Within the 26 eligible Modified-EUSES errors, 18 true source formulas have a frozen
peer hypothesis that reduces expected-output residual. Seventeen of those 18 best
hypotheses reduce residual to zero in the internal evaluator. One sampled case,
`modified_euses_003`, disagrees with LibreOffice on whether the selected best source
repair has positive gain; the overall stable sample still passes at 91.67%.

This is evidence that expected-output residual can validate a peer repair when the
task topology is present. It is not evidence of cross-corpus localization: every
recoverable error comes from one public corpus and only six structures.

## Posthoc topology boundary

After the preregistered failure was locked, a separate read-only audit removed the
sink condition and asked the broader question: does any recorded source have any
formula descendant at all? The audit used the same frozen public manifest, 24 workers,
and no protected input.

| Public cohort | Error events | With any formula descendant | Without formula descendants |
| --- | ---: | ---: | ---: |
| Info1 | 2 | 0 | 2 |
| Integer corpus | 29 | 0 | 29 |
| Modified EUSES | 29 | 26 | 3 |
| **Total** | **60** | **26** | **34** |

The receipt SHA-256 is
`7cf2025f3de8ec5febe6d9140bd8abd19481b5ec282c02a2a283aa11f0ed6119`.
This is a posthoc topology diagnosis, not a revised gate or model result. It shows that
removing only the formula-sink restriction cannot recover any Info1 or Integer error:
those 31 sources have no downstream formula cell that could serve as an intermediate
output. The 26/60 EORL availability ceiling is therefore already the broader
source-to-formula-descendant ceiling on these public pairs.

## Decision

EORL v1 fails D0 and stops before full-ranking implementation. The `40/12/24/8`
thresholds, formula-sink proxy, peer generator, tolerance, and cross-engine rule remain
unchanged. D1, baselines, ablations, Enron/Historical evaluation, protected access,
and formal `V5-R1` naming are not authorized.

The result distinguishes a benchmark-contract failure from a total mechanism failure:
peer residual correction is strong in the one eligible corpus, while the fixed sink
proxy has insufficient public task coverage. The follow-up audit also closes a simple
"use an intermediate formula output" continuation on the current public pairs, because
Info1 and Integer provide no downstream formula at all. A future model must use a
different learning target and be separately preregistered; it cannot retroactively
rescue EORL v1 or report the 18 recoverable source events as localization accuracy.
