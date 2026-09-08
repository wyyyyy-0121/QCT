# FormulaGuard EORL expected-output residual localization preregistration

Date: 2026-09-01  
Protocol: `formulaguard_eorl_v1`  
Research code: `EORL` (Expected-Output Residual Localizer)  
Status: frozen before task construction, output evaluation, or EORL implementation

## 1. Research question and model identity

`V4-R1` remains the only formal main ranker. AETR showed that formula-level evidence
can be learned on constructed faults but did not transfer to Enron. VRER then stopped
before training because author-verified, licensed correction histories could not meet
the frozen scale and diversity gate.

EORL changes the inference contract instead of fitting another head under the failed
single-workbook/no-oracle contract. At prediction time the user supplies exactly:

1. one formula cell regarded as an important output; and
2. the expected numeric value of that output under the current workbook inputs.

EORL asks whether label-free, peer-generated repair hypotheses can be evaluated by
their reduction of this observed output residual and thereby produce a complete,
explainable responsibility ranking. It is not a patched VRER, PSL, or historical V5.
`EORL` is a research name only; it may become a `V5-R1` candidate only after every
public and protected gate passes.

## 2. Prior-work and contribution boundary

Expected outputs, dependency cones, dynamic slicing, spectrum-based fault
localization, constraint debugging, GoalDebug-style reasoning, counterfactual repair,
peer formula translation, suspiciousness ranking, and complete formula ranking are
established ideas. FormulaGuard cannot claim any one of them as an invention.

The falsifiable contribution hypothesis is narrower:

> Within a user-selected failed output's dependency cone, a complete ranking by the
> counterfactual reduction in expected-output residual produced by independently
> peer-supported formula repairs identifies responsible formulas more accurately than
> dependency position, anomaly evidence, repair availability, support, or minimal edit
> alone, while retaining a concrete repair-and-propagation explanation.

The paper may describe this combination as a contribution only if it exceeds all
compatible baselines under grouped evaluation and later protected confirmation. V4 is
reported as a burden-free historical reference, not as a same-information competitor.

## 3. Frozen inputs and forbidden data

Development uses only the 90 already revealed public paired events: 60 errors and 30
controls from the public pressure manifest. The following identities are frozen:

- observation profiles SHA-256:
  `26f7d1d64a65860fb90714a51beb602742d28d1cfefeea8cbadf331b0e1463dc`;
- revealed event table SHA-256:
  `c68e2436957a83f6e8e80e6de6c5a3d45ca35b71e162ebc928275352ba90dd34`;
- public pair manifest SHA-256:
  `bed0ac4e026fd2afea1552d00262b00c0b6034cbc6cbcabf6355c9115719ac54`;
- frozen label-free signal shards SHA-256:
  `17fab17b109376e22d339a25d3861aa8c72e5c05a2c410cceab1845938a93890`;
- label-free hypothesis configuration SHA-256:
  `7cc319ad154cd874e8fda1249daa334ecbd6f37417fdcb4b52ee006c663b30bd`.

The 30 Enron, 100 Historical, and non-paired public events cannot enter EORL v1
development because no defensible user-supplied expected output is available for
them. They must not be assigned expected values from labels, guessed correct formulas,
or cached downstream values.

The directory `/home/ayaka/code/FormulaGuard_240_120/` remains forbidden: it must not
be listed, opened, hashed, searched, copied, or overlap-checked before a complete
candidate and protected protocol are committed. No existing protected metadata may be
used to choose EORL rules or gates.

## 4. Offline user-contract construction

The public pair builder may read revealed source labels and the correct paired
workbook only to construct and score benchmark tasks. Neither is passed to EORL.

For an error event, an eligible output must:

1. be the same visible formula cell in the observed and reference workbooks;
2. be a strict dependency descendant of at least one recorded source formula in the
   observed workbook;
3. be a visible formula sink in the observed dependency graph;
4. evaluate to finite numeric values in both workbooks under their existing inputs;
5. differ by more than `1e-9 * max(1, abs(reference_value))`.

Among eligible outputs, choose the one with the largest observed formula ancestor
cone, then sheet name, row, and column in ascending order. The expected value is the
reference workbook's evaluated value. Conditioning the benchmark on an affected
output models a user who reports a wrong result; it is not unconditional workbook
detection coverage and must never be reported as such.

For a control event, choose the shared, visible, finite numeric formula sink with the
largest ancestor cone and the same deterministic ties. Its reference value is the
expected value. The observed and reference values must agree within the same tolerance.

The persisted task manifest records identities, hashes, output cell, expected/base
values, cone size, and construction reason. Source labels and correct formulas are
kept in a separate scoring-only artifact and are forbidden EORL inputs.

## 5. D0 mechanism-availability gate

D0 runs before EORL ranking is implemented. For each eligible error task it evaluates
only the already frozen, at-most-four peer repair hypotheses at recorded source
formulas. It measures an oracle availability ceiling, not deployable localization.

For numeric output `y` and expected value `e`, define:

`rho(y, e) = abs(y - e) / max(1, abs(e))`.

A source is residually recoverable when at least one frozen peer hypothesis reduces
`rho` by more than `1e-9` and does not introduce an evaluation error at the selected
output. D0 passes only if all conditions hold:

1. at least 40 of 60 error events yield eligible tasks;
2. eligible errors cover at least 12 of the 17 frozen error structure groups;
3. at least 24 of 30 controls yield eligible, matching-output tasks;
4. at least 24 error events and at least 8 structure groups are residually recoverable
   at a true source formula;
5. every retained error has positive base residual and every retained control has zero
   residual within tolerance;
6. task construction and source-recoverability receipts are byte-identical in two
   independent processes;
7. a stable 20% hash sample agrees with LibreOffice on finite output availability,
   base/reference residual status, and the sign of the best source-repair gain in at
   least 90% of sampled tasks;
8. protected inputs, Enron/Historical labels, future formulas, and expected values from
   any source other than the paired public reference are absent.

Any failure stops EORL v1 before full ranking. Thresholds, output-selection rules,
evaluator tolerance, and repair generators cannot change after D0 is observed.

## 6. Frozen EORL ranking

Only D0 passage authorizes implementation. At inference, EORL builds the selected
output's formula ancestor cone. For every formula in that cone it evaluates each of
the at most four already frozen peer hypotheses. Let `rho0` be the observed output
residual and `rho_h` the residual after one formula replacement. Define:

`gain_h = max(0, (rho0 - rho_h) / max(rho0, 1e-12))`.

The cell score is the maximum finite `gain_h`; a cell without a valid hypothesis has
score zero. No formula label, workbook identity, cohort, source label, correct formula,
or reference workbook is an input. The expected value is used only through `rho`.

When `rho0` is within tolerance, EORL abstains from proposing a repair. Otherwise the
complete formula ranking is:

1. positive-gain cone cells by decreasing gain;
2. exact-zero-residual repair before nonzero residual when gains tie;
3. higher independent peer support, then higher hypothesis support;
4. lower frozen V4 rank, then original parser inventory order;
5. remaining zero-gain cone cells in frozen V4 order;
6. formulas outside the cone in frozen V4 order.

V4 is a tie/fallback order only and cannot change a non-tied residual decision. Impact,
filename, raw address, workbook identity, and cohort cannot change the score.

Each positive action reports the observed formula, proposed peer repair, dependency
path to the selected output, output before/after, expected value, residual before/after,
gain, and peer support. Explanation fields are outputs, not ranking inputs.

## 7. Model-complexity gate

EORL v1 contains no fitted weights, neural network, embedding model, feature search,
threshold search, or hyperparameter tuning. This is deliberate: D0/D1 must establish
that expected-output residual adds causal responsibility information before model
capacity is increased.

A neural successor is not authorized by an EORL failure. It would require a separate
preregistration and at least 500 non-overlapping expected-output error episodes from at
least 50 structure groups, plus evidence that deterministic EORL passes its mechanism
gate but leaves a stable grouped residual that fixed observable features could explain.

## 8. Required baselines and ablations

All compatible baselines receive the same output cell, expected value, dependency
graph, review budget of five, eligible task set, and deterministic ties:

- `v4`: unchanged frozen V4, reported as a no-added-information historical reference;
- `cone_v4`: cone formulas in V4 order, then formulas outside the cone;
- `cone_distance`: farthest ancestor first, then V4, reproducing the Branch-C idea;
- `repair_support`: cone formulas by repair availability, independent support, and
  hypothesis support without output residual;
- `minimal_edit`: cone formulas by the smallest AST edit among peer hypotheses without
  output residual;
- `minimal_edit_residual`: positive residual-reducing hypotheses by smallest AST edit,
  a transparent GoalDebug-style proxy rather than a reproduction of GoalDebug;
- `eorl_top1_hypothesis`: EORL using only the first frozen peer hypothesis;
- `eorl_no_support_ties`: EORL gain followed directly by V4 order;
- `oracle_after_formula`: scoring-only ceiling that substitutes the paired correct
  formula at source cells; it is not a deployable baseline.

Tarantula/Ochiai require multiple pass/fail test spectra and are incompatible with one
expected output under one fixed input state. They are recorded as unavailable rather
than approximated with fabricated spectra. Any later task with real spectra must add
them before protected evaluation.

## 9. D1 public development gates

D1 evaluates the immutable EORL implementation once on all D0-eligible tasks. Metrics
are error structure-group macro Top-5 and MRR, event micro metrics, control abstention,
per-corpus results, five stable structure folds, and 10,000 structure-group bootstrap
resamples with seed `20260901`.

EORL passes only if every condition holds:

1. structure-group macro Top-5 exceeds `cone_v4` by at least 5 percentage points and
   MRR does not fall;
2. Top-5 exceeds the strongest compatible non-oracle baseline by at least 5 points and
   MRR does not fall;
3. Top-5 exceeds unchanged V4 by at least 5 points and MRR does not fall, explicitly
   labeled as an added-information comparison;
4. the 95% group-bootstrap interval for EORL minus the strongest compatible baseline
   has a lower bound above zero;
5. at least four of five structure folds have nonnegative Top-5 differences versus
   both `cone_v4` and the strongest compatible baseline;
6. neither Integer nor Modified-EUSES regresses more than 5 points versus `cone_v4`;
7. control repair-action rate is zero and all control abstentions are reproduced by
   the independent process;
8. every eligible formula receives a deterministic rank and every positive-gain Top-5
   item has the complete explanation record.

Info1 has two errors and remains descriptive. No weights, gates, ties, output choices,
or hypotheses may be revised after D1. Failure stops EORL v1 and leaves `V4-R1` as the
only main ranker. A smaller reproducible gain may be reported as a secondary result but
cannot authorize `V5-R1` or protected access.

## 10. Candidate lock and protected one-shot gate

If D0 and D1 pass, commit source, tests, environment, task hashes, full public
predictions, baselines, ablations, explanation schema, and a protected evaluation
protocol before any protected path access. The protected protocol must define how a
producer-provided original/reference pair simulates the same output-and-expected-value
contract without exposing source labels to prediction.

Only after that commit may the user's standing authorization be used for one protected
`240+120` execution. Protected results cannot tune EORL. Promotion requires the frozen
protected Top-5/MRR superiority, per-producer/source noninferiority, control abstention,
coverage, cross-engine, and reproduction gates. Until then, no paper may call EORL the
main model or claim broad superiority.

