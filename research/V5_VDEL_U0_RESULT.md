# FormulaGuard VDEL U0 result

Date: 2026-09-03

Protocol: `formulaguard_vdel_u0_v1`

Implementation commit: `cf739d03ca890a6f756759443609b03b9eb9420a`

Status: frozen U0 availability gate failed; U1 feature extraction, fitting, and
ranking are not authorized

## 1. Reproducible evidence

The implementation includes amendment 1's complete-group exclusion for old
VEnron profiles containing nondeterministic openpyxl object renderings. The
complete regression passed with 657 tests, including one skip, and the affected
Ruff check passed before the formal runs.

Two independent formal runs completed from the same clean tracked source:

- `results/vdel_u0_run_a`;
- `results/vdel_u0_run_b`.

Their two artifacts are byte identical. Common SHA-256 values are:

- `private_manifest.json`:
  `7f5a0294070b748e5e90741522470e6a66065b9a7243fd47dfa94cbef4137da1`;
- `u0_receipt.json`:
  `9d842e296a6ce3b48c8e778da2455a15849df075f1be7318127259e87444e12c`.

Both receipts record `formal_evidence=true`, an empty tracked-source status,
`protected_data_inputs=[]`, and the immediate next VEnron formula state as the
only label input. No cached value, constant, email field, FormulaGuard fault
label, public source cell, answer workbook, V4 outcome, or protected input was
used.

## 2. Input integrity and exclusions

The audit verified the frozen indexes accounting for 7,294 formula profiles,
360 author-ordered groups, and 6,934 adjacent-transition records against the
preregistered hashes. Every shard read for a candidate group was also checked
against its indexed SHA-256. The frozen delta rules produced 239 potential
three-version transitions in 40 groups.

One candidate group contained an old profile with an unstable
`ArrayFormula` object rendering and was excluded in full. Four further groups
were near duplicates of public Enron observed workbooks under the frozen
formula-containment rules and were excluded in full. Those four groups accounted
for nine potential transitions. No excluded group contributed a ranking window
or control.

The public side of the overlap audit profiled exactly 96 byte-unique workbooks.
Its corrected extractor reads stable `ArrayFormula.text`; it does not export
constants, paths, formulas, or cross-corpus match rows. The private VDEL
manifest likewise contains only opaque hashes, folds, counts, and Boolean
longevity labels.

## 3. Availability result

After exclusions and all frozen window rules, the 239 potential transitions
were classified as follows:

| Classification | Transitions |
| --- | ---: |
| Mixed re-edited/stable ranking window | 21 |
| No-re-edit control | 50 |
| Every available edit re-edited | 105 |
| Worksheet-title set changed | 26 |
| Fewer than two candidates remained in the next version | 17 |
| Excluded invalid-profile group | 11 |
| Excluded near-duplicate group | 9 |

The 21 ranking windows span 12 evolution groups and contain 111 available
candidates: 67 re-edited and 44 stable. Fold coverage is:

| Fold | Windows | Groups |
| ---: | ---: | ---: |
| 0 | 4 | 2 |
| 1 | 9 | 5 |
| 2 | 2 | 1 |
| 3 | 4 | 3 |
| 4 | 2 | 1 |

The 50 no-re-edit controls span 20 groups, so the separate control-availability
gate passes. The bottleneck is not control supply. Most otherwise eligible
transitions either re-edit every surviving candidate or do not supply enough
mixed within-delta outcomes for a responsibility ranking.

## 4. Frozen gate decision

| Gate | Required | Observed | Result |
| --- | ---: | ---: | --- |
| Ranking windows / groups | 120 / 40 | 21 / 12 | **Fail** |
| Candidates / re-edited / stable | 240 / 120 / 120 | 111 / 67 / 44 | **Fail** |
| Every fold windows / groups | 15 / 8 | minimum 2 / 1 | **Fail** |
| No-re-edit controls / groups | 30 / 15 | 50 / 20 | Pass |
| Complete-group overlap exclusion | required | verified | Pass |
| Complete-group invalid-profile exclusion | required | verified | Pass |
| Input/accounting/fold integrity | required | verified | Pass |
| Forbidden inputs | zero | zero | Pass |
| Independent-process equality | required | byte identical | Pass |

U0 fails three independent sample-size and coverage gates. U1 is therefore not
run. The model, features, weights, logits, rankings, and version artifact do not
exist. The observed 21-window development subset cannot authorize lowering the
window, group, candidate, class, or fold thresholds; extending the future
horizon; admitting single-edit transitions; changing overlap rules; or reviving
VHRL's exact-reversion labels.

This result preserves a narrower finding: VEnron contains enough no-re-edit
controls but not enough cross-group, mixed one-step edit-longevity windows for
the preregistered learning task. It does not refute version-aware review in
general and does not establish formula-error truth.

SpreadsheetBench 2 remains unreceived. No protected `240+120` package was
listed, searched, hashed, opened, copied, or matched. VDEL never authorizes
protected access because those packages do not satisfy its prior/current/future
input contract.
