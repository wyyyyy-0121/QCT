# FormulaGuard VDEL version-delta edit-longevity preregistration

Date frozen: 2026-09-03

Protocol: `formulaguard_vdel_v1`

Research code: `VDEL` (Version-Delta Edit Longevity; not a formal version name)

Status: frozen before materializing one-step re-edit labels, overlap results,
features, fitted weights, or rankings

## 1. Question and scope

`V4-R1` remains the only formal main ranker. The failed VRER protocol prohibits
another learned head under the same single-workbook, no-oracle input contract.
VDEL therefore receives an actual prior workbook version as well as the current
version. It ranks the direct same-address formula edits in that version delta by
the risk that the edited formula will be edited again in the immediately next
author-ordered version.

The target is **one-step edit longevity**, not author intent or fault truth. A
re-edited formula can be an ordinary evolving calculation, and a stable formula
can still be wrong. VDEL must not be reported as a general error localizer or as
evidence that VEnron supplies confirmed bugs. Its maximum possible claim is a
version-review result under a richer two-workbook inference contract.

VDEL is not a revival of VHRL. VHRL ranked responsibility for explicit-error or
exact-reversion proxies inside multi-edit transitions and stopped at 29 positive
groups. VDEL reads no cached result, performs no rollback, does not require an
exact reversion, uses only the immediately next formula state as a longevity
label, and exposes the prior/current delta at prediction time.

## 2. Frozen source evidence

VDEL may read only the existing public VEnron formula-only profiles and frozen
transition inventory:

- `results/venron_profile_v0/profile_receipt.json`, SHA-256
  `54b24336912fa0ce4d50f55ef1897bef4e7ed40e1d7313a9a17fff6fcba924e0`;
- `results/venron_profile_v0/profile_index.json`, SHA-256
  `f337ad4448aec142bb529a90b514dc1f8fe8235aae29414b20750cd8ab7b0cc3`;
- `results/venron_gate_v0/gate_result.json`, SHA-256
  `4743f0a1fb929afc6d98f4ebbfa3ac9b74022fa272c98f84da2f95f8b91b723e`;
- `results/venron_gate_v0/transition_manifest.json`, SHA-256
  `8a8ff6e13fdebc44f28d4abb509357c9475c3badf00a679d8bbf33456cc9a5ee`.

Those artifacts account for 7,294 parsed workbook versions in 360 complete
evolution groups. They contain formula text, worksheet title, address, opaque
group identity, and author-supplied order. Constants, cached values, email
fields, sender/recipient data, and fault labels are absent and remain forbidden.

For overlap removal only, VDEL may open the 96 byte-unique observed workbooks
identified by `results/core_reset_b_phase0/scoring_groups.csv`, SHA-256
`6f5384990f8758258dba4c556bc1f119e498d850ab37c2d092ccaa82f6e88be7`.
It may retain only formula text, sheet title, address, workbook SHA-256, cohort,
and structure-cluster ID. Event labels, source cells, correct formulas, case
kinds, expected outputs, answer workbooks, and V4 outcomes are forbidden.

No path under either protected `240+120` package may be listed, searched,
hashed, opened, copied, matched, or otherwise accessed. SpreadsheetBench 2 is
not an input and remains unreceived.

## 3. Frozen overlap exclusion

Overlap is evaluated before a longevity row can enter U0. Formula strings are
trimmed only at their ends. For every workbook, construct these sets:

1. exact entries `(sheet title, A1 address, formula)`;
2. keyed formulas `(sheet title, A1 address) -> formula`;
3. formula-coordinate keys `(sheet title, A1 address)`.

A VEnron version is a near duplicate of a public observed workbook when both
have at least 20 formulas and either condition holds:

1. exact-entry intersection divided by the smaller formula count is at least
   `0.80`; or
2. coordinate-key intersection divided by the smaller key count is at least
   `0.90`, and at least `0.80` of intersecting keys have identical formulas.

Every VEnron evolution group containing one near-duplicate version is excluded
in full. The output records only group counts, cohort counts, threshold values,
and stable hashes of opaque excluded-group IDs. It must not export public paths,
raw formulas, or a cross-corpus match table. Thresholds cannot be changed after
the first complete overlap run.

## 4. Frozen prediction windows and labels

A window is three consecutive integer orders `(t-1, t, t+1)` in one retained
evolution group. The prediction delta is `(t-1) -> t`; version `t+1` is scoring
evidence only.

The delta is eligible when:

1. all three formula profiles are complete;
2. versions `t-1` and `t` have identical worksheet-title sets;
3. exactly 2 through 12 keys contain formulas at the same sheet/address in both
   versions and have different end-trimmed formula strings;
4. the delta is neither a frozen V0 bulk-direct rewrite nor a bulk add/remove
   transition;
5. formula additions plus removals between `t-1` and `t` do not exceed 12;
6. at least two direct-edit keys remain formulas at the same address in `t+1`.

For each retained direct-edit key, the label is `re_edited=1` when its formula
in `t+1` differs from the formula in `t`, `re_edited=0` when it is unchanged,
and unavailable when the key is no longer a formula. A ranking window must
contain at least one available positive and one available negative.

A no-re-edit control satisfies the same delta rules but every available direct
edit is unchanged in `t+1`. Controls measure score calibration only and never
become negative formulas inside a positive ranking window. Windows from the
same evolution group never cross a fold.

## 5. U0 availability and integrity gate

Assign an evolution group to fold
`int(sha256("formulaguard-vdel-v1\0" + group_id)[:8], 16) mod 5`. Two
independent processes must generate byte-identical aggregate receipts and
private row manifests. U0 passes only if every condition holds after full-group
overlap exclusion:

1. at least 120 ranking windows span at least 40 evolution groups;
2. ranking windows contain at least 240 available direct-edit candidates, at
   least 120 re-edited candidates, and at least 120 stable candidates;
3. each of the five folds contains at least 15 ranking windows from at least
   eight groups;
4. at least 30 no-re-edit controls span at least 15 groups;
5. every public near duplicate is excluded by complete evolution group, and no
   excluded group contributes any row;
6. input hashes, group order, candidate accounting, fold isolation, and
   two-process byte equality all verify;
7. cached values, constants, email data, fault labels, public source cells,
   answer/golden workbooks, V4 outcomes, and protected inputs are absent.

Failure stops VDEL before feature extraction or fitting. The horizon, edit
limits, addition/removal bound, overlap rules, mixed-label requirement, folds,
and thresholds may not be relaxed on this corpus.

## 6. Frozen U1 representation

Only a U0 pass authorizes U1. Features are computed from `t-1` and `t`; no
feature reads `t+1`, a later version, cached values, constants, cell text,
filenames, email data, group identity, or labels.

Each direct edit receives these fixed numeric or binary features:

1. formula token counts before and current: length, functions, operators,
   references, ranges, numeric literals, string literals, absolute row/column
   axes, cross-sheet references, and parser-supported status;
2. signed current-minus-before differences for every count above, plus exact
   token edit distance divided by the larger token count;
3. relative-reference displacement counts: inserted, deleted, row-changed,
   column-changed, absolute-axis-changed, sheet-relation-changed, and range-
   shape-changed;
4. before/current formula-family support in the same row, same column, radius-6
   neighborhood, and whole worksheet, plus signed support changes;
5. before/current nearest translated-peer agreement in each cardinal direction,
   plus agreement changes and missing-peer indicators;
6. before/current formula occupancy in the 5-by-5 neighborhood, direct-edit
   count, formula addition/removal count, and current workbook formula-count
   logarithm.

Formula-family equality is exact equality after anchor-relative A1 references
are represented as signed row/column offsets while preserving absolute axes,
range shape, functions, operators, and literal categories. Raw formula text,
raw numeric/string literals, cell coordinates, sheet names, workbook names,
and identities are not model fields. Unsupported formulas retain lexical token
counts and an unsupported indicator rather than being dropped.

Continuous fields receive training-fold median imputation, standardization, and
a missing indicator. Binary fields remain unchanged. The exact ordered feature
list and parser/tokenizer hashes must appear in the U1 receipt.

## 7. Frozen learner and ranking

The only learned model is balanced logistic regression with L2 regularization,
`C=1.0`, `liblinear`, maximum 2,000 iterations, and seed `260903`. There is no
hyperparameter, feature, threshold, cohort, or fold search.

Every training ranking window has equal total weight; its positive candidates
share one half and its stable candidates share one half. No-re-edit controls do
not fit the classifier. For each outer fold, train on the other four complete
group folds and rank candidates in the held-out fold by decreasing model logit,
then decreasing current inconsistency, decreasing normalized edit distance, and
the stable SHA-256 of the opaque candidate identity. The ties do not enter the
model.

The model emits a ranking of direct edits, not workbook edits. It never changes
a formula automatically.

## 8. Frozen baselines, metrics, and U1 gate

Every baseline receives the same prior/current versions and direct-edit
candidate set:

- `coordinate_hash`: stable opaque-candidate hash only;
- `edit_distance`: decreasing normalized token edit distance;
- `current_inconsistency`: increasing lack of current translated-family support;
- `support_drop`: decreasing before-to-current translated-family support;
- `v4_restricted`: current V4 ranking filtered to the direct-edit candidates,
  reported as an added-information comparison and never used as a feature.

Primary metrics are evolution-group macro Top-1 and MRR. Top-3, Top-5, candidate
count, no-re-edit control score distribution, and full-current-workbook V4 rank
are secondary. Use 10,000 evolution-group bootstrap resamples with seed
`20260903`.

U1 passes only if every condition holds:

1. VDEL Top-1 exceeds the strongest non-V4 baseline by at least 5 percentage
   points and MRR does not decrease;
2. VDEL Top-1 exceeds `v4_restricted` by at least 5 points and MRR does not
   decrease;
3. at least four of five folds have nonnegative Top-1 differences versus both
   comparators;
4. the 95% group-bootstrap interval for VDEL minus the strongest non-V4
   baseline Top-1 has a lower bound above zero;
5. leave-one-high-volume-group-out results for every group contributing at
   least 5% of windows do not regress more than 5 Top-1 points versus the
   strongest non-V4 baseline;
6. two independent runs reproduce candidate IDs, folds, features, weights,
   logits, rankings, and aggregate metrics byte for byte;
7. all forbidden-input and overlap-exclusion assertions remain satisfied.

Failure stops VDEL. It does not authorize a single-workbook adapter, a fifth-
slot rule, a longer future horizon, post-hoc thresholds, or access to protected
data.

## 9. External evidence and version boundary

A U1 pass is development evidence on one public corpus only. It authorizes a
separate, committed acquisition and evaluation protocol for a newly obtained
version-history source with at least 80 mixed-label ranking windows across at
least 20 independent workbook lineages from at least five unrelated projects.
The external source must be license-audited, group-disjoint from VEnron and all
FormulaGuard development inputs, and unopened until the model, source,
environment, and complete external prediction procedure are locked.

Only a full external pass under gates at least as strict as U1 may authorize a
scoped version artifact. Such an artifact must say `version-delta edit-
longevity ranker`, require prior and current workbooks, and explicitly disclaim
general error localization. It cannot use the reserved name `V5-R1`.

The existing protected `240+120` packages do not provide the required prior-
version input or future longevity outcome and are outside VDEL's task contract.
VDEL never authorizes their access. No development improvement, including a
large one over V4, substitutes for the required fresh external validation.
