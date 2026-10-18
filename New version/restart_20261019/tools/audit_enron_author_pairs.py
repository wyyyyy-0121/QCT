#!/usr/bin/env python3
"""Map all 36 author-described Enron events; do not infer truth from any diff."""
from __future__ import annotations
import collections
import hashlib
import json
import re
from pathlib import Path
import openpyxl
from openpyxl.utils.cell import range_boundaries, get_column_letter

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OUT = ROOT / 'source_evidence/enron_info1'
PRIVATE = OUT / 'private'
AUTHOR = PRIVATE / 'enron/Enron Errors Corpus'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def addresses(text):
    result = []
    for part in str(text).split(';'):
        part = part.strip()
        if not re.fullmatch(r'[A-Z]+\d+(?::[A-Z]+\d+)?', part):
            raise ValueError('Ambiguous author range: ' + str(text))
        c1, r1, c2, r2 = range_boundaries(part)
        for row in range(r1, r2 + 1):
            for col in range(c1, c2 + 1):
                result.append(get_column_letter(col) + str(row))
    return result

def main():
    scope = json.loads((PRIVATE / 'inventory_scope.json').read_text())
    inv_by_hash = {}
    for item in scope['workbooks']:
        if item['source'] == 'enron_author' and Path(item['inventory']).is_file():
            inv_by_hash[item['source_sha256']] = json.loads(Path(item['inventory']).read_text())
    table = openpyxl.load_workbook(AUTHOR / 'Enron-Errors.xlsx', read_only=True, data_only=True).active
    events = []
    details = []
    for values in table.iter_rows(min_row=6, values_only=True):
        if not isinstance(values[0], int):
            continue
        num, bookno, badfile, badsheet, badrange, goodfile, goodsheet, goodrange = values[:8]
        row = {'event': num, 'spreadsheet_number': bookno, 'author_faulty_file': badfile,
               'author_corrected_file': goodfile, 'faulty_sheet': badsheet, 'faulty_range': badrange,
               'corrected_sheet': goodsheet, 'corrected_range': goodrange,
               'cell_type': values[10], 'author_change': values[11], 'description': values[12],
               'final_validation_eligible': False, 'certified_repair_truth': False,
               'reason_not_certified': 'Author version pair alone is not source-cell business verification'}
        directory = AUTHOR / str(bookno)
        if badfile:
            native = directory / badfile
            row['faulty_file_exists'] = native.is_file()
            if native.is_file():
                row['faulty_sha256'] = sha(native)
                legacy = REPO / f'data/external/enron/source/spreadsheets/{bookno:02d}.xls'
                row['legacy_original_exists'] = legacy.exists()
                row['legacy_original_byte_match'] = legacy.is_file() and sha(legacy) == row['faulty_sha256']
        if not badfile or not goodfile:
            row['status'] = 'missing_faulty_or_corrected_version'
            events.append(row)
            continue
        original, corrected = directory / badfile, directory / goodfile
        if not original.is_file() or not corrected.is_file():
            row['status'] = 'author_filename_not_found'
            events.append(row)
            continue
        bad = inv_by_hash.get(sha(original))
        good = inv_by_hash.get(sha(corrected))
        if not bad or not good:
            row['status'] = 'inventory_missing_or_failed'
            events.append(row)
            continue
        row['corrected_sha256'] = sha(corrected)
        row['roundtrip_original_equal'] = bad['roundtrip_content_equal']
        row['roundtrip_corrected_equal'] = good['roundtrip_content_equal']
        b_s = {s['name']: s['cells'] for s in bad['native_sheets']}
        g_s = {s['name']: s['cells'] for s in good['native_sheets']}
        if badsheet not in b_s or goodsheet not in g_s:
            row['status'] = 'sheet_mapping_needs_manual_review'
            events.append(row)
            continue
        try:
            b_addrs, g_addrs = addresses(badrange), addresses(goodrange)
        except ValueError as error:
            row['status'] = 'range_mapping_needs_manual_review'
            row['mapping_error'] = str(error)
            events.append(row)
            continue
        if len(b_addrs) != len(g_addrs):
            row['status'] = 'range_cardinality_mismatch'
            events.append(row)
            continue
        observed = []
        for a, b in zip(b_addrs, g_addrs):
            before, after = b_s[badsheet].get(a), g_s[goodsheet].get(b)
            observed.append({'event': num, 'faulty_cell': a, 'corrected_cell': b,
                             'before': before, 'after': after})
        details.extend(observed)
        row['mapped_cells'] = len(observed)
        row['original_formula_cells'] = sum(x['before'] is not None and x['before']['type'] == 'FORMULA' for x in observed)
        row['changed_formula_to_formula_cells'] = sum(
            x['before'] is not None and x['after'] is not None and
            x['before']['type'] == x['after']['type'] == 'FORMULA' and
            x['before']['formula'] != x['after']['formula'] for x in observed)
        row['original_formula_to_blank_cells'] = sum(x['before'] is not None and
            x['before']['type'] == 'FORMULA' and x['after'] is None for x in observed)
        row['original_formula_to_constant_cells'] = sum(x['before'] is not None and x['after'] is not None and
            x['before']['type'] == 'FORMULA' and x['after']['type'] != 'FORMULA' for x in observed)
        row['mapped_addresses_identical'] = b_addrs == g_addrs
        # Count all non-formula differences by matching sheet name; this flags confounding.
        input_changes = formula_changes = 0
        for name in b_s.keys() & g_s.keys():
            for addr in b_s[name].keys() | g_s[name].keys():
                x, y = b_s[name].get(addr), g_s[name].get(addr)
                fx, fy = x and x['type'] == 'FORMULA', y and y['type'] == 'FORMULA'
                sx = (x['type'], x['formula']) if x else None
                sy = (y['type'], y['formula']) if y else None
                if sx != sy:
                    if fx or fy:
                        formula_changes += 1
                    else:
                        input_changes += 1
        row['same_sheet_name_formula_differences'] = formula_changes
        row['same_sheet_name_nonformula_differences'] = input_changes
        row['sheet_names_identical'] = list(b_s) == list(g_s)
        row['status'] = ('formula_pair_candidate' if row['changed_formula_to_formula_cells']
                         else 'no_changed_formula_pair_in_mapped_cells')
        events.append(row)
    assert len(events) == 36, len(events)
    # Third party formulas/values stay private. Public evidence contains counts and hashes only.
    (PRIVATE / 'ENRON_PAIR_CELL_DETAILS.json').write_text(json.dumps(details, ensure_ascii=False, indent=2) + '\n')
    payload = {'schema': 'enron-author-event-pair-audit-v1', 'event_count': len(events),
               'status_counts': dict(collections.Counter(e['status'] for e in events)),
               'mapped_changed_formula_pairs': sum(e.get('changed_formula_to_formula_cells', 0) for e in events),
               'certified_repair_truth_cells': 0, 'eligible_final_sources': 0,
               'note': 'Candidate cell counts are not an accuracy denominator; all events retained.',
               'events': events}
    (OUT / 'ENRON_AUTHOR_PAIR_AUDIT.json').write_text(json.dumps(payload, indent=2) + '\n')
    print(json.dumps({k:v for k,v in payload.items() if k != 'events'}, indent=2))

if __name__ == '__main__':
    main()
