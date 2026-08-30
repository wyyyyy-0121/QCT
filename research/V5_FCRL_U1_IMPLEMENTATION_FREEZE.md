# FormulaGuard FCRL U1 implementation freeze

Date: 2026-08-31
Protocol: `formulaguard_fcrl_u1_v1`
Status: frozen before constructing any real FCRL training or evaluation example
Parent: `formulaguard_fcrl_preregistration_v1`

## 1. Purpose and metric clarification

U1 tests whether the frozen ForTaP encoder contains enough information for its
published formula-prediction decoder contract.  Official ForTaP does not emit full
Excel formula text: it emits prefix tokens, replaces cell references with range
pointers, and collapses literal values to `C-NUM`, `C-STR`, or `C-BOOL`.  Therefore
the preregistered phrase `exact normalized-formula accuracy` is implemented as exact
match of the **ForTaP-normalized formula-prefix key**:

- operators/functions are uppercase published vocabulary tokens;
- cell references have no `$` marker and use concrete A1 coordinates;
- range endpoints remain `start : end`;
- literals use the official typed placeholder;
- `<START>`, `<END>`, padding, whitespace, and target formula text are not part of
  the key.

This is stricter than sketch-only accuracy because every reachable cell pointer must
match, but it is not full Excel formula-text equality and must never be described as
such in the paper.  The registered 50% Top-5, 25% Top-1, baseline-gain, reachability,
and repeat-hash thresholds are unchanged.

The frozen QCT parser subset currently admits numeric literals and maps them to
`C-NUM`.  Formulas containing string or Boolean literal nodes are rejected by the
adapter; `C-STR` and `C-BOOL` describe the official ForTaP contract, not added parser
coverage in this experiment.

## 2. Bound source and retained workbooks

The only source is the existing SpreadsheetBench v1 input-only intake and DRFV
corpus audit:

- archive SHA-256:
  `9cf7228b54f1edcdd4b372eb736774adf29cb4f804c9920229bac6c154833399`;
- input manifest SHA-256:
  `bb01edd4a58f80a7f26f6b3051f3bdbc6983b2a5a47a23d185bcd07cf2a4f42d`;
- DRFV corpus manifest SHA-256:
  `0e1228992fccf6b13961e397b944133db83dcde72b5372af5c36cd54306e71ed`;
- DRFV corpus inventory SHA-256:
  `55839e8a8f24752ea90d99213927f3fd1a2a45c1ab575edadb5ecfd2fa17cc93`;
- retained byte representatives: 607 in 219 structure groups.

Only rows with `status=eligible`, `byte_representative=true`, and
`excluded_known_overlap_component=false` are accepted.  Every XLSX byte hash is
rechecked.  Answer workbooks, task JSON values, instructions, answer positions,
SpreadsheetBench 2, FormulaGuard labels, V4 outputs, Enron fine-tuned weights, and
protected data remain forbidden.

## 3. Immutable split and target selection

The existing sorted-group split is reused byte for byte: 153/33/33 structure groups
for train/calibration/internal-test.  No group or byte-identical workbook may cross a
split.

Within each retained workbook, sheets use workbook order and targets use A1 address.
Each visible formula receives the stable key
`SHA256(opaque_workbook_id || sheet_index || A1)`.  Targets are processed in that
order; the first 128 passing the frozen FCRL adapter are retained.  Rejections and
their stable reason codes are counted, but neither selection nor a rejection rule may
change after counts are observed.  A target with no reachable reference is retained
for U1 prediction/reachability accounting; a training batch with no valid range label
uses sketch loss only, matching the mathematical empty-range case.

Every one of the frozen 153/33/33 groups must retain at least one target.  Otherwise
U1 fails as a corpus/adapter coverage failure before training; empty groups are not
silently removed from the macro denominator.

FCRL manifests contain only a new opaque workbook ID, source byte hash, structure
group, split, sheet ordinal, A1 address, target hash, normalized prefix key, local-peer
prefix keys, reference counts, encoder hash, and aggregate rejection counts.  They
contain no paths, task IDs, filenames, sheet names, raw strings, raw numbers,
embeddings, instructions, labels, or answer metadata.  Local shards and model states
remain Git-ignored.

## 4. Fixed local-peer and global baselines

The global-frequency baseline is the five most frequent normalized prefix keys among
retained **train targets only**, ordered by decreasing target count then key.  It is
fixed before calibration or internal-test scoring.

The local-peer completion baseline never reads the target formula.  It translates
visible same-row/same-column peer formulas to the masked target, groups contiguous
peers as frozen in the adapter, and orders candidates by decreasing independent block
count, then nearest Manhattan distance, then prefix key.  The first five distinct
keys are predictions.  No global-frequency backfill is used.

## 5. Training and recovery

- exact U0 base checkpoint and adapter;
- official `LSTMLM` decoder, official `Normal(0,0.02)` initialization;
- backbone always evaluation-mode and gradient-free;
- seed 260831, deterministic algorithms, `PYTHONHASHSEED=0`;
- batch size 8, AdamW learning rate `2e-4`, weight decay `0.01` on all decoder
  parameters, gradient clip `1.0`;
- maximum 15 epochs; no scheduler, warm restart, mixed precision, accumulation,
  architecture search, parameter search, or data-dependent batch-size change;
- each epoch shuffles workbooks and then targets within each workbook using
  `Random(seed + epoch)`; each workbook is parsed once per epoch;
- checkpoints contain decoder/optimizer/RNG state, epoch, manifest hash, source
  commit, and aggregate losses only; no workbook-derived tensor or embedding cache;
- interruption resumes only from a complete epoch checkpoint with matching hashes.

After every epoch, the complete calibration split is decoded with beam size five.
The selection metric is structure-group-macro Top-5 prefix-key accuracy.  An exact
tie keeps the earlier epoch.  Training stops after two consecutive epochs without a
strict improvement or after epoch 15.  Internal-test examples are not decoded during
training.

## 6. Beam and metrics

Beam search uses the registered beam size five, length normalization alpha 1, gamma
0, and maximum 64 tokens.  A batched-beam implementation calls only official
`LSTMLM.sketch_logits` and `range_logits`; completed beams are ordered by the frozen
length-normalized sketch log probability, then token IDs.  Each `<RANGE>` selects the
maximum-probability visible candidate pointer; an unavailable pointer yields an
invalid prediction, never a partial match.  Duplicate normalized keys are removed in
beam order without baseline backfill.

For model, global frequency, and local peer, target hits are averaged within each
structure group and then equally across the 33 internal-test groups.  U1 gates use
these structure-group-macro Top-1/Top-5 values and percentage-point differences.
Workbook-macro and target-micro values are reported as secondary diagnostics.  Gold
reference reachability is the micro reachable/total reference-token fraction over
all retained internal-test targets.

## 7. One-time internal-test discipline

Implementation, target manifest, train-only global baseline, calibration history,
selected decoder SHA-256, environment, and source commit must be frozen in a tracked
candidate-lock record and pushed before any internal-test decoding.  The locked test
runner then executes twice in independent processes solely to verify identical full
prediction hashes.  The first complete result is final.  A failed gate stops FCRL;
test results may not change the adapter, targets, decoder, beam, threshold, split, or
training configuration.
