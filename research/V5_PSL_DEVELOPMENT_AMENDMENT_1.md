# V5-PSL development amendment 1: bounded parameter comparison

Date: 2026-08-30

## Status and evidence boundary

The preregistered `V5-PSL-dev1` public-pressure attempt at commit `71459f5`
failed three gates and did not produce an audit receipt. Those results remain a
failed preregistered attempt. After seeing them, the 90 public cases are
explicitly reclassified as revealed development data for a single bounded
parameter comparison. No result from this comparison may be called an
independent test, a preregistered pressure pass, or evidence of superiority.

The external 30-template, 240-error and 120-control confirmation set remains
unseen and is not used by this amendment. It remains the only evidence capable
of promoting a frozen candidate to the paper's main model.

## Fixed comparison before execution

The comparison contains the original default, eleven conservative variants and
the fixed `no_perturbation` baseline. Strong tail remains `0.10`; weak tail
remains `0.20` except in the strict profile, where it is `0.15`. Evidence
profiles are crossed with localization margins `0.15` and `0.25`:

| Profile | Strong effect | Strong stability | Weak tail | Weak effect | Weak stability |
| --- | ---: | ---: | ---: | ---: | ---: |
| default | 0.20 | 0.75 | 0.20 | 0.10 | 0.60 |
| effect30 | 0.30 | 0.75 | 0.20 | 0.15 | 0.60 |
| effect40 | 0.40 | 0.75 | 0.20 | 0.20 | 0.60 |
| stability85 | 0.20 | 0.85 | 0.20 | 0.10 | 0.70 |
| balanced | 0.30 | 0.85 | 0.20 | 0.15 | 0.70 |
| strict | 0.40 | 0.85 | 0.15 | 0.20 | 0.70 |

All other parameters remain those of `PSLConfig`. Relaxed thresholds are not
searched because the revealed failure already has excessive control actions.
The grid, fold algorithm and selection implementation are fixed in
`scripts/tune_v5_psl_parameters.py` before any grid result is produced.
The formal run requests 24 worker processes and records the requested count in
its metadata. Parallelism changes scheduling only; each workbook evaluates all
profiles sequentially in one worker.

## Grouping and selection

Cases sharing the same original-workbook SHA-256 stay in one of five
deterministic folds. This keeps related injected errors and clean controls from
being treated as independent templates. A parameter profile is eligible only
when all conditions hold on the full 90-case development set:

- supported rate is at least 80%;
- error Top-5 is at least 60%;
- control actionable rate is at most 15%;
- review efficiency is not below the fixed no-perturbation baseline;
- at least four of five folds have error Top-5 at least 50% and control
  actionable rate at most 25%.

Eligible profiles are ordered by worst-fold Top-5, global review efficiency,
global error Top-5, lower control action rate and finally profile identifier.
If no profile is eligible, parameter tuning alone is rejected. Its failure
surface may guide one documented structural successor, but no near-miss may be
reported as a gate pass and no third-party file may be opened.
