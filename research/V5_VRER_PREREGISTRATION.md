# FormulaGuard VRER verified-revision supervision preregistration

Date: 2026-09-01  
Protocol: `formulaguard_vrer_v1`  
Research code: `VRER` (Verified Revision Evidence Ranker)  
Status: frozen before acquiring or opening any new revision workbook

## 1. Research question and status boundary

`V4-R1` remains the only frozen main ranker. AETR learned a strong ranking signal on
N2 constructed errors (`+26.81pp` structure-group macro Top-5) but regressed on the
natural Enron cohort (`-10.67pp`, and `-14.67pp` when Enron was left out of training).
Its failure is evidence of mechanism shift, not permission to add an Enron switch,
blend AETR with V4, or tune another head on the same revealed labels.

VRER asks a different question: can author-verified public formula corrections teach
a complete ranker which observable, peer-supported edits resemble real corrections,
and does that signal transfer to workbooks and repositories absent from training?

VRER is a new research route, not a continuation or relabeling of VHRL. VHRL used
rollback and exact-reversion proxies without author-intent ground truth. Those proxies
are forbidden VRER positives. `VRER` is not a formal version name. It may become a
`V5-R1` candidate only after every public gate and the later protected one-shot gate.

## 2. Contribution hypothesis and prior-work boundary

Learning to rank, ridge regression, formula differencing, AST edit features, peer
formula comparison, grouped cross-validation, and repair candidate generation are
prior techniques and cannot be claimed as FormulaGuard inventions.

The falsifiable contribution hypothesis is narrower:

> A formula's defect evidence can be estimated by jointly representing (a) the
> label-free support for its best peer-derived replacement and (b) the structural edit
> required to reach that replacement, with edit reliability learned only from public
> author-verified corrections. This correction-conditioned evidence should transfer
> better to natural errors than anomaly evidence learned mainly from injected faults.

The required disproof is an atomic-evidence-only learner trained on exactly the same
verified revisions and folds. If the edit representation does not add held-out
repository and Enron value, VRER has no supported methodological contribution even if
one aggregate score is high.

## 3. Protected and revealed-data boundary

The directory `/home/ayaka/code/FormulaGuard_240_120/` must not be listed, hashed,
opened, searched, copied, or overlap-checked during VRER acquisition, development, or
public evaluation. Existing public-revision material under that protected project is
also forbidden. Public sources must be independently downloaded from their canonical
upstream locations after this protocol is committed.

The Enron Error Corpus, Info1, Historical 100, Integer corpus, Modified EUSES, old
revealed trial, SpreadsheetBench 2, and all previous FormulaGuard results are revealed
evaluation evidence. Their labels, source addresses, filenames, corpus identity, V4
scores, and outcomes cannot enter VRER acquisition, feature construction, fitting,
hyperparameter selection, or candidate choice. Enron is a retrospective transfer
safety test, not fresh confirmation evidence.

## 4. What qualifies as a verified correction

The acquisition ledger must retain every discovered candidate, including rejected
ones. An accepted correction episode must satisfy all of the following:

1. The workbook is available from a public, canonical, immutable Git revision or a
   peer-reviewed public artifact with an explicit redistribution or research-use
   license. Repository-level source code licensing is not silently assumed to cover a
   workbook when the repository says otherwise.
2. A public author or maintainer statement in the fixing commit, linked issue, pull
   request, release note, or artifact annotation explicitly identifies a bug, error,
   incorrect formula/calculation, or correction. The exact evidence URL and quoted
   text are recorded. Filename evolution, timestamps, later edits, or exact reversion
   alone do not qualify.
3. Before and after artifacts are pinned by immutable source revision and SHA-256.
   The same workbook path, worksheet, and cell contain parseable formulas on both
   sides, and their end-trimmed formula strings differ.
4. A source statement naming an exact cell is accepted directly. A workbook-level
   correction statement is accepted only when the workbook has at most 12 direct
   same-cell formula changes and no sheet insertion/deletion, sheet rename, formula
   block movement, or mass addition/removal that makes cell correspondence ambiguous.
5. Formula changes contradicted by the public statement, generated timestamps,
   external-link refreshes, locale rewrites, formatting-only edits, cached-value-only
   changes, and exact rollbacks without an explicit correction statement are rejected.

The unit `correction_episode` is one before/after workbook transition supported by one
public correction statement. Multiple changed cells in one episode are not counted as
independent episodes. The unit `revision_group` joins the full repository, workbook
lineage, forks, renamed copies, and near-identical structural templates. No revision
group may cross a model fold.

Ordinary-edit controls must come from public revisions of an accepted source
repository that lack correction language and pass the same workbook alignment and
parseability rules. They are controls, not verified clean workbooks.

## 5. R0 acquisition and corpus gate

Before any feature fitting, acquisition writes an immutable candidate ledger, accepted
manifest, rejection manifest, license receipt, source hashes, workbook-pair hashes,
formula-diff receipt, structural-group assignment, and a second-process reproducibility
receipt. Acceptance rules cannot change after the first complete R0 run.

All of these minimums must hold:

1. at least 60 correction episodes and 80 corrected formula cells;
2. at least 40 independent `revision_group` values from at least 10 unrelated public
   repositories or artifact projects;
3. at least 30 ordinary-edit control episodes from at least 5 of those repositories;
4. no repository contributes more than 25% of accepted revision groups;
5. at least 90% of accepted corrected cells are parseable by the frozen FormulaGuard
   formula parser;
6. a stable 20% hash sample produces identical formulas, diffs, source-evidence hashes,
   and structural-group IDs in an independent process;
7. zero inputs originate from FormulaGuard protected data, Enron-derived repositories,
   Enron Error Corpus files, VEnron, or any revealed FormulaGuard label manifest.

Failure stops VRER before model implementation. Counts may be exceeded but thresholds,
acceptance rules, sources already rejected, and group identities cannot be relaxed or
manually rearranged after R0.

## 6. R1 label-free repair recoverability gate

For each accepted before-workbook, run the frozen model-discovery atomic signal
extractor without the after-workbook or correction labels. Each formula has at most
four peer-derived repair hypotheses in the extractor's deterministic order.

Only after every before-workbook audit is atomically complete may the scorer compare
hypotheses with the after formula. Report exact formula match and normalized relative-
reference AST match separately. R1 passes only if:

1. an exact after formula appears among the four hypotheses for at least 40% of
   corrected cells and at least 30% of revision groups;
2. an exact or normalized AST match appears for at least 55% of corrected cells and at
   least 40% of revision groups;
3. at least 8 source repositories have one recoverable revision group;
4. renaming worksheets, translating the full workbook, stripping formatting, and
   changing cached values leave hypothesis identities and edit features invariant
   after coordinate normalization;
5. controls, future formulas, source statements, and labels are absent from extractor
   inputs and receipts.

Failure means the proposed correction-conditioned input is unavailable often enough
to be a main ranker. It stops VRER; it does not authorize adding repair generators
after labels are visible.

## 7. Frozen representation

For every formula in a before-workbook, the model input contains no raw formula text,
cell address, workbook/repository identity, filename, cohort, group, label, future
formula, V4 value, or cached cell value. It contains three explicitly separated views:

1. `evidence`: independent peer count, alternative support, second support, support
   margin, disagreement, competition, role outlier, formula-family size, region size,
   parseability, and unsupported/evidence-state indicators;
2. `edit`: deterministic AST differences between the observed formula and its first
   label-free repair hypothesis: operator/function/reference/literal insertions,
   deletions and replacements; relative-reference displacement; absolute/mixed
   reference changes; range shape changes; aggregation-boundary changes; and exact
   translated-family agreement;
3. `context`: workbook formula-count and region/family ratios needed to calibrate
   evidence support. Dependency impact, descendants, sinks, and propagation reach are
   excluded from the defect score and may be reported only after ranking.

A formula without a repair hypothesis receives a fixed all-missing edit vector and a
`no_hypothesis=1` indicator. Missing continuous values receive training-fold medians,
then training-fold standardization and missing indicators. The exact ordered feature
list and extractor/configuration hashes must be written to every result receipt.

## 8. Frozen learner, tuning, and ranking

The learner is a complete formula-level linear ridge ranker with an intercept. Targets
are `1` for corrected cells and `0` for every other parseable formula in the same
before-workbook. Ordinary-edit controls contribute only zero targets. Each outer
training revision group receives equal total weight; within an episode, positive and
negative formulas each receive half of its weight. Control episodes receive the median
total episode weight.

The only tunable value is ridge `lambda` in the fixed set `{0.1, 1.0, 10.0}`. It is
selected inside each outer training partition by grouped inner cross-validation on
structure-group macro MRR, breaking ties toward `1.0`, then `10.0`, then `0.1`. No
feature selection, interaction search, nonlinear learner, class-weight search,
threshold, cohort gate, V4 fusion, or Top-k search is allowed.

Formulas are ranked by fitted defect score, then alternative support, independent peer
count, lower competition, and original parser inventory order. The latter fields only
break exact score ties. All formulas receive a rank. Impact evidence cannot change the
Top-5 ranking.

## 9. Development folds and required baselines

Five stable outer folds are assigned at complete repository lineage level, while
balancing only frozen pre-label group counts. No repository, fork, workbook lineage,
or near-duplicate structure crosses a fold. Each episode receives one out-of-fold
ranking. In addition, every repository with at least five revision groups receives a
leave-one-repository-out result.

The following use identical folds, labels, weighting, and lambda selection:

- `full`: evidence + edit + context, the registered VRER model;
- `atomic_only`: evidence + context, the direct disproof baseline;
- `edit_only`: edit + context;
- `no_context`: evidence + edit;
- `formula_micro`: full features with formula-row weighting.

V4-R1, the frozen atomic Combined/Peer/Role/Impact lists, and AETR are evaluated only
after VRER out-of-fold predictions are complete. V4 never becomes a VRER input. AETR
must be refit on the same verified-revision training folds rather than reusing its N2
weights.

## 10. R2 verified-revision gates

Primary metrics are revision-group macro Top-5 and MRR with 10,000 group bootstrap
resamples using seed `20260901`. `full` must satisfy every condition:

1. Top-5 exceeds `atomic_only` by at least 5 percentage points and MRR does not fall;
2. Top-5 exceeds same-fold V4-R1 by at least 5 points and MRR does not fall;
3. at least four of five outer folds have nonnegative Top-5 difference versus both
   `atomic_only` and V4;
4. the 95% bootstrap interval for `full - atomic_only` Top-5 has a lower bound above 0;
5. no eligible leave-one-repository-out cohort regresses more than 5 points versus
   `atomic_only`, and at least two improve by 5 points;
6. exact-candidate-recoverable and nonrecoverable correction groups are both reported;
   neither may be silently removed from the main result.

Failure terminates VRER. Results cannot be rescued with repository classifiers,
source-specific weights, altered evidence rules, or Enron-informed changes.

## 11. R3 revealed public transfer gates

Only an R2-passing implementation may be frozen and run once on the existing public
FormulaGuard evaluation cohorts. The same model and rank rule are used everywhere.
It must simultaneously satisfy:

1. Enron structure-group macro Top-5 improves over V4 by at least 5 points and MRR is
   not lower;
2. leave-Enron-out is intrinsic because Enron is forbidden training data; its Top-5
   and MRR must meet the same condition;
3. overall public Top-5 improves by at least 5 points and MRR is not lower;
4. Enron, Historical 100, Integer corpus, and Modified EUSES individually regress by
   no more than 5 points;
5. at least four of five frozen structure folds have nonnegative overall Top-5 change;
6. the overall group-bootstrap Top-5 interval lower bound is above 0;
7. `full` exceeds `atomic_only` on Enron Top-5 and MRR, establishing value beyond a
   new natural training set alone.

Info1 remains descriptive because it has only two natural events. Existing public
labels cannot be used to revise VRER after this run. Any failed gate terminates the
candidate and leaves V4-R1 as the main ranker.

## 12. Candidate freeze and protected one-shot decision

If R0-R3 pass, commit source, environment lock, exact feature order, selected model,
all public predictions, ablations, hashes, and a protected-evaluation protocol before
accessing the protected directory. The later protocol must fix at least structural-
group macro Top-5/MRR versus V4, per-producer or per-source noninferiority, clean-control
behavior, parsing coverage, and reproducibility gates without inspecting the package.

Only then may the user's standing authorization be used for one protected `240+120`
run. A protected failure cannot be tuned away. Passing all registered protected gates
is necessary, but not by itself sufficient, for the paper to claim broad natural-error
superiority: the paper must still distinguish verified public revisions, retrospective
Enron evidence, constructed N2 errors, and the protected package's actual provenance.

## 13. Stop decision after VRER

If R0 or R1 fails, FormulaGuard lacks adequate correction supervision or hypothesis
coverage. If R2 or R3 fails, the correction-conditioned mechanism does not transfer.
In either case, stop replacing linear/nonlinear heads under the current single-
workbook no-oracle input contract. The next admissible project is a newly named input
contract using an actual prior workbook version, a user-selected output, a pass/fail
observation, or a domain constraint. It cannot be presented as a patched V5 ranker.
