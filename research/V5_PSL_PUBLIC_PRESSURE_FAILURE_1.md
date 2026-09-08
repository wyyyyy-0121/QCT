# V5-PSL public-pressure failure and audit reproducibility record 1

Date: 2026-08-30

The first public-pressure run completed all 90 cases and 450 method events at
commit `71459f5`. The revealed event table showed three failed candidate gates:

- default error Top-5 was 35%, below the required 60%;
- default control actionable rate was 30%, above the allowed 15%;
- default review efficiency was 5.43 source hits per 100 inspected cells, below
  the no-perturbation baseline of 8.54.

No formal audit receipt was produced. Independent recomputation first rejected
`modified_euses_001` because evidence floats differed at approximately `1e-15`.
A subsequent 24-process read-only diagnosis also found that complete ranking
positions 17 and 18 exchanged order for `modified_euses_011` and
`modified_euses_013`. Their states, Top-5 rankings and action sets were
unchanged, but the protocol requires the complete semantic output to reproduce.

The audit and prediction schedulers now share a default maximum of 24 worker
processes and record the requested worker count. This scheduling change does
not alter model calculations and is not the single permitted post-pressure
mechanism revision. The existing run remains historical revealed development
evidence bound to `71459f5`; it cannot be relabeled as output from a later
commit. The next mechanism revision must address both the failed performance
gates and deterministic complete ranking before a fresh formal run.
