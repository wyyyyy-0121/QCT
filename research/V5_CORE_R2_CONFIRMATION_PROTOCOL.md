# FormulaGuard V5-Core R2 Independent Confirmation Protocol

## Purpose and evidence boundary

R2-R1 can enter this protocol only if the revealed-data pressure receipt says
`eligible_for_new_independent_confirmation: true`.  The 480-error development
set, 360 clean controls, historical 100 cases, and Enron events remain
development or retrospective evidence.  None may be relabeled as independent.

The confirmation set is prepared outside the project by a third party after
the model, clean null, source code, pressure receipt, and Git commit are
frozen.  FormulaGuard receives no source cells, error categories, correct
formulas, or clean/error indicators before prediction locking.

## Confirmation composition

The complete set has 780 workbooks:

| Secret stratum | Count |
|---|---:|
| Six traditional silent-error mechanisms, 70 each | 420 |
| A withheld mutation mechanism family | 90 |
| Correct repair deliberately absent from the candidate pool | 60 |
| Unsupported syntax, multiple plausible sources, or insufficient evidence | 30 |
| Clean regular workbooks | 45 |
| Clean workbooks with legal exceptions | 45 |
| Clean periodic or two-dimensional regimes | 45 |
| Clean cross-sheet structures | 45 |

At least 150 structures must be derived from legally usable, anonymized real
workbooks, and at least 120 error cases must be manually or semi-manually
designed.  Development-to-confirmation overlap is forbidden for normalized
correct-to-error transformations and for exact graph-signature/formula-
fingerprint pairs.

## Precommit and archives

Before the R2 freeze, the third party publishes only
`third_party_precommit.json` containing:

```text
total_cases=780
error_cases=600
clean_cases=180
model_was_run=false
development_overlap_audit_passed=true
independent_preparer=true
public_zip_sha256
secret_zip_sha256
labels_csv_sha256
exceptions_csv_sha256
design_ledger_csv_sha256
provenance_csv_sha256
declaration_json_sha256
```

`PUBLIC.zip` contains only:

```text
manifest.csv                 # exactly instance_id,workbook
secret_precommit_sha256.txt
workbooks/*.xlsx
```

`SECRET.zip` contains at least:

```text
labels.csv
exceptions.csv
design_ledger.csv
provenance.csv
originals/*.xlsx
third_party_declaration.json
```

The secret `labels.csv` has one row per public identifier.  Required fields
are `instance_id,case_kind,challenge_stratum`.  Error rows also provide
`source_cells`; clean rows leave it empty.  Traditional errors provide
`error_type`; repair-evaluable rows may provide `correct_formula`.

The independent preparer can validate and package an already-created dataset
without running FormulaGuard by using:

```bat
run_v5_core_r2_prepare_third_party.cmd --input D:\outside\raw --output D:\outside\pack
```

Both directories must stay outside the repository.  This tool does not
generate cases or call a localization method.  It verifies event-table grain,
original/mutant formula agreement, single injection except declared ambiguous
events, silent numeric behavior, downstream propagation, workbook uniqueness,
translation-invariant formula-pair separation from development, permissions,
anonymization, and the real/manual construction floors before writing hashes.
It also rejects an exact match to development in either a source-relative
correct-to-mutant transformation or the combined graph/formula signature.  Its
output directory must be empty and may not overlap the raw input directory.

After a successful immutable freeze, performance is measured separately from
the confirmation cohort with `run_v5_core_r2_performance.cmd`.  Isolated
latency remains serial, aggregate throughput uses 24 independent processes,
and Python allocation peaks use a separate `tracemalloc` pass so those three
quantities are not conflated.

## Lock order

1. Pressure safety passes.
2. R2 freeze configuration is generated, committed, tagged
   `v5-core-r2-lock`, and pushed.
3. The third party releases only `PUBLIC.zip`.
4. V4, V4.3, R2-Source, and R2-Full complete rankings are generated without
   labels and hash-locked.
5. Only then may `SECRET.zip` be released.
6. The scorer verifies every precommitted hash and scores all 780 cases once.
7. No post-confirmation tuning, exclusions, threshold changes, or replacement
   datasets are allowed.

## Metrics and promotion rule

Error cases report Top-1/3/5, MRR, EXAM, per-stratum results, candidate-missing
results, and paired 10,000-sample bootstrap intervals against V4 and V4.3.
Clean cases report alarm false-positive rate and diagnostic-state counts.
Abstention reports coverage and selective Top-1 error risk; unsupported cases
remain in all denominators.

R2 may replace V4 only when all of the following hold:

- paired R2-Full minus V4 and V4.3 MRR intervals exclude zero on the positive side;
- paired macro Top-5 intervals exclude zero on the positive side;
- candidate-absent R2-Source Top-5 does not collapse;
- clean alarm false-positive rate is at most 10%;
- selective diagnosis reduces wrong forced Top-1 decisions;
- benefit is not confined to fewer than four secret error/regime strata;
- no clear safety regression appears in real-structure cases.

Failure is retained and reported.  It does not authorize another round of
tuning on the confirmation labels.
