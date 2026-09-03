# FormulaGuard VEPR U0 result

Date: 2026-09-03

Protocol: `formulaguard_vepr_u0_v1`

Implementation commit: `25a94c787642e5eb73ab945afd97d9836f37bf3f`

Status: frozen U0 availability gate failed; U1 feature extraction, fitting,
ranking, public prediction, and version creation are not authorized

## 1. Reproducible evidence

The VEPR implementation and ten focused tests were committed before the formal
runs. The complete project regression passed with 667 tests, including one skip,
and the affected Ruff check and `git diff --check` passed.

Two independent formal processes completed from the same clean tracked source:

- `results/vepr_u0_run_a`;
- `results/vepr_u0_run_b`.

Both pairs of artifacts are byte identical. Common SHA-256 values are:

- `private_manifest.json`:
  `24bd6336fe2ed0046116a3aa6a82eab7bcc819155554744eadcd4e8bdabc1a5a`;
- `u0_receipt.json`:
  `c125c13926b831c82a36a125ac046acbb903be2f9b1b6c2a9ce6ed1e8f63c6fc`.

Both receipts record `formal_evidence=true`, source commit `25a94c7`, an empty
tracked-source status, the four pinned VEnron hashes, the pinned public grouping
hash, and `protected_data_inputs=[]`. Revalidation reproduced every gate from
the receipt summary and validated both private manifests.

## 2. Input integrity and exclusion

U0 verified all 7,294 formula profiles, 360 complete evolution groups, and 6,934
adjacent transitions. It checked every formula row before constructing a VEPR
label. Eight evolution groups contained at least one invalid legacy formula-text
representation and were excluded in full under amendment 1.

The overlap audit profiled exactly 96 byte-unique public/Enron observed workbooks
without reading a source label. It audited every one of the 130 evolution groups
that could otherwise contribute a ranking transition or unchanged control. Six
groups were near duplicates of public Enron workbooks and were excluded in full.
No invalid or overlapping group contributed a retained row.

The private manifests contain salted group, snapshot, transition, control, and
candidate identities; formula/layout hashes; counts; folds; and Boolean next-edit
labels. Independent schema inspection found no raw formula, workbook path, sheet,
address, public source cell, V4 rank, cached value, constant, cell text, email
field, expected output, correct workbook, or protected input.

## 3. Availability result

The frozen transition conditions identified 291 potential ranking transitions.
Complete-group invalid-profile and public-overlap exclusions removed 13 and 17
transition rows respectively, leaving:

| Quantity | Observed |
| --- | ---: |
| Ranking transitions | 261 |
| Evolution groups | 50 |
| Positive next-edit formula rows | 1,023 |
| Stable candidate rows | 112,217 |
| All candidate rows | 113,240 |
| Deduplicated unchanged controls | 219 |
| Control evolution groups | 107 |

Fold coverage was:

| Fold | Transitions | Groups | Positive rows | Stable rows | Controls | Control groups |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 33 | 7 | 142 | 8,752 | 42 | 18 |
| 1 | 37 | 11 | 124 | 7,724 | 55 | 29 |
| 2 | 137 | 12 | 559 | 26,770 | 64 | 24 |
| 3 | 27 | 10 | 51 | 12,042 | 25 | 13 |
| 4 | 27 | 10 | 147 | 56,929 | 33 | 23 |

The overall positive/stable candidate and control gates pass. The limiting facts
are the total of 261 transitions rather than 300, only 27 transitions in folds 3
and 4 rather than 30, and only 51 positives in fold 3 rather than 80. The large
fold-2 concentration also confirms why group count alone is not adequate evidence.

## 4. Frozen gate decision

| Gate | Required | Observed | Result |
| --- | ---: | ---: | --- |
| Ranking transitions / groups | 300 / 50 | 261 / 50 | **Fail** |
| Positive / stable rows | 600 / 30,000 | 1,023 / 112,217 | Pass |
| Every-fold transitions / groups | 30 / 6 | minimum 27 / 7 | **Fail** |
| Every-fold positive / stable rows | 80 / 3,000 | minimum 51 / 7,724 | **Fail** |
| Controls / groups | 200 / 80 | 219 / 107 | Pass |
| Every-fold controls / groups | 20 / 10 | minimum 25 / 13 | Pass |
| Complete-group overlap exclusion | required | verified | Pass |
| Complete-group invalid-profile exclusion | required | verified | Pass |
| Input, snapshot-order, accounting, and fold integrity | required | verified | Pass |
| Forbidden inputs | zero | zero | Pass |
| Independent-process equality | required | byte identical | Pass |

U0 fails the overall transition and five-fold coverage gates. The failure occurs
before the 2,048 syntax vector, structured feature matrix, model weights, logits,
rankings, abstention threshold, public predictions, or any fault-label score is
created. U1 is not run.

The observed 261 transitions cannot authorize lowering 300, changing the fold
salt, merging folds, redistributing the high-volume fold, removing the per-fold
positive minimum, admitting structural churn, increasing edit/addition bounds,
or reusing the 21 VDEL windows. VEPR therefore stops and cannot be called
`V5-R1` or used to access SpreadsheetBench 2 or either protected `240+120` package.

The narrower finding is that natural VEnron edit supervision supplies many
formula rows but too few well-distributed eligible transitions for the frozen
cross-group study. A successor must obtain a broader, separately licensed set of
natural version histories or change the supervision/inference contract; it may
not train on this failed VEPR subset and then use public fault labels to select a
repair.
