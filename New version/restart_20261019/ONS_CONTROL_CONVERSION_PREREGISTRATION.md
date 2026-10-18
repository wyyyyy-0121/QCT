# ONS clean-control conversion audit preregistration

Date: 2026-10-19

## Purpose and scope

This is a read-only source-format audit for the UK Office for National Statistics (ONS) GERD and BERD revisions spreadsheets. These are candidate clean controls only. ONS describes them as comparisons between first-published and revised statistical values; that does not label any formula as erroneous. They contribute zero natural-error sources and zero natural-error template families.

No HybridGuard, dev11, candidate rule, or scoring code will run in this audit. No model or threshold changes are authorized by its outcome. Source contents already inspected in the earlier 2026-10-19 screening are disclosed; this is not blind evidence.

## Inputs and acquisition boundary

- GERD current `.xls` from the official ONS page.
- GERD previous-version `.xls` only from the official `Previous versions` link.
- BERD current `.xls` from the official ONS page.
- Record the exact page and file URLs, retrieval timestamp, HTTP status, byte size, media type, and SHA-256 before opening workbook contents.
- Keep source binaries and converted files under ignored `source_evidence/raw/ons_control/`; do not commit workbook contents.

## Fixed audit procedure

1. Preserve each downloaded `.xls` unchanged and verify its hash before/after conversion.
2. Convert each input once with the installed LibreOffice headless Calc engine to `.xlsx`; record tool version, command, exit status, and logs.
3. Inventory sheet names/order/visibility, dimensions, formula cells and exact formula text, cached formula results when available, non-empty values, merged regions, and defined names in the `.xlsx` output.
4. Re-open each converted `.xlsx` in LibreOffice without saving and export a second normalized copy. Compare formula addresses/text and formula result values across the first and second conversions. Do not treat two conversions by the same engine as independent proof of original `.xls` fidelity.
5. For the GERD current/history pair, compare shared formula addresses and text; record additions/removals and non-formula changes separately. Do not label revisions as errors.
6. Check workbook-level metadata for external links, macros, hidden sheets, and unsupported objects that may be lost by conversion.

## Acceptance and stop conditions

- Conversion is accepted only as an operational input-format check if every formula survives both opens with identical addresses and text, formula results remain stable, and no unexplained sheet/formula loss occurs.
- This procedure cannot certify original `.xls` formula fidelity unless an independent parser/engine can expose the original BIFF formulas or a trusted source-level formula manifest. If that evidence is unavailable, report `inconclusive` and do not run the model on converted files.
- Any formula or result change, conversion warning, damaged object, or source hash change stops control use until independently resolved.
- A separate control-test preregistration is required before any model inference. It must freeze the workbook versions, input hashes, whole-workbook false-positive denominator, unsupported/failure handling, 1/8 worker comparison, and resource metrics.

## Required reporting

Publish a concise audit report with source and output hashes, conversion-tool version, per-workbook formula and result counts, differences, limits, and one of `operationally accepted`, `inconclusive`, or `rejected`. No accuracy claim is permitted from this conversion audit.
