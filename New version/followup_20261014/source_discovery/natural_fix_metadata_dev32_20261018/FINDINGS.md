# Natural-correction provenance search, 2026-10-18

Two pinned parent/correction workbook chains were found in repository metadata:

- micro-solution/BPA: business-planning XLSM; 2020-07-08 commit
  bc9918fa2947b5c3823fc782809dc67f68e5b16b says "fix formulas in .xlsm".
  Parent 5d462b8ffa4e03a2eefe441b879bd23d52558e09 has the same path with
  a different binary blob. Both repositories API responses identify no fork.
- drjlevi6/Data-Scientist: Linear Regression/Weights.xlsx; 2023-11-15 commit
  c071cf71a81a7ba43a1cf4712c67a6925bfa52bf says "Correct formula errors".
  Parent 6f52de87c8f30a46bc4be36b9cdc9206036d88a3 has the same path with
  a different binary blob. Size changes substantially; no unchanged-input or
  localized-correction claim is justified before OOXML comparison.

No workbook bodies were retrieved. Neither repository declares an SPDX license
in the repository response; record this as unknown. Commit messages and changed
binary blobs are correction leads, not certified formula labels or confirmed
original errors. The trace stores commit metadata and text patches; none of
this metadata is used by the dev32 prediction process.

An original workbook removal and a newly added recalculation file are not
accepted as original/correction pairs. One broader search failed with
IncompleteRead; its failure is preserved, not silently retried as a success.

Remaining gates: origin/history/related-template audit, model/protocol freeze
before any final workbook or answer-body acquisition, original prediction lock
before correction reading, literal formula and non-formula diff, semantic
certification, full suggestion adjudication and family deduplication. Final
qualified sources/families stay 0/0. Preserve these two as reserved candidates;
if used for development later, exclude the entire origins from final validation.
