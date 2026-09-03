# V4 static-fifth public revision confirmation protocol

Date frozen: 2026-09-03

Status: prospective single-project confirmation; no formal version is
authorized by this document

## 1. Question and fixed candidate

This protocol asks whether the already frozen V4 static-fifth candidate exceeds
V4-R1 on a separately collected set of public, author-confirmed workbook
revisions under the same five-cell review budget.

The candidate is not changed for this evaluation:

- implementation commit:
  `2a5ec423d647b5879feb3796fff168424438167e`;
- architecture: preserve V4 ranks 1-4, then place the highest static-anchor
  formula outside that prefix at rank 5;
- implementation: `formulaguard/v4_static_fifth.py`;
- model version: `v4-static-fifth-exploratory-v1`;
- review budget: 5 for both V4-R1 and the candidate.

The rule has no corpus gate, learned weight, or threshold.  SFRI is not included
in this test because it did not pass its own frozen promotion gate.

## 2. Evidence chronology and claim boundary

The public revision delivery archive predates this protocol but was not an
input recorded by the static-fifth candidate lock.  The candidate implementation
was committed on 2026-08-31 at 09:45 +08:00.  QCT first preregistered use of the
verified-revision corpus on 2026-09-01.  The existing static-fifth selection and
candidate lock name only the prior public development predictions and their
formula-change signature inventory, not this revision corpus.

The archive is:

- path:
  `/home/ayaka/code/FormulaGuard_public_revisions_delivery_20260831.zip`;
- SHA-256:
  `9a8496ff1ee457473bcf34019c3af2aa369fa38c41e2c8975d86b9067f9a67e4`;
- known scope before prediction: four before/after workbook pairs from one
  MIT-licensed public project, containing eight corrected formula cells.

One project and four revision events cannot establish cross-project or natural
error generalization.  A pass can only add a bounded public-revision confirmation
to the existing candidate.  It cannot authorize `V5-R1`, protected evaluation,
or a broad production claim.

## 3. Prediction isolation and lock

Prediction may read only archive members matching
`public_revisions/workbooks/PWR[0-9]{3}/before.xlsx`.  It must reject duplicate
IDs, unexpected before-workbook counts, unsafe ZIP names, symlinks, encrypted
members, and an archive hash mismatch.

Before prediction lock, the runner must not read or extract:

- `cases.csv`;
- `manifest.json`;
- any `after.xlsx`;
- validation reports, handoff text, or other label/provenance files.

Each before workbook is staged from verified bytes, parsed once, and receives
complete V4-R1 and static-fifth rankings.  Every shard records the archive hash,
member name, member-byte hash, source hashes, and empty `label_inputs` and
`protected_data_inputs`.  Two independent output directories must be byte
identical and hash-locked before scoring begins.

## 4. Revealed scoring

Only after both prediction locks verify may a separate scorer read `cases.csv`,
`manifest.json`, and the four `after.xlsx` members.  It must independently
recompute the before/after formula differences and verify that the case labels
match those diffs.

Each workbook pair is one revision event.  Its source set is the set of formula
cells changed from before to after.  A method's event rank is the best rank of
any changed formula cell.  The scorer reports event Top-1, Top-5, MRR, paired
rescues and losses, formula-cell Top-5 coverage, and results by revision ID.

No workbook name, sheet name, address, post-revision formula, or case metadata
may influence prediction ranking.

## 5. Frozen gates

The bounded confirmation passes only if every condition holds:

1. both independent prediction runs are byte identical and all archive,
   source, shard, ranking, and scoring hashes verify;
2. all four preregistered revision pairs and all eight declared formula changes
   are present and independently reproduced;
3. V4-R1 and static-fifth rank exactly the same complete formula inventory for
   each before workbook and both use a five-cell review budget;
4. static-fifth produces at least one net Top-5 revision-event rescue and has
   strictly higher event Top-5 than V4-R1;
5. there are zero Top-5 revision-event losses and no per-revision regression;
6. event MRR does not decrease;
7. prediction reads no label or protected input, and scoring reads no protected
   `240+120` input.

The thresholds cannot be changed after reading `cases.csv` or any `after.xlsx`.
Failure of any gate records a negative result and leaves the existing candidate
status unchanged.

## 6. Version artifact rule

Only a complete pass authorizes creation of
`research/V4_STATIC_FIFTH_REVISION_CONFIRMED_CANDIDATE.json`.  That file must
bind the unchanged candidate source, both prediction locks, the score receipt,
all relevant hashes, the exact limited claim, and `formal_version: null`.

No artifact named `V5`, `V5-R1`, `release`, or `production` may be created from
this four-event result.
