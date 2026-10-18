#!/usr/bin/env python3
"""Post-lock EPA inventory using independent OOXML and openpyxl formula reads."""
from pathlib import Path
import collections
import datetime
import gzip
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT.parent / 'followup_20261014'
sys.path[:0] = [str(LEGACY / 'qa'), str(LEGACY / 'scripts'),
               str(LEGACY / 'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from diff_hobyah_natural_dev26 import snapshot
from acquire_epa_pairs import RAW, OUT, sha, save, verify_lock
import openpyxl


def layout(path):
    workbook = openpyxl.load_workbook(path, data_only=False)
    return {sheet.title: dict(state=sheet.sheet_state, max_row=sheet.max_row,
        max_column=sheet.max_column, merged_ranges=sorted(str(r) for r in sheet.merged_cells.ranges),
        hidden_rows=[r for r, d in sheet.row_dimensions.items() if d.hidden],
        hidden_columns=[c for c, d in sheet.column_dimensions.items() if d.hidden]) for sheet in workbook}


def json_scalar(value):
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return {'scalar_type': type(value).__name__, 'iso_value': value.isoformat()}
    raise TypeError(type(value).__name__)


def main():
    verify_lock()
    lock_path = OUT / 'xlsx_prediction_lock.json'
    lock = json.loads(lock_path.read_text())
    for relative, digest in lock['files'].items():
        assert sha(ROOT / relative) == digest
    summary = {}
    for name in ('flares', 'oxidizers'):
        for version in ('before', 'after'):
            receipt = json.loads((OUT / f'{name}_{version}_acquisition.json').read_text())
            assert receipt['ok'] and sha(RAW / f'{name}_{version}.xlsm') == receipt['sha256']
        before, after = [snapshot(RAW / f'{name}_{stage}.xlsm') for stage in ('before', 'after')]
        changes = []
        for key in sorted(before['values'].keys() | after['values'].keys()):
            old, new = before['values'].get(key), after['values'].get(key)
            if old != new:
                kind = ('formula_changed' if key in before['formulas'] and key in after['formulas']
                    else 'formula_removed' if key in before['formulas']
                    else 'formula_added' if key in after['formulas'] else 'nonformula_changed')
                changes.append(dict(cell=key, before=old, after=new, kind=kind))
        before_layout, after_layout = [layout(RAW / f'{name}_{stage}.xlsm') for stage in ('before', 'after')]
        local = RAW / f'{name}_pair_inventory.local.json.gz'
        with gzip.open(local, 'xt') as handle:
            json.dump(dict(before=before, after=after, changes=changes,
                before_layout=before_layout, after_layout=after_layout), handle, default=json_scalar)
        prediction = json.loads((RAW / f'xlsx_run/tasks/{name}/prediction.json').read_text())
        proposals = {model: [row for row in prediction[model]['rows'] if row.get('suggested_formula')
            and row['suggested_formula'] != prediction['observed_formulas'][row['cell']]]
            for model in ('paper', 'dev11')}
        summary[name] = dict(before_formula_cells=len(before['formulas']),
            after_formula_cells=len(after['formulas']), before_sheets=before['sheets'], after_sheets=after['sheets'],
            dual_parser_formula_inventory_agrees=True, before_layout=before_layout, after_layout=after_layout,
            change_counts=dict(collections.Counter(row['kind'] for row in changes)),
            formula_change_cells=[row['cell'] for row in changes if row['kind'].startswith('formula_')],
            proposals={model: len(rows) for model, rows in proposals.items()},
            local_diff_sha256=sha(local), certified_natural_errors=0,
            revisions_acquired_before_xlsx_prediction=True,
            truth_status='pending independent semantics and version alignment; differences are not labels',
            precision=None, coverage=None, final_validation_eligible=False)
    save(OUT / 'pair_inventory_summary.json', dict(books=summary,
        xlsx_prediction_lock_sha256=sha(lock_path), auditor_sha256=sha(Path(__file__)),
        accepted_natural_sources=0, final_validation_eligible=False))
    for name, result in summary.items():
        print(json.dumps(dict(name=name, **{key: value for key, value in result.items()
            if key not in ('formula_change_cells', 'before_layout', 'after_layout')}), indent=2))


if __name__ == '__main__':
    main()
