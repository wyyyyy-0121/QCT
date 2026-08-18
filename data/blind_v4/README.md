# V4 independent blind data drop

This directory is for label-free workbooks only. Copy
`blind_manifest_template.csv` to `blind_manifest.csv`, then add one row per
independent event, for example:

```csv
instance_id,workbook
blind_001,workbooks/blind_001.xlsx
blind_002,workbooks/blind_002.xlsx
```

Requirements:

- use a distinct workbook for every event;
- do not include source cells, correct formulas, error types, or revealing file names;
- keep the label file outside the repository until predictions are hash-locked;
- target at least 15 events for a quantitative comparison; 6--12 events are
  reported only as an exploratory case study;
- retain provenance, usage permission, injector identity, and injection date in
  the external label ledger for later disclosure.

Place `.xlsx` files under `workbooks/`. Git ignores that directory so private or
third-party spreadsheets are not committed accidentally.
