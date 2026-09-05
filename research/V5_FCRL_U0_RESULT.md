# FormulaGuard FCRL U0 result

Date: 2026-08-31
Protocol: `formulaguard_fcrl_u0_v1`
Result: **PASS**
Scope: artifact, adapter, leakage, determinism, and one synthetic GPU batch only

## Artifact identity

- official source commit:
  `4de8bba4e9bf6a89b2e131bfb471b4db2c45b951`;
- MIT license SHA-256:
  `c2cfccb812fe482101a8f04597dfc5a9991a6b2748266c47ac91b6a5aae15383`;
- base checkpoint: 547,835,515 bytes, SHA-256
  `42c2166afb60fedf833fcdbc4469dd6e23611f786aa7220a20375117c6c5a4a1`;
- 205/205 `BbForTuta` tensors matched by exact key and shape;
- frozen backbone parameters: 108,668,496;
- trainable official `LSTMLM` decoder parameters: 33,755,945;
- no Enron fine-tuned checkpoint was loaded.

## Adapter and leakage checks

The adapter rules were frozen in
`research/V5_FCRL_ADAPTER_IMPLEMENTATION_FREEZE.md` before constructing a public
corpus example.  Synthetic workbooks differing only in the target formula and target
cached value produced the same encoder hash:

`87ad509cedfb6d5d73b1bd2066e39d55402c9d2fac3ab06f95a6f71c02045ddc`.

Two independent Python processes reproduced that hash.  Cross-sheet references were
rejected, both target marker tokens survived truncation, and both synthetic gold
reference endpoints were reachable.  These are mechanism tests, not a corpus-level
coverage estimate.

## Official-code compatibility boundary

The official aggregate `FPTUTA` was not imported because `model/heads.py` requires
undeclared `torch_scatter`.  FCRL imported only `FPTokenizer`, `BbForTuta`, and
`LSTMLM`.

The first pre-corpus synthetic decoder call exposed an official tensor-layout bug:
`LSTMLM` passed a sequence-first query with batch-first encoder key/value to
`MultiheadAttention`.  The frozen adapter transposes key/value only.  The final U0
rerun used this recorded compatibility fix and the official `init_tuta_loose`
`Normal(0,0.02)` decoder initialization.

## GPU forward/backward

- environment: Python 3.11.16, Torch 2.13.0+cu130, CUDA runtime 13.0;
- GPU: NVIDIA GeForce RTX 5070 Ti Laptop GPU;
- CPU worker setting: 24;
- encoded shape: `[1,24,768]`, all finite;
- sketch/range/total synthetic losses: 3.6699848 / 2.0235510 / 5.6935358;
- decoder gradients were present and finite;
- frozen backbone gradient count was zero.

## Boundary and next gate

U0 proves only that the exact public base artifact and frozen adapter can execute
without target leakage on a synthetic batch.  It does not show useful formula
prediction, localization, calibration, or improvement over V4.  No SpreadsheetBench
v1 training example has yet been constructed by FCRL, and U1-U4 have not run.

Protected inputs, fault labels, answer workbooks, SpreadsheetBench 2, old trial data,
and new custodian data were not accessed.  The protected `240+120` remains locked
until every U0-U4 condition and the complete public prediction lock are committed.
