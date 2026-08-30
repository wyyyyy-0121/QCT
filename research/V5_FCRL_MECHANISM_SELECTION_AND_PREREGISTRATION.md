# FormulaGuard FCRL mechanism selection and preregistration

Date: 2026-08-31
Protocol: `formulaguard_fcrl_preregistration_v1`
Status: frozen before checkpoint acquisition, Torch installation, or model implementation
Research name: `FCRL` (Formula Counterfactual-Regret Localizer; not a formal version name)

## 1. Selection decision

`V4-R1` remains the only frozen main ranker. Gate 2A/2B, CWRP, and DRFV did not
authorize a successor. DRFV stopped at its corpus gate before training, so its
conditional replacement-discrimination hypothesis was not tested. This record does
not lower that failed gate or resume DRFV on the same protocol.

The next research line uses one genuinely new information source relative to the
failed FormulaGuard candidates: a frozen public formula-pretrained table encoder.
It tests one narrow mechanism:

> Mask each possible formula source cell, estimate the conditional probability of
> its observed formula and workbook-supported alternatives, and rank the cell by
> the probability regret of keeping the observed formula rather than the best
> supported counterfactual; abstain when no alternative has independent support.

The selected backbone is the public base ForTaP checkpoint. It is a cited dependency,
not a FormulaGuard contribution. The Enron formula-prediction fine-tuned checkpoint
is forbidden because Enron is a FormulaGuard retrospective safety corpus. FCRL may
be discussed as a possible successor only after every gate in this document passes.

## 2. Public-artifact audit and rejected options

### 2.1 HERMES: rejected as an executable backbone

- Repository: `https://github.com/formulet/HERMES`
- Audited commit: `e8a9f6c30cc604955a5adda506b794f1e504a709`
- Public tree at that commit: `README.md` and `HermEs_DEMO.mp4` only.
- No source, license file, configuration, data preparation code, model checkpoint,
  release, or runnable command is present.
- The ACL 2023 paper reports a TUTA encoder, hierarchical Formulet expansion,
  106K Enron samples, 30K FUSE samples, and a 265M-parameter model. Those ideas and
  results remain related work; they cannot be reproduced from the public repository.

### 2.2 ForTaP: selected only as a frozen cited backbone

- Repository: `https://github.com/microsoft/TUTA_table_understanding`
- Audited commit: `4de8bba4e9bf6a89b2e131bfb471b4db2c45b951`
- License: MIT for the repository.
- Public artifacts: model code, base ForTaP checkpoint link, Enron formula-prediction
  data, and an Enron fine-tuned checkpoint link.
- Reproducibility limits: the 13.5M-file pretraining corpus is not public, dependency
  versions are not locked, no automated tests are supplied, and the runner assumes
  CUDA. The paper reports 4.5M retained tables, 10.8M formulas, and four V100 GPUs.
- FCRL therefore records the exact downloaded checkpoint hash and treats the base
  checkpoint as an external binary dependency. It does not claim to reproduce
  ForTaP pretraining or its reported 55.8% Enron Top-1 result.

### 2.3 SheetJS EDRM: rejected for the first FCRL attempt

The metadata-only tree snapshot at SheetJS commit
`5b73fc395cbe4727a986ab02a5028c1c1585617f` contains 20,256 `edrm/*.xls`
members totaling 6,400,760,437 bytes and is covered by the repository's CC0 file.
The repository README also warns that the original EDRM corpus contained personal
information. It overlaps the Enron domain used for FormulaGuard safety evaluation.
No EDRM workbook content has been downloaded for FCRL. This source is excluded from
FCRL v1 to avoid an unnecessary privacy surface and an unusable Enron comparison.

## 3. Prior-art boundary and falsifiable contribution

Established work that must be cited and must not be claimed as new includes:

- ForTaP/TUTA formula-aware table pretraining and formula prediction;
- SpreadsheetCoder contextual formula generation;
- HERMES hierarchical Formulet generation;
- FLAME formula tokenization, pretraining, corruption, and repair;
- ExceLint relative-reference fingerprints, anomaly regions, and fixes;
- CUSTODES/WARDER formula clustering and outlier detection;
- general pseudo-likelihood, likelihood-ratio anomaly detection, conformal
  calibration, counterfactual ranking, and selective prediction.

The only proposed contribution is the **counterfactual-regret localization head**:
formula prediction is run for every observed formula cell, the observed formula is
scored alongside alternatives supported independently by the workbook, and the
margin is converted into a full source-cell ranking plus an abstention decision.
Prediction accuracy is not localization accuracy and will be reported separately.

The contribution is falsified if any of the following holds:

1. raw observed-formula surprisal performs as well as counterfactual regret;
2. local-peer ranking performs as well as FCRL;
3. replacing ForTaP initialization with the fixed random-init ablation does not hurt;
4. removing independent alternative support does not increase clean actions;
5. FCRL cannot exceed `V4-R1` on the frozen public localization gates.

## 4. Inputs and information contract

For each target formula cell, its formula and cached value are removed from the table
input and replaced by `[FORMULA]`. The frozen encoder may read the same workbook's
cell text, numeric values, formatting, position, and non-target formulas because
these are part of ForTaP's published input contract. The target formula is supplied
only to the candidate scorer, never to the context encoder.

Raw cell text, numeric values, filenames, sheet names, and embeddings are transient:
they must not be written to manifests, predictions, logs, tests, or Git. Committed
outputs may contain only opaque workbook IDs, cell addresses, normalized formula
tokens, aggregate counts, scores, reasons, and hashes. Fault labels, correct formulas,
expected outputs, `V4` rankings, and protected data are forbidden training inputs.

## 5. Fixed model and score

### 5.1 Backbone and formula predictor

- frozen base `fortap.bin` checkpoint acquired from the official ForTaP link;
- official commit fixed in Section 2.2;
- all backbone parameters frozen;
- a two-stage formula decoder matching the published ForTaP formula-prediction
  output contract: sketch tokens first, then referenced cells from visible input;
- maximum input length 512, formula length 64, beam size 5;
- decoder hidden size inherited from the checkpoint, dropout 0.10;
- AdamW, learning rate `2e-4`, weight decay `0.01`, gradient clip `1.0`;
- fixed seed `260831`, deterministic algorithms, batch size 8, at most 15 epochs;
- early stopping on calibration-group Top-5 exact formula accuracy, patience 2;
- no architecture, learning-rate, beam, seed, or feature search.

If exact reuse of the base checkpoint is technically impossible, Gate U0 fails. It
is forbidden to substitute the Enron-fine-tuned checkpoint or silently reimplement
a different backbone under the ForTaP name.

### 5.2 Counterfactual-regret localization head

For target cell `c`, let `f` be the observed normalized formula and `A(c)` be the
union of the decoder beam and translated local-peer formulas. An alternative is
supported only if it is parseable, differs from `f`, and either occurs in at least
two non-target peer cells or is independently proposed by both the decoder and one
peer cell. Duplicate peers from the same translated formula block count once.

All formula log probabilities are length-normalized. The fixed full-ranking score is

`regret(c) = max(0, max_g logP(g | masked_context(c)) - logP(f | masked_context(c)))`

over supported `g` in `A(c)`. The secondary key is lower observed-formula log
probability, followed by stable sheet and cell order only as a final deterministic
tie-break. The head does not use V4, dependency impact, output truth, or a repair
execution result. The selected action threshold is the single calibration quantile
that maximizes error coverage subject to at least 75% synthetic acted precision and
at most 15% paired-clean action rate; ties choose the higher threshold.

## 6. Development corpus and immutable splits

FCRL reuses only the already materialized SpreadsheetBench v1 input workbooks from
the DRFV intake. Answers, instructions, answer positions, and answer workbooks remain
forbidden. The previously observed corpus audit is a resource fact, not a new blind
gate: 607 retained unique workbooks, 219 structure groups, and 74,570 parseable
formulas. DRFV's U0 failure remains unchanged.

The existing DRFV structure-group IDs are sorted by SHA-256. The first 70% are
training, the next 15% calibration, and the final 15% internal test. A workbook or
near-duplicate group cannot cross splits. Each workbook contributes at most 128
formula targets by stable hash. The test split is not used for early stopping,
threshold selection, or implementation debugging after its first complete score.

All FormulaGuard localization corpora, SheetJS `nuix/`, EDRM, SpreadsheetBench 2,
the old trial package, and the new protected package are excluded from training.

## 7. Gates and stopping rules

### Gate U0: artifact and adapter reproducibility

After this protocol is committed, acquisition must record the repository commit,
checkpoint URL, byte size, SHA-256, license hash, Python/Torch/CUDA versions, and GPU.
The adapter must pass target-leakage, repeat-hash, parser, unsupported-formula,
translation, and one-batch forward/backward tests. The checkpoint must load without
using any Enron-fine-tuned weights. Failure stops FCRL before corpus training.

### Gate U1: formula-prediction information

On the untouched structure-group test split, all must hold:

- Top-5 exact normalized-formula accuracy at least 50%;
- Top-1 exact normalized-formula accuracy at least 25%;
- Top-5 at least 10 percentage points above global formula frequency;
- Top-5 at least 5 points above local-peer completion;
- at least 70% of gold referenced cells are present in the truncated input;
- repeated inference in independent processes has identical prediction hashes.

Failure stops FCRL. A low formula-prediction score cannot be rescued by localization
labels or by lowering the gate.

### Gate U2: fixed self-supervised localization

For each internal-test workbook, one target formula is selected by stable hash and
replaced using the eight already frozen DRFV corruption families. Each corruption is
generated without fault labels. FCRL, raw surprisal, local peer, and frozen V4 rank
all parseable formulas. All must hold:

- workbook-macro Top-5 exceeds both V4 and local peer by at least 5 points;
- counterfactual regret exceeds raw surprisal Top-5 by at least 3 points;
- at least seven of eight corruption families are nonnegative versus V4 and none
  regresses by more than 5 points;
- synthetic acted precision is at least 75%, error coverage at least 30%, and the
  paired unmodified-workbook action rate at most 15%;
- formula-only and context-shuffled ablations each reduce Top-5 by at least 5 points.

U2 is scored once. Failure stops FCRL without a revised corruption family, threshold,
decoder, context window, or score on the same test split.

### Gate U3: revealed retrospective safety

Only after U1/U2 pass may the fixed model be run once on Enron 30, public-pressure
60 error plus 30 control, and historical 100. These are revealed retrospective data,
not independent confirmation. Training overlap is removed by byte, exact structural,
and weighted-Jaccard `>=0.80` component before the run. All must hold:

- Enron Top-5 exceeds V4 by at least 5 points and MRR does not fall;
- public-pressure and historical Top-5 do not fall more than 5 points versus V4;
- public-control action rate is at most 15%;
- counterfactual regret beats raw surprisal on Enron and at least one N2 queue;
- the frozen-backbone, no-support-gate, raw-surprisal, local-peer, and random-init
  ablations are all reported.

Failure stops FCRL. These labels cannot be used for a second architecture or threshold
revision.

### Gate U4: locked public external evaluation

After U3 passes, source, configuration, decoder weights, environment, acquisition
receipt, overlap exclusions, and predictions on all preceding public inputs are
committed. SpreadsheetBench 2 Debugging is then received under the existing
input-before-gold discipline. Input predictions are completely locked before any
gold workbook is materialized. Eligibility, metrics, baselines, and thresholds are
the unchanged DRFV U2 definitions. FCRL must satisfy every DRFV U2 performance and
control threshold; failure stops the line.

## 8. Protected `240+120` authorization

The protected directory remains inaccessible until U0-U4 all pass and the final
candidate specification, source, configuration, weights, environment, and complete
public prediction lock are committed. Before then, no directory enumeration, hash,
file read, overlap check, or schema inspection is allowed.

The user has authorized Codex to run the protected evaluation immediately when all
conditions are met, without waiting for another message. The run is one-shot and may
not tune the model. A passing result supports only the registered unseen injected-
error/control claim unless the package independently establishes stronger provenance.

## 9. Version and paper discipline

`FCRL` is a research name. It is not `V5-R1` during U0-U4. Even after a pass, the
paper must describe ForTaP as prior work and an external frozen backbone, report the
unavailable pretraining corpus and checkpoint dependency, and limit originality to
the localization head and its validated behavior. HERMES numbers may be cited only
as formula-generation results, not as a reproduced baseline.
