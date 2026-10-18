# MOD cadet statistics source audit preregistration

Date: 2026-10-19. Stage: source/format audit only, before obtaining workbooks.

## Candidate and disclosure

The UK Ministry of Defence's HTML statistical release for 1 April 2021 says that Table 2 revised 1 April 2018 VCC age-group percentages because of a formula error, without affecting the underlying VCC counts. This official correction statement has already been read. No source workbook, formula, cell coordinate, or corrected formula has been read for this candidate. This is a disclosed source lead; no blind-validation qualification is claimed.

Official metadata for the 2018 release identifies one `.xlsx` attachment, and the GOV.UK page carries the standard OGL v3 notice subject to stated exceptions. Metadata and page snapshots are retained locally. Confirm the page-level notice before acquisition; it is not a claim to blanket rights over any third-party material. No source workbook will be redistributed.

## Ordered procedure and stop conditions

1. Obtain only the 2018 attachment URL returned by the official content API. Record its URL, retrieval time, HTTP response, byte size, and SHA-256 before opening it. Preserve the source unchanged.
2. Without exposing formula bodies or numeric values, count worksheet XML `<f>` elements and record their total per sheet; separately count other formula-bearing parts and external-link/VBA parts. Read no labels and do not identify the reported erroneous cells.
3. If the published `.xlsx` contains zero worksheet formulas, stop: it is a values-only/ non-formula publication for this model's input purposes, regardless of how the original statistics were computed. Do not run the model or fetch later workbooks for accuracy scoring. Keep the event as an official error lead, not a qualified error workbook.
4. If formulas exist, stop this audit after the inventory. Before any inference, register the original version's pre-correction provenance, complete input/implementation locks, prediction-first ordering, independent label audit, and handling of the already disclosed correction statement. The current public attachment's publication year alone does not prove it is the unrepaired original.
5. A changed percentage is not itself a formula-level label. Only an available erroneous formula plus independently justified correction and complete version history can qualify the candidate; unresolved cells stay unknown.

## Reporting

Publish only acquisition hashes, formula counts and source-level eligibility decision; workbook content stays in ignored `source_evidence/raw/mod_cadets/`. No model or rule change, accuracy metric, source/family increment or performance claim is permitted by this audit alone.
