# FormulaGuard VEPR natural-edit-prior preregistration

Date frozen: 2026-09-03

Protocol: `formulaguard_vepr_v1`

Research code: `VEPR` (Version-Evolution Prior Ranker; not a formal version name)

Status: frozen before materializing VEPR transition labels, features, fitted
weights, rankings, or public predictions

## 1. Question and scope

`V4-R1` remains the only formal main ranker. Existing single-workbook feature
heads trained on constructed FormulaGuard faults did not transfer safely to
natural Enron errors. VRER could not obtain enough licensed, author-confirmed
corrections. VDEL changed the inference contract but stopped because only 21
mixed re-edit windows survived its three-version candidate definition.

VEPR tests a different source of supervision and a different target:

> Given one current workbook snapshot, can a model trained only on natural
> workbook evolution rank the formula cells that an author will directly edit
> in the immediately next version, and does that frozen edit prior transfer to
> silent formula-source localization better than `V4-R1`?

The prediction candidates are all same-address formula cells in the current
snapshot, not formulas already edited in a prior delta. The current snapshot is
the only inference input. A future direct edit is an author-review proxy, not an
error label: ordinary development, assumption changes, and refactoring are also
positive. VEPR cannot claim fault truth from VEnron. It becomes a candidate for
the FormulaGuard localization task only if a frozen model later passes the
separate revealed-public and unopened-external transfer gates in this protocol.

VEPR does not revise VDEL. In particular, it does not add single-edit windows to
VDEL, predict re-edit longevity, expose a prior version at inference, or reuse
VDEL's 21-window labels. It also does not revive VHRL's rollback or explicit-
error proxies, VRER's author-confirmed-correction claim, FSPR's formula-pair
fifth-slot rule, or AETR's FormulaGuard-label-trained atomic head.

## 2. Frozen source evidence

VEPR may read only these existing public VEnron formula-only artifacts:

- `results/venron_profile_v0/profile_receipt.json`, SHA-256
  `54b24336912fa0ce4d50f55ef1897bef4e7ed40e1d7313a9a17fff6fcba924e0`;
- `results/venron_profile_v0/profile_index.json`, SHA-256
  `f337ad4448aec142bb529a90b514dc1f8fe8235aae29414b20750cd8ab7b0cc3`;
- `results/venron_gate_v0/gate_result.json`, SHA-256
  `4743f0a1fb929afc6d98f4ebbfa3ac9b74022fa272c98f84da2f95f8b91b723e`;
- `results/venron_gate_v0/transition_manifest.json`, SHA-256
  `8a8ff6e13fdebc44f28d4abb509357c9475c3badf00a679d8bbf33456cc9a5ee`.

The frozen V0 audit already established 7,294 parsed versions in 360 evolution
groups, 1,190 adjacent transitions with a direct same-address formula-text edit
across 152 groups, and 4,316 unchanged transitions. Those aggregate facts only
justify an availability audit; they are not VEPR results.

For overlap exclusion only, VEPR may open the 96 byte-unique observed public
workbooks identified by `results/core_reset_b_phase0/scoring_groups.csv`,
SHA-256
`6f5384990f8758258dba4c556bc1f119e498d850ab37c2d092ccaa82f6e88be7`.
It may retain only formula text, sheet title, address, workbook SHA-256, cohort,
and structure-cluster ID. Event labels, source cells, correct formulas, case
kinds, expected outputs, answer workbooks, and V4 outcomes are forbidden until
the public scoring stage.

No path under either protected `240+120` package may be listed, searched,
hashed, opened, copied, matched, or otherwise accessed before the candidate and
complete public prediction lock defined below. SpreadsheetBench 2 remains
unreceived.

## 3. Frozen overlap exclusion and folds

VEPR reuses VDEL's already frozen formula-containment test without changing a
threshold. For each workbook, compare exact `(sheet, address, formula)` entries
and `(sheet, address)` keys. A VEnron version is a near duplicate of an observed
public workbook when both have at least 20 formulas and either:

1. exact-entry containment relative to the smaller formula inventory is at
   least `0.80`; or
2. coordinate containment is at least `0.90` and formula agreement on shared
   coordinates is at least `0.80`.

An entire VEnron evolution group is excluded if any version matches. The audit
may reuse the stable excluded-group hashes from a verified VDEL run, but it must
recompute that no excluded group contributes any VEPR row. No raw formula,
public path, or cross-corpus match row may be exported.

Retained evolution groups are assigned to one of five folds by
`int(sha256("formulaguard-vepr-v1\0" + group_id)[:8], 16) mod 5`. Every version
and transition from one evolution group stays in the same fold. Formula text,
address, sheet name, version order, group identity, and transition identity are
not model features.

## 4. Frozen transitions, candidates, and labels

An example uses two consecutive author-ordered versions `(t, t+1)`. Version `t`
is the complete prediction input and `t+1` is label evidence only. A ranking
transition is eligible when all conditions hold:

1. both formula profiles are complete;
2. version `t` has between 10 and 5,000 formula cells;
3. at least one and at most 19 same-sheet, same-address formula text changes
   exist;
4. the frozen V0 flags `bulk_direct_rewrite` and `bulk_add_remove` are both
   false;
5. formula additions plus removals do not exceed 12;
6. at least five same-address formula cells are unchanged;
7. the complete evolution group survived Section 3.

Candidates are all formula keys shared by `t` and `t+1`. The label is
`next_direct_edit=1` exactly when the end-trimmed formula at that key differs in
`t+1`; otherwise it is zero. Additions and removals are reported but never
candidates or labels. Label construction occurs only after the current-formula
snapshot for `t` has been atomically completed and hashed.

An unchanged control is an adjacent pair with no formula-text change, addition,
or removal, whose current version has 10 through 5,000 formulas and whose group
survived overlap exclusion. At most one control per `(group_id, formula-layout
hash)` is retained, choosing the lowest version order. Controls never fit the
classifier. They calibrate and test workbook-level abstention only.

Single-edit transitions are deliberately eligible because VEPR ranks the edit
against all stable current formulas. This is a new all-formula prospective-edit
task; it is not a relaxation of VDEL's within-delta mixed-label task.

## 5. U0 availability and integrity gate

Two independent processes must produce byte-identical private manifests and
aggregate receipts. U0 passes only if, after complete-group overlap exclusion:

1. at least 300 ranking transitions span at least 50 evolution groups;
2. at least 600 positive formula rows and 30,000 stable candidate rows exist;
3. every fold contains at least 30 ranking transitions, six groups, 80 positive
   rows, and 3,000 stable candidate rows;
4. at least 200 unchanged controls span at least 80 groups, with every fold
   containing at least 20 controls from ten groups;
5. every public near duplicate is excluded by complete evolution group;
6. all source hashes, author order, candidate accounting, current-snapshot-before-
   label order, fold isolation, and two-process byte equality checks pass;
7. cached values, constants, cell text, email data, fault labels, expected
   outputs, public source cells, correct workbooks, V4 outcomes, and protected
   inputs are absent.

Failure stops VEPR before feature extraction or fitting. No threshold, edit
limit, group rule, fold, candidate definition, or sample minimum may be revised
on VEnron after U0.

## 6. Frozen current-snapshot representation

Only U0 passage authorizes feature extraction. Every feature is computed from
version `t` before `t+1` is opened for labels. The fixed feature vector contains:

1. FSPR's committed anchor-independent formula-syntax signed unigram/bigram
   hash in 2,048 dimensions, using syntax only and tokenizer
   `fspr-anchor-independent-v1`;
2. parser-supported status; logarithmic formula length; lexical token, AST
   depth, function, operator, reference, range, numeric-literal, string-literal,
   absolute-axis, and cross-sheet-reference counts;
3. exact anchor-relative formula-family frequencies in the worksheet, row,
   column, and radius-6 neighborhood, each divided by the corresponding formula
   population;
4. translated-peer agreement counts and ratios in the same row, same column,
   and four cardinal directions; modal-family support, runner-up support, and
   normalized support margin;
5. formula anomaly score and graph anomaly/review scores from the committed
   label-free implementations, together with their within-workbook percentile
   ranks;
6. formula-graph precedent count, dependent count, isolated status, sink status,
   and log-one-plus counts; no cached value or evaluated output is used;
7. workbook and worksheet log formula counts, parseable ratio, repeated-family
   coverage, formula-edge coverage, and local formula occupancy in the 5-by-5
   neighborhood.

Raw formulas are transient and never written to training rows. Numeric and
string literal values, sheet names, addresses, workbook names, source paths,
version order, group IDs, corpus IDs, and labels are not model fields. The
exact ordered numeric feature list, 2,048 hash weights, tokenizer/source hashes,
and missing-value policy must be recorded in each U1 model artifact.

For fitting, continuous structured features receive training-fold median
imputation and standardization plus a missing indicator. Binary features remain
unchanged. Sparse syntax features are already unit-normalized and are not
standardized.

## 7. Frozen learner, sampling, and ranking

The only learner is `sklearn.linear_model.LogisticRegression` with L2 penalty,
`C=1.0`, `solver="liblinear"`, `max_iter=2000`, `class_weight=None`, and
`random_state=260903`. There is no hyperparameter, architecture, feature,
threshold, corpus, or seed search.

Every positive in a training transition is retained. At most 64 stable formulas
per transition are retained by increasing SHA-256 of `(protocol, opaque
transition ID, opaque candidate ID)`. Training weights give each evolution group
equal total weight, each transition within a group equal weight, and the positive
and stable classes within a transition one half each. Full unsampled candidate
inventories are used for validation ranking.

Candidates are ranked by decreasing logit, decreasing formula anomaly,
decreasing graph-review score, then a stable opaque candidate hash. The last
three keys resolve exact model ties and do not enter the classifier. Every
eligible formula receives exactly one rank.

In each outer fold, fit on the other four complete-group folds. The abstention
threshold is the smallest training-control top logit at or above the empirical
95th percentile; a test workbook acts only when its top logit is at least that
threshold. Controls never affect weights or formula order.

## 8. U1 natural-evolution gate

The fixed baselines receive the same current snapshot and complete candidates:

- `opaque_hash`;
- committed formula-anomaly ranking;
- committed graph-review ranking;
- rare anchor-relative formula family first;
- syntax-only logistic regression using only the 2,048 hashed syntax features.

Primary metrics are evolution-group macro Top-5 and MRR for finding at least one
next direct edit. Top-1, Top-3, edit-block coverage, event-micro metrics, control
action rate, and feature coefficients are secondary. Use 10,000 evolution-group
bootstrap resamples with seed `20260903`.

U1 passes only if every condition holds:

1. full VEPR Top-5 exceeds the strongest nonlearned baseline by at least five
   percentage points and MRR does not decrease;
2. full VEPR Top-5 exceeds syntax-only logistic regression by at least three
   points and MRR does not decrease;
3. at least four of five folds have nonnegative Top-5 differences against both
   comparators;
4. the 95% group-bootstrap interval for the full-minus-strongest-nonlearned
   Top-5 difference has a lower bound above zero;
5. test-fold unchanged-control action rate is at most 10%, both overall and in
   every fold;
6. removing local/family features and removing graph features each reduce
   Top-5 by at least one point, establishing that the result is not formula-
   syntax memorization alone;
7. every group contributing at least 5% of ranking transitions can be removed
   without causing more than a five-point Top-5 regression against the strongest
   nonlearned baseline;
8. two independent runs reproduce folds, sampled IDs, feature hashes, weights,
   logits, complete rankings, thresholds, and aggregate metrics byte for byte;
9. every forbidden-input and overlap assertion remains satisfied.

Failure stops VEPR. It cannot be rescued by changing the task into VDEL, adding
future horizons, treating additions/removals as positives, tuning weights or
thresholds, adding V4 as a feature, or reading public fault labels.

## 9. Frozen public transfer gate

Only a U1 pass authorizes fitting one final model on all retained VEnron ranking
groups and calibrating its threshold on all retained VEnron controls. Source,
configuration, final model, environment, and two byte-identical predictions for
all 96 byte-unique public/Enron observed workbooks must be committed before any
public fault label or frozen V4 shard is read by the scorer.

The scorer then evaluates the already revealed 190 public error events and 30
paired controls. It must use the true frozen V4 ranking shards rather than
recomputing V4. VEPR passes only if:

1. structure-group macro Top-5 exceeds V4 by at least five percentage points and
   structure-group macro MRR does not decrease;
2. event Top-5 exceeds V4 by at least five points and event MRR does not decrease;
3. Enron Top-5 exceeds V4 by at least five points and Enron MRR does not decrease;
4. Historical 100, Integer, Modified EUSES, and Info1 each regress by no more
   than five Top-5 points, with Info1 descriptive because it has two events;
5. at least eight V4 Top-5 misses are rescued and no more than two V4 Top-5 hits
   are lost, across at least five structure groups;
6. the 95% structure-group bootstrap interval for the VEPR-minus-V4 Top-5
   difference has a lower bound above zero;
7. public paired-control workbook action rate is at most 15%;
8. syntax-only, no-local-family, and no-graph ablations are reported and full
   VEPR exceeds syntax-only on Enron Top-5 or MRR;
9. prediction isolation, complete rankings, input hashes, model hashes, frozen
   V4 hashes, overlap exclusions, and independent-process equality all verify.

Failure stops VEPR. Revealed public labels cannot select a second feature view,
threshold, weight, candidate filter, cohort exception, or fifth-slot adapter.

## 10. External confirmation and version boundary

A public-gate pass authorizes a separate committed intake/prediction/scoring
protocol for SpreadsheetBench 2 Debugging. Input workbooks must be materialized
before gold workbooks; predictions must be committed before gold access. The
external gate must preserve the five-cell review budget and require at least a
five-point Top-5 improvement over the frozen V4 baseline, nondecreasing MRR, at
most two V4 Top-5 losses, and no more than 15% action on valid controls. Exact
eligibility and source hashes must be frozen before download.

Only after that external gate passes may the locked candidate be run once on the
old protected trial. Before the final blind run, the custodian must regenerate a
fresh `240+120` package because the currently staged package lost one-time blind
eligibility in the recorded 2026-09-02 access incident. No currently staged
protected path may be inspected to prepare that regeneration.

The final blind gate must be committed before intake and require, on its stated
group-macro and event metrics, at least a five-point Top-5 improvement over
frozen V4, nondecreasing MRR, no cohort regression beyond five points, at most
two V4 Top-5 losses, paired-control action at most 15%, complete prediction-before-
label isolation, and independent result verification.

Only passage of U0, U1, the public gate, SpreadsheetBench 2, the old protected
trial, and the freshly regenerated final blind gate can authorize a version
file. That file may use `V5-R1` only if it exposes the same single-workbook input
and complete five-cell FormulaGuard ranking contract, records the exact model and
source hashes, and limits its claims to the populations actually validated.
