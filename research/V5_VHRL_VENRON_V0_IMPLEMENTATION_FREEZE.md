# FormulaGuard VHRL VEnron V0 implementation freeze

Date: 2026-08-31
Protocol: `formulaguard_vhrl_venron_v0_implementation_v1`
Status: frozen before extraction or opening any of the 7,294 group workbooks
Parent: `research/V5_VHRL_VENRON_INTAKE_FREEZE.md`

## 1. Observed public metadata schema

The separately frozen schema intake opened only
`VEnron1.0/Version/FileOrder.xls`. Its receipt reports 361 sheets: `Group List`
plus one sheet for each of the 360 evolution groups. Each group sheet contains file
rows interleaved with email rows. A file row has the author-supplied version order in
column A, source MD5 in column E, and archive-relative file path in column F.

The full V0 parser may retain only those three fields plus the group ID derived from
the validated sheet title. Sender, recipients, subject, email body, email path, and
all other order-workbook fields are forbidden outputs and forbidden features. The
schema intake itself is public-data evidence but contains email-derived text locally;
it remains ignored and must not be committed or used for model development.

## 2. Safe extraction and identity

Before extraction, the pipeline must verify the acquisition, inventory, and order-
schema receipt hashes, a clean pushed implementation commit, and the pinned archive
SHA-256. Every archive path must already be present in the immutable member manifest.
Verbose archive types must contain regular files and directories only.

Exactly the 7,294 paths referenced by the 360 group sheets are extracted into the
ignored VEnron raw root. `FileOrder.xls`, `readme.txt`, and directory entries are not
included. After extraction, the regular-file set must match the ordered manifest
exactly and each file's MD5 must equal column E. Symlinks, hard links, devices, extra
files, path traversal, duplicates, or identity mismatches fail V0.

The first pre-extraction parser run exposed a publisher metadata encoding defect:
column E contains 6,862 32-character, 400 31-character, 26 30-character, and six
29-character hexadecimal tokens. The archive filename carries the same shortened
token. This is the expected distribution of omitted leading zeroes in fixed-width
MD5 text. The repaired parser accepts only 29-32 lowercase hexadecimal characters,
requires the filename token to match exactly, left-pads the token with zeroes to 32
characters, and verifies that reconstructed MD5 against the extracted file bytes.
No nonhex token or shorter identity is accepted.

## 3. Conversion and formula-only profile

- engine: the installed LibreOffice version recorded in the run metadata;
- output: XLSX under an ignored converted root, preserving group directories;
- workers: 24; each process uses an isolated LibreOffice user profile;
- timeout: 180 seconds per workbook;
- conversion/profile shards are immutable and resumable;
- formula profile retains only opaque group/order identity, sheet title, cell address,
  and formula text as exposed by `openpyxl` with `data_only=False`;
- constants, cached values, cell text, formatting, senders, email text, filenames as
  semantic features, V4 scores, fault labels, and protected data are not exported.

A workbook counts as parsed when LibreOffice produces exactly one XLSX and openpyxl
can enumerate all its worksheets and formula cells. Workbooks with zero formulas are
still parsed and are counted separately. Conversion failure, parse failure, and zero-
formula status remain separate. V0 does not require FormulaGuard's limited formula
grammar to accept the formulas.

## 4. Frozen adjacent-transition definitions

Adjacency is exactly consecutive integer order in the matching group sheet. A pair is
eligible only when both versions parsed successfully. No later timestamp, filename,
email, or content heuristic may reorder versions.

For an eligible pair, keys are exact `(worksheet title, A1 address)` pairs and formula
text is stripped at its two ends only. The categories are:

- `direct_formula_text_change`: both versions contain a formula at the same key and
  the formula strings differ;
- `formula_addition` / `formula_removal`: a formula key exists on only one side;
- `address_only_formula_move`: there is no direct change, additions and removals are
  both nonempty, and their exact formula-text multisets are equal;
- `bulk_direct_rewrite`: at least 20 direct changes and they cover at least 50% of
  formula keys shared by both versions;
- `bulk_add_remove`: at least 20 total formula additions plus removals;
- `no_formula_text_change`: no direct change, addition, or removal.

These are mechanical text-change categories, not user intent. A transition is a
`nonbulk_multi_direct` candidate only when it has at least two direct changes and is
neither a bulk direct rewrite nor a bulk add/remove transition. Sheet renames and row
or column moves are not aligned heuristically in V0; their additions/removals remain
visible and cannot be relabeled as same-address edits. Cached-value differences never
count as formula edits.

## 5. Frozen V0 gates

The original gates are operationalized without lowering them:

1. at least 300 groups and 6,000 ordered group workbooks;
2. at least 1,000 eligible adjacent transitions with a direct formula-text change,
   spanning at least 150 groups;
3. at least 100 `nonbulk_multi_direct` transitions spanning at least 30 groups;
4. at least 80% of all 7,294 group workbooks parse successfully;
5. the receipt reports direct, single, multi, bulk direct, bulk add/remove, address-
   only move, additions/removals, zero-formula, no-formula-change, and ineligible
   counts separately;
6. protected-data, fault-label, expected-output, cached-value-diff, and V4 inputs are
   all empty.

Gate 3 deliberately uses the nonbulk subset so a large sheet rewrite cannot create a
false appearance of many responsibility-ranking examples. Any failed gate stops VHRL
before regression-proxy labeling or model implementation. No threshold or alignment
rule may be changed after the first complete V0 score.
