# Zenodo 4091366 Candidate Preregistration

Status: development-source audit only; not eligible for final evaluation.

## Provenance gate

- Record: [Zenodo 4091366](https://doi.org/10.5281/zenodo.4091366), concept record 3929150.
- Metadata lists CC BY 4.0 and describes version 1.1 as containing fixes to small errors and formulas.
- The record lists `Argentina_Camarones.xlsx` and `Argentina_Camarones_v1.1.xlsx` in the same release. This is a version-pair lead, not yet proof that the first file is the erroneous predecessor or that every formula difference is a correction.
- API response digests and the fields checked are recorded in `source_evidence/ZENODO_METADATA_SCREEN_20261019.json`. The raw responses are local-only under the ignored `source_evidence/raw/` directory.

## Frozen input and prediction procedure

1. Acquire only the two files named above from the record's public files endpoint. Record byte size, SHA-256, source URL, and acquisition time before inspection.
2. Run the frozen 2026-09-04 paper model on `Argentina_Camarones.xlsx` only, using the existing read-only `tools/predict_workbook.py` interface, no parallel-sheet declaration, and a new output path. Do not provide the v1.1 file, author-difference material, labels, or any scoring artifact to prediction.
3. Preserve the full runner output and its hash. The `paper` result is the sole primary model output; any comparator output is exploratory and cannot alter this registration.
4. Record the baseline handoff locks: `baseline/protocol/source_lock.json` SHA-256 `1c346caac23ccbdc8c7462fbf56f0a22a3507dbb29247fde86325363cfe6424d`; frozen prediction adapter SHA-256 `286e01533e43572ddb67b4b40256d32beda06f65c502ecf81ec74ec070fbffb3`; paper protocol SHA-256 `6e4f4cc3fbe1ef9e6ebb679646cdb6386a2ead012b2c3ed285c2105bafb8e652`.
5. Prediction is inference only. Do not inspect formula differences or assign any error labels until the prediction output and input hashes are locked.

## Label and scoring rules

- A changed formula is only a candidate label. Count it as an error only where the source's correction statement applies and an independent business/structural check confirms that the revised formula expresses the intended row/column role and uses the proper dependencies. A changed value, formula text, or version number alone is insufficient.
- Inspect all changed cells and a sample-independent set of unchanged formula cells; retain ambiguous cases as `unknown`. Keep non-formula changes, formula changes without independent intent evidence, unsupported cells, and rejected predictions visible in the inventory.
- Primary repair endpoint: literal full-formula equality between the paper model's proposed formula and the independently confirmed corrected formula. Secondary analyses may report dependency-equivalent formulas separately.
- Suggestion precision denominator includes every nonempty changed-formula proposal, including proposals on correct cells. Error-cell coverage denominator includes every confirmed erroneous formula cell; `review`, refusal, unsupported, failure, and unknown do not count as a correct repair or leave the denominator.
- No threshold, rule, candidate generator, or model tuning on this source. Any findings used to choose later experiments make this entire source development evidence permanently.

## Scope and stop conditions

This record can contribute at most one source and one template family. It cannot support a population claim or the six-source/fifteen-family final evaluation. If the two files do not form a traceable error/correction pair, if licensing attribution is insufficient for the intended use, or if independent formula intent cannot be established, retain the acquisition and classify the candidate as non-scorable. Do not run an accuracy experiment until prediction locking and the label audit are complete.
