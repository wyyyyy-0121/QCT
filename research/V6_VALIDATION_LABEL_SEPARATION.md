# V6 locked internal validation label separation

Date: 2026-08-26

Before any 360-event validation prediction was created, the fixed validation
generator produced 360 public instances, 360 mutant workbooks and 360 matching
clean workbooks. The label-aware dataset-quality and cross-split leakage audit
was completed as a separate data-preparation phase. It passed all hard gates
and reported no template, normalized formula-pair or graph-formula overlap with
the development, red-team or clean-control splits.

The resulting precommit receipt is
`research/V6_VALIDATION_PRECOMMIT.json`. It freezes:

- eight public manifest/audit file hashes;
- an aggregate inventory hash for all 720 workbooks;
- the secret `evaluation_labels.jsonl` SHA-256 without recording label rows;
- V4, V6 and method-specification source hashes;
- Git commit `6ea31becd8cf0a4892a440a4fd056db581598ff5`;
- the fact that no validation prediction directory existed at precommit time.

`run_v6_validation.py` no longer constructs or label-audits the dataset inside
the prediction command. Its first phase verifies only public files, workbooks
and model hashes. The localization subprocess reads `instances.jsonl` and
mutant workbooks only. The secret label hash is checked and scoring is enabled
only after `prediction_complete.json` proves all 360 complete rankings exist
and the full-ranking audit passed.

This is an internal locked validation rather than a third-party blind test:
the deterministic project generator necessarily created the labels during the
separate preparation phase. The evidence supports process separation and
tamper detection, not a claim that an external custodian held these labels.
The final 600-event third-party protocol remains the independent evaluation.
