# FormulaGuard PCRC peer-conditioned repair compatibility preregistration

Date: 2026-09-02
Protocol: `formulaguard_pcrc_v1`
Research code: `PCRC` (Peer-Conditioned Repair Compatibility)
Status: frozen before PCRC corpus construction, training, or prediction
Formal version authorized: no

## 1. Research question

The frozen V4 ranker has substantial repair-candidate headroom, but static peer scores,
linear residual controllers, repair closure, downstream responsibility, EORL, and an
earlier neural semantic-compatibility experiment have not converted that headroom into
a safe cross-structure ranking improvement. PCRC tests one narrower mechanism:

> Can a small model trained only on correct input-only workbooks learn whether an
> executable peer-derived formula is more compatible with a target's masked structural
> context than the observed formula, and can that margin safely promote true source
> formulas above a frozen V4 ordering?

PCRC is not `V5-R1`. It becomes eligible for a locked external test only if every
public development gate below passes without post-result revision.

## 2. Prior overlap and allowed claim

None of the following is a PCRC invention: formula ASTs, relative references, local
formula peers, formula repair candidates, neural formula encoders, contrastive or
candidate-ranking losses, masked formula prediction, selective prediction, V4, or
repair-based spreadsheet debugging. Relevant prior and project lines include ExceLint,
CUSTODES/WARDER, SpreadsheetCoder, ForTaP/HermEs, FLAME, LaMirage, DRFV, FCRL, and the
August 31 semantic-compatibility experiment.

The earlier semantic model used a frozen ForTaP context vector and unconstrained nearby
formula-role alternatives. Its calibration candidate accuracy was 48.58% versus the
registered 55% gate; its selective internal-test accuracy was 66.93% versus 70%; and
its already revealed public repair-margin Top-5 was 31.05% versus V4's 57.89%. These
results cannot be reset or hidden.

PCRC differs only in the following falsifiable mechanism:

1. training and inference use the same executable, at-most-four peer repair generator;
2. the context encoder is trained directly on target-masked structural tokens rather
   than receiving a frozen general table embedding;
3. the score is the compatibility difference between a proposed repair and the
   observed formula, followed by a clean-calibrated V4-stable promotion rule;
4. candidate support is reported as explanation, but does not itself decide the rank.

The maximum allowed novelty statement, if every gate passes, is that a
peer-conditioned compatibility margin can turn self-supervised formula replacement
into a safe residual source-ranking signal. Architecture or component novelty is not
claimed. Failure of any required ablation makes that statement unavailable.

## 3. Evidence already observed before this lock

The following feasibility facts are disclosed rather than treated as prospective
results:

- SpreadsheetBench v1 input-only retains 607 byte-unique workbooks, 219 structure
  groups, and 74,570 parseable formulas after known-overlap removal.
- A deterministic 200-target audit found 23,605 masked targets: 16,369 train, 3,737
  calibration, and 3,499 internal-test targets across 153/33/33 structure groups.
- It found at least one distinct peer candidate for 11,397 train, 2,051 calibration,
  and 2,303 internal-test targets, with 27,349/4,229/5,745 candidates respectively.
- A post-result read-only diagnosis on the already revealed 60 public errors found a
  source peer hypothesis in 42/60 events and a correct-role hypothesis in 38/60. A
  two-peer support restriction retained a correct-role hypothesis in 32/60, while
  clean controls also frequently produced alternatives. These counts justify learning
  a compatibility difference; they are not localization accuracy and will not select
  a threshold or model.

The failed semantic receipts remain fixed at:

- `results/semantic_compatibility_training_v2/receipt.json`, SHA-256
  `e46b7fef2c6b61a9fb290725f22b27a722ab147bf3320fcb300689643bb85e`;
- `results/semantic_compatibility_selective_v1/receipt.json`, SHA-256
  `fbfd0123dee7a76644311d270564ce7715be3cafaa20735a87f9dc5644192d8c`;
- `results/semantic_public_localization_v2/receipt.json`, SHA-256
  `ed0a4a0c3bc6aeaeef80ce5f0b2cf57e120422959c23487ed9320138d52d2a5e`.

## 4. Data boundary and splits

### 4.1 Self-supervised corpus

Only the already materialized SpreadsheetBench v1 `*_input.xlsx` corpus may train or
calibrate PCRC. The immutable source identities are:

- `results/drfv_corpus_v1/corpus_manifest.json`, SHA-256
  `0e1228992fccf6b13961e397b944133db83dcde72b5372af5c36cd54306e71ed`;
- `results/drfv_corpus_v1/corpus_receipt.json`, SHA-256
  `743461a31faf9734d38cbcb43dbf2a23cc1cf30076b8d83ffe22d3d7d6d5e789`;
- `results/drfv_spreadsheetbench_v1_intake/input_manifest.json`, SHA-256
  `bb01edd4a58f80a7f26f6b3051f3bdbc6983b2a5a47a23d185bcd07cf2a4f42d`.

The existing 153/33/33 structure-group train/calibration/internal-test split is
immutable. Answer workbooks, instructions, answer positions, fault labels, V4 ranks,
output truth, raw text, and protected data are forbidden inputs. SheetJS/Enron CWRP
data is excluded because it would contaminate the Enron transfer interpretation.

### 4.2 Revealed public transfer

Only after the self-supervised gate passes may the frozen model run once on the current
190 revealed public errors and 30 paired controls. These labels are already development
evidence, not independent validation. No coefficient, threshold, token, candidate rule,
or checkpoint may change after this run.

### 4.3 Locked external and protected data

SpreadsheetBench v2 Debugging remains unopened external evidence. It may be received
only after the complete PCRC model, weight, environment, threshold, and public
predictions are committed. Its gold files remain inaccessible until input predictions
are locked.

The user-designated protected directory
`/home/ayaka/code/FormulaGuard_240_120/` must not be listed, searched, hashed, or read
before all public and external gates pass and a final candidate lock is committed. The
historical nonconfidential 240+120 trial is not a training source for PCRC.

## 5. Frozen target and candidate construction

Each retained workbook contributes at most 200 visible parseable targets, selected by
the existing stable hash of opaque workbook ID, sheet ordinal, row, and column.

For each target, the existing `SignalAuditConfig` is fixed to axis radius 12, local
radius 6, at most 16 row/column peers, 24 local peers, 16 role peers, and four repair
hypotheses. A hypothesis must be an executable translated peer formula, differ from the
observed normalized formula, and preserve the target's parser-supported formula shape.
Candidates are ordered by vote count, independent axes, independent cells, and
normalized formula. No source label or reference workbook enters generation.

The clean observed formula is the only positive. All distinct generated hypotheses are
hard negatives. Targets without a distinct candidate remain in the inventory but do
not enter the candidate loss. Candidate support count, axes, and cells are retained in
the audit record and explanation but are excluded from neural input.

## 6. Frozen token schema and leakage barrier

The context sequence must be reconstructible without reading the target formula or its
cached value. It contains, in this order:

1. five-bin row/column position, number-format class, row/column formula-density bins,
   and a 5x5 `outside/blank/constant/formula` topology with the center marked `MASK`;
2. up to four nearest visible formulas in each of up/down/left/right, ordered by
   direction, distance, and address; each peer carries a distance bucket and its own
   canonical formula tokens;
3. up to eight nearest visible dependent formulas that reference the target, with
   distance and cross-sheet buckets; no target-derived precedent edge is allowed;
4. boundary tokens identifying every context segment.

The formula encoder receives exactly one candidate at a time. Formula tokens retain
functions, operators, AST delimiters, SELF/OTHER sheet relation, relative/absolute row
and column references, signed reference offsets, and bounded numeric categories.
Numeric categories are `ZERO`, `ONE`, `NEG_ONE`, `FRACTION`, `INTEGER_2_9`,
`INTEGER_10_99`, `INTEGER_100_PLUS`, and their negative equivalents. Raw numeric
literals, string contents, sheet names, workbook names, and cell text are forbidden.

The target formula token IDs, candidate token IDs, candidate count, repair support, and
V4 rank must not enter the context encoder. A regression test must prove that changing
only the target formula and cached value leaves context token IDs byte-identical.

## 7. Frozen model and limited calibration

PCRC is a small dual encoder, not a large language model:

- separate context and formula token embeddings, dimension 128;
- one bidirectional GRU per encoder, hidden size 192 per direction;
- normalized 256-dimensional projections;
- cosine compatibility divided by fixed temperature 0.10;
- maximum context/formula lengths 384/96;
- candidate cross-entropy over one clean positive and one-to-four hard negatives;
- batch 128, AdamW, weight decay `1e-4`, gradient clip 1.0, at most 30 epochs,
  patience 4, deterministic seed `260902`, FP32 training on CUDA.

Only the learning rate may be calibrated, from the finite set
`{1e-3, 3e-4, 1e-4}`. One run per rate is allowed. Selection uses calibration
structure-group macro candidate accuracy, then event accuracy, then cross-entropy, then
the smaller learning rate. Internal test remains unopened until one rate and checkpoint
are locked. No second seed, architecture search, token revision, or test-driven retry is
allowed.

For a target with observed compatibility `c0` and repair compatibilities `c1..cm`, the
PCRC margin is `max(c1..cm) - c0`; without a repair candidate it is negative infinity.
The proposed repair is the highest-compatibility candidate, with frozen candidate order
as the final tie-break.

Calibration selects one promotion threshold from the observed clean-margin values. The
allowed thresholds are positive empirical quantiles `{0.90, 0.95, 0.975, 0.99}` plus
infinite abstention. Select the lowest quantile whose workbook-level clean action rate
is at most 10%; ties use the higher threshold. This selection does not read fault
labels. At inference, cells above threshold are placed first by descending margin;
all remaining cells retain exact V4 order. This produces a complete five-cell review
ranking while making every deviation explicit and auditable.

## 8. Self-supervised gate S1

The independently opened 33-group internal test must satisfy every condition:

1. at least 2,000 eligible hard-negative targets across at least 25 groups;
2. candidate top-1 accuracy at least 60% and at least 5pp above both train-frequency
   and nearest-peer baselines;
3. structure-group macro accuracy at least 55%, with a 10,000-sample group-bootstrap
   95% lower bound above the stronger baseline;
4. unseen-role accuracy at least 45%;
5. clean target preference error at the locked threshold at most 10% and clean
   workbook action rate at most 15%;
6. two independent prediction processes produce byte-identical target IDs, scores,
   selected checkpoint, threshold, and aggregate metrics.

Failure stops PCRC before public transfer. The test cannot be re-split or reused for a
revision.

## 9. Required ablations and public gate S2

The frozen public run must include V4 and the following PCRC ablations:

- `context_frequency`: most frequent clean-train role among candidates;
- `local_peer`: existing peer defect ranking and candidate order without neural scores;
- `formula_only`: zero context vector with the same formula encoder;
- `observed_only`: rank by negative observed compatibility, without repair margin;
- `no_promotion`: V4 unchanged, proving gains come from thresholded margins.

S2 passes only if every condition holds on the 190 errors and 30 paired controls:

1. structure-group macro Source Top-5 improves over V4 by at least 5pp;
2. Enron structure-group macro Top-5 improves over V4 by at least 5pp;
3. Historical, Integer, and Modified EUSES each regress by no more than 5pp;
4. structure-group macro MRR improves, with no cohort MRR regression greater than 0.02;
5. the 10,000-sample paired structure-group bootstrap 95% lower bound for PCRC minus
   V4 Top-5 is above zero;
6. paired-control workbook action rate is at most 15%, and V4-hit loss rate is at most
   2%;
7. full PCRC exceeds every ablation in overall Top-5, and exceeds `formula_only` and
   `observed_only` by at least 3pp.

Info1 remains descriptive because it has two errors. Candidate coverage, repair exact
role, Top-1, Top-3, review churn, and explanations are mandatory reports but cannot
rescue a failed gate.

## 10. External promotion and stopping rule

S1 and S2 passage only authorizes a committed external-input prediction lock. The
external protocol must be separately materialized before SpreadsheetBench v2 inputs
are downloaded and must retain task/group coverage, V4/local-peer comparisons,
precision@5, hit@5, MRR, control, overlap, and gold-isolation requirements at least as
strict as the frozen DRFV U2 protocol.

Any S1, S2, or external failure permanently stops PCRC v1. Results, checkpoints,
predictions, and failure causes remain. Thresholds, learning rates, candidate rules,
features, gates, and dataset roles may not be relaxed. A failed result cannot be
renamed as `V5-R1`, and protected data remains inaccessible.
