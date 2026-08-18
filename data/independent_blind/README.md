# Independent blind-study public area

Only corrupted `.xlsx` workbooks and a public `manifest.csv` belong here.
The public manifest contains exactly `instance_id,workbook`; it must never
contain an error cell, original formula, correct formula, error type, or other
private label. Keep all labels outside the repository until predictions have
been frozen. See `research/INDEPENDENT_BLIND_STUDY_PROTOCOL.md`.

This directory deliberately ships no ready-made cases: using FormulaGuard's
own synthetic generator would defeat the purpose of an independent blind set.
