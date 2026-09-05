# V5 successor baseline diagnostic result

Date: 2026-08-30
Status: complete; no feasibility policy eligible

## Evidence boundary

The fixed diagnostic in `V5_SUCCESSOR_BASELINE_DIAGNOSTIC.md` ran once at
commit `57a381f` with 24 worker processes. All 90 label-free shards were written
before `case_kind` and `source_cells` were used for scoring. No third-party
confirmation file was read. The evidence is revealed development data and
cannot support an independent or preregistered superiority claim.

Local ignored evidence hashes are:

- completion: `0bd6ec2b03c9d5dd3047ac328af05a1a564e756048690285adff8118451cf1fa`;
- events: `33ef928df1ed9aee31b2d107041a5bddf2c4790c75d747567a4138bc75479998`;
- metadata: `8e9df92a5f77ff82c30b97662ff3a531ad4e378206f62c16897168a45ff84a0b`.

## Ranking comparison

| Existing ranking | Top-1 | Top-5 | MRR |
| --- | ---: | ---: | ---: |
| V4-R1 | 36.67% | 56.67% | 0.4688 |
| V4.3-Semantic-C | 36.67% | 58.33% | 0.4738 |
| V5-PSL static anchor | 36.67% | 63.33% | 0.4822 |

These are same-data retrospective differences. They do not reopen either the
rejected V4.3 main freeze or the terminated V5-PSL line.

V4.2's optional sixth review cell increased case coverage from 34/60 to 36/60
while adding only two inspected cells across the run. This is consistent with
its frozen auxiliary role; it does not change V4's complete ranking.

## Selective feasibility result

No fixed policy passed all advancement gates. The strongest bounded probe was
"exactly one V4 strong-counterfactual cell in Top-5":

- 19 error cases received one action and 17 actions hit the true source;
- acted-error case precision was 89.47%;
- source-hit rate was 28.33%, below the fixed 30% gate by one case;
- 0/30 clean controls received an action;
- efficiency was 89.47 source hits per 100 inspected cells;
- four of five original-workbook folds passed the fixed stability condition.

The peer-supported strong variant produced the identical decisions. It cannot
be selected as a pass because the source-hit gate failed. The broader unique
strong-or-moderate rule reduced source-hit rate to 21.67%, and V4 Top-1 strong
acted on 43.33% of clean controls. The terminal V5-PSL action found only 2/60
sources while acting on 36.67% of controls.

V4 candidate availability was not the limiting factor: 57/60 sources had a
selected candidate and 38 selected candidates exactly matched the original
formula. The remaining gap is a conservative, workbook-level action decision,
not candidate generation or another response-score threshold.

## Decision

The diagnostic authorizes no new architecture. The near-miss strong policy may
receive one explicitly disclosed replication on the older package that the
owner has downgraded to revealed trial data. That replication cannot alter this
failed gate or count as external validation. A new model preregistration is
considered only from the combined mechanism evidence, and final promotion still
requires the separately created, unseen custodian set.
