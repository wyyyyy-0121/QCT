# V4 / V5.2 independent-study public area

This directory is intentionally label-free.  The independent producer places
exactly 15 corrupted `.xlsx` workbooks under `workbooks/` and copies
`manifest.template.csv` to `manifest.csv`.

`manifest.csv` must contain exactly `instance_id,workbook`.  Error cells,
correct formulas, error types, original workbooks, exceptions, and notes stay
outside the repository under `D:\FormulaGuard_Blind_Labels` until the joint
prediction lock has succeeded.

Do not reuse `data/blind_v4`: its labels have already been revealed.
