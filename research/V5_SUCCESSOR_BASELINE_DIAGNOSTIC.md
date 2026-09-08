# V5 successor baseline diagnostic

Date fixed: 2026-08-30
Status: fixed before execution on revealed public-development data

## Purpose and evidence boundary

V5-PSL has terminated after its single structural revision failed. This
diagnostic does not revise or rename V5-PSL and does not create a new model. It
compares existing label-free outputs on the same 90 cases, which are permanently
classified as revealed development data. No result may be described as an
independent test, a preregistered pressure pass, or evidence of superiority.

All 90 prediction shards must be written before `case_kind` or `source_cells`
is used for scoring. The unseen 240-error plus 120-control confirmation set
must remain untouched. The run uses 24 worker processes and records source,
manifest, event and shard hashes.

## Fixed comparisons

Complete ranking metrics are reported without tuning for frozen `V4-R1`,
`V4.3-Semantic-C` and the terminated V5-PSL static anchor. `V4.2-Review-B` is
evaluated only as the frozen V4 Top-5 plus its optional sixth review cell.

The following action policies are fixed before execution:

- V4 fixed Top-5;
- V4.2 Top-5 plus optional sixth review cell;
- the terminal V5-PSL revision action;
- V4 Top-1 only when its evidence is `strong_counterfactual`;
- exactly one `strong_counterfactual` cell in V4 Top-5;
- exactly one strong or moderate counterfactual cell in V4 Top-5;
- exactly one V4 Top-5 strong cell whose candidate has at least two supports
  and includes peer translation.

The last four are bounded feasibility probes, not candidate models. No score
weight, threshold, promotion distance, candidate budget or policy is searched
after observing the run.

## Advancement rule

A feasibility policy can justify writing a separately named architecture
preregistration only if all conditions hold:

- source-hit rate is at least 30% of error cases;
- at least 75% of acted error cases contain the source;
- at most 15% of clean controls receive an action;
- source hits per 100 inspected cells are not below fixed V4 Top-5 review;
- at least four of five original-workbook folds simultaneously achieve 20%
  source-hit rate, 60% acted-error precision and at most 25% control actions.

Failure means these existing evidence labels do not justify another selective
architecture. In that case the defensible paper system remains frozen V4-R1
with V4.2 as an explicitly auxiliary sixth-review module; a new model would
require a genuinely new mechanism and a new development protocol.
