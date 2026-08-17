# External corpus placement

Do not commit or redistribute third-party workbooks until their terms have been checked.

## Enron Error Corpus

1. Download the files and properties labels from the official corpus page.
2. The official archive is kept locally under `data/external/enron/source/`.
   Converted `.xlsx` files go under the Git-ignored
   `data/external/enron/workbooks/converted/` directory.
3. Build a manifest that retains every reviewed fault and every exclusion:

```bat
python scripts\prepare_enron_manifest.py --workbooks data\external\enron\source\spreadsheets --properties data\external\enron\source\configuration_files --converted data\external\enron\workbooks\converted --output data\external\enron\manifest.csv --libreoffice "D:\Apps\libreoffice\program\soffice.exe"
```

For legacy `.xls` files, add `--libreoffice "C:\Program Files\LibreOffice\program\soffice.exe"`. The audit must inventory 36 fault rows before parser exclusions.

The generated manifest follows this core shape:

```csv
instance_id,workbook,source_cell,correct_formula,include,exclusion_reason
enron_001,workbooks/example.xlsx,Sheet1!D17,,1,
enron_002,workbooks/macro_example.xlsm,Sheet1!E20,,0,macro_or_external_link_dependency
```

`correct_formula` may be empty when only the faulty source cell is known. Run:

```powershell
python scripts\run_external_evaluation.py `
  --manifest data\external\enron\manifest.csv `
  --output results\enron
```

The external results must be reported separately from PropagationBench-Synthetic.
The script writes `external_exclusions.csv` and `external_dataset_audit.json`; do not delete excluded rows from the manifest.
