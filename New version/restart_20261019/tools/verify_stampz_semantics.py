#!/usr/bin/env python3
"""Verify the bounded StampZ semantic observations without creating truth labels."""
from pathlib import Path
import hashlib
import json
import re

import openpyxl
from inspect_stampz_ods import inventory, excel_formula

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'source_evidence/raw/stampz'
OUT = ROOT / 'source_evidence/stampz'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    target = OUT / 'semantic_verification.json'
    if target.exists():
        raise SystemExit('Preserve existing semantic verification')
    lock = json.loads((OUT / 'prediction_lock.json').read_text())
    for relative, digest in lock['files'].items():
        assert sha(ROOT / relative) == digest, relative
    before, after = [inventory(RAW / f'{version}.ods') for version in ('before', 'after')]
    formulas, revised = before['formulas'], after['formulas']
    changed = {key for key in formulas.keys() | revised.keys()
               if formulas.get(key) != revised.get(key)}
    assert changed == {f'Sheet1!Q{row}' for row in range(8, 106)}
    for row in range(8, 106):
        original, correction = formulas[f'Sheet1!Q{row}'], revised[f'Sheet1!Q{row}']
        assert set(re.findall(r'\[\.([A-Z]+)(\d+)\]', original)) == {('B', str(row + 5)), ('C', str(row + 5))}
        assert set(re.findall(r'\[\.([A-Z]+)(\d+)\]', correction)) == {('B', str(row)), ('C', str(row))}
        assert re.sub(r'\[\.([BC])\d+\]', lambda match: f'[.{match[1]}{row}]', original) == correction
        assert set(re.findall(r'\[\.([A-Z]+)(\d+)\]', formulas[f'Sheet1!O{row}'])) == {('A', str(row))}
        assert set(re.findall(r'\[\.([A-Z]+)(\d+)\]', formulas[f'Sheet1!P{row}'])) == {('B', str(row)), ('C', str(row))}
    headers = {'A1': 'Xnorm', 'B1': 'Ynorm', 'C1': 'Znorm', 'Q1': 'Hue (h)'}
    for coordinate, text in headers.items():
        assert before['captions'][f'Sheet1!{coordinate}'] == text
    workbook = openpyxl.load_workbook(RAW / 'before.xlsx', data_only=False)
    converted = {sheet.title + '!' + cell.coordinate: cell.value
                 for sheet in workbook for row in sheet for cell in row if cell.data_type == 'f'}
    assert converted == {key: excel_formula(value) for key, value in formulas.items()}
    cached = openpyxl.load_workbook(RAW / 'before.xlsx', data_only=True)['Sheet1']
    input_nonempty = sum(cached.cell(row, col).value not in (None, '')
                         for row in range(8, 112) for col in range(1, 4))
    q_nonempty = sum(cached.cell(row, 17).value not in (None, '') for row in range(8, 106))
    assert input_nonempty == q_nonempty == 0
    semantic = json.loads((OUT / 'semantic_audit.json').read_text())
    assert semantic['changed_formula_count'] == len(changed)
    assert not semantic['accepted_natural_source_for_admission']
    result = dict(prediction_lock_verified=True, all_315_converted_formulas_match=True,
        changed_cells=len(changed), all_reference_offsets_verified=True,
        neighboring_L_and_C_same_row_verified=True, headers_verified=True,
        original_nonempty_input_cells_A8_C111=input_nonempty,
        original_nonempty_changed_Q_cached_results=q_nonempty,
        semantic_audit_sha256=sha(OUT / 'semantic_audit.json'),
        scorable_natural_errors=0, final_validation_eligible=False,
        note='Structural and empty-input checks support a candidate only; no business truth label was generated.')
    with target.open('x') as handle:
        json.dump(result, handle, indent=2)
        handle.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
