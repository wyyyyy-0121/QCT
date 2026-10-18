#!/usr/bin/env python3
"""Read-only BIFF/OOXML audit; no model import or formula normalization.

Requires openpyxl and xlrd==2.0.1. Use PYTHONPATH for an isolated xlrd install.
Existing outputs are never overwritten. Workbook content stays in the raw folder.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct

from openpyxl import load_workbook
import xlrd
from xlrd.formula import FMLA_TYPE_CELL, decompile_formula


SOURCE_HASHES = {
    'GERD_current': 'cd6b52f66254ce2b41248bbb1a0d3c934ee2001cf1bcd51b937340bef6bbe87e',
    'GERD_previous_v1': 'fe2eaa8bbc7a54462e2ef562d8aa1f9b697cbed3ab15eb744d33c78cdc208294',
    'BERD_current': '44c87345720921b7bec6c8294dfd976347d3e50823ab969a06a59101473af742',
}
FILE_PATHS = {
    'GERD_current': 'revisionsspreadsheetforannualdatagerd/current/prtrevisionstable2014.xls',
    'GERD_previous_v1': 'revisionsspreadsheetforannualdatagerd/current/previous/v1/revisionsspreadsheet_tcm77-398550.xls',
    'BERD_current': 'revisionsspreadsheetforannualdataberd/current/rftrevisionsspreadsheet2013_tcm77-385800.xls',
}
ONS_BASE = 'https://www.ons.gov.uk/economy/governmentpublicsectorandtaxes/researchanddevelopmentexpenditure/datasets/'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(path):
    formulas_book = load_workbook(path, data_only=False)
    values_book = load_workbook(path, data_only=True)
    result = {'sheets': [], 'formulas': {}, 'cached': {}, 'non_formula': {},
              'defined_names': sorted(formulas_book.defined_names),
              'external_links': len(formulas_book._external_links)}
    for sheet in formulas_book:
        result['sheets'].append({
            'name': sheet.title, 'visibility': sheet.sheet_state,
            'dimensions': sheet.calculate_dimension(),
            'merged': sorted(map(str, sheet.merged_cells.ranges)),
        })
        for row in sheet:
            for cell in row:
                key = f'{sheet.title}!{cell.coordinate}'
                if cell.data_type == 'f':
                    if not isinstance(cell.value, str):
                        raise ValueError('Array/shared formula requires separate audit')
                    result['formulas'][key] = cell.value
                    result['cached'][key] = values_book[sheet.title][cell.coordinate].value
                elif cell.value is not None:
                    result['non_formula'][key] = str(cell.value)
    formulas_book.close()
    values_book.close()
    return result


def original_inventory(path):
    book = xlrd.open_workbook(path, on_demand=True, formatting_info=True)
    if book.biff_version != 80:
        raise ValueError('Only the locked BIFF8 inputs are supported')
    sheets = book.sheets()
    result = {'formulas': {}, 'cached': {}, 'errors': [], 'sheets': []}
    for sheet, start in zip(sheets, book._sh_abs_posn):
        result['sheets'].append({'name': sheet.name, 'visibility': sheet.visibility,
                                'rows': sheet.nrows, 'columns': sheet.ncols})
        position = start
        reached_eof = False
        while position + 4 <= len(book.mem):
            opcode, size = struct.unpack_from('<HH', book.mem, position)
            end = position + 4 + size
            if end > len(book.mem):
                raise ValueError('Truncated BIFF record')
            data = book.mem[position + 4:end]
            position = end
            if opcode == 0x000A:
                reached_eof = True
                break
            if opcode not in (0x0006, 0x0206, 0x0406):
                continue
            row, column = struct.unpack_from('<HH', data)
            address = xlrd.formula.colname(column) + str(row + 1)
            key = f'{sheet.name}!{address}'
            length = struct.unpack_from('<H', data, 20)[0]
            result['cached'][key] = sheet.cell_value(row, column)
            try:
                text = decompile_formula(book, data[22:], length, FMLA_TYPE_CELL,
                                         browx=row, bcolx=column)
                if text is None:
                    raise ValueError('Formula decompiler returned no expression')
                result['formulas'][key] = '=' + text
            except Exception as error:
                result['formulas'][key] = None
                result['errors'].append({'cell': key, 'error': repr(error)})
        if not reached_eof:
            raise ValueError('Missing BIFF worksheet EOF')
    book.release_resources()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    private_output = args.raw_dir / 'inventory.local.json'
    if args.output.exists() or private_output.exists():
        raise SystemExit('Preserve existing audit outputs; choose a new audit directory')
    report = {'created_utc': datetime.now(timezone.utc).isoformat(),
              'parser_version': xlrd.__version__,
              'model_runs': 0, 'accepted_natural_sources': 0,
              'accepted_final_families': 0, 'workbooks': [],
              'decision': 'inconclusive', 'control_inference_permitted': False,
              'limits': [
                  'BIFF decompilation spelling is not original author text.',
                  'No semantic normalization or business correctness certification.',
                  'Original cache versus Calc differences trigger preregistered stop.',
                  'No concurrency/performance claim from this serial format audit.',
              ]}
    local = {}
    for name, expected_hash in SOURCE_HASHES.items():
        source = args.raw_dir / f'{name}.xls'
        first_path = args.raw_dir / 'converted1' / f'{name}.xlsx'
        second_path = args.raw_dir / 'converted2' / f'{name}.xlsx'
        if sha(source) != expected_hash:
            raise ValueError(f'Source hash mismatch: {name}')
        first, second = inventory(first_path), inventory(second_path)
        original = original_inventory(source)
        keys = set(original['formulas']) | set(first['formulas'])
        address_difference = sorted(set(original['formulas']) ^ set(first['formulas']))
        spelling_difference = [key for key in sorted(keys)
                               if original['formulas'].get(key) != first['formulas'].get(key)]
        cache_difference = []
        for key in sorted(keys):
            before, after = original['cached'].get(key), first['cached'].get(key)
            if before != after:
                difference = {'cell': key, 'original_cache': before, 'calc_cache': after}
                if isinstance(before, (int, float)) and isinstance(after, (int, float)):
                    difference['absolute_difference'] = abs(before - after)
                cache_difference.append(difference)
        roundtrip_difference = [field for field in first if first[field] != second[field]]
        if sha(source) != expected_hash:
            raise ValueError(f'Source changed while auditing: {name}')
        report['workbooks'].append({
            'name': name, 'source_sha256': expected_hash, 'source_bytes': source.stat().st_size,
            'source_file_url': 'https://www.ons.gov.uk/file?uri=' + ONS_BASE.split('www.ons.gov.uk')[1] + FILE_PATHS[name],
            'local_source_mtime_utc': datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat(),
            'first_conversion_sha256': sha(first_path), 'second_conversion_sha256': sha(second_path),
            'original_formula_count': len(original['formulas']),
            'converted_formula_count': len(first['formulas']),
            'decompile_errors': original['errors'],
            'formula_address_difference': address_difference,
            'formula_spelling_difference_count': len(spelling_difference),
            'original_cache_exact_match_count': len(keys) - len(cache_difference),
            'original_cache_differences': cache_difference,
            'roundtrip_differing_fields': roundtrip_difference,
            'converted_sheets': first['sheets'],
            'converted_defined_names': first['defined_names'],
            'converted_external_link_count': first['external_links'],
        })
        local[name] = {'original': original, 'first': first, 'second': second,
                       'formula_spelling_differences': spelling_difference}
    current = local['GERD_current']['first']
    previous = local['GERD_previous_v1']['first']
    report['gerd_current_vs_previous'] = {
        'formula_maps_equal': current['formulas'] == previous['formulas'],
        'non_formula_changes': sum(current['non_formula'].get(key) != previous['non_formula'].get(key)
                                   for key in set(current['non_formula']) | set(previous['non_formula'])),
        'note': 'Version differences are not formula-error labels.',
    }
    private_output.write_text(json.dumps(local, indent=2, default=str) + '\n')
    report['private_inventory_sha256'] = sha(private_output)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'decision': report['decision'], 'workbooks': len(local),
                      'model_runs': 0, 'output': str(args.output)}))


if __name__ == '__main__':
    main()
