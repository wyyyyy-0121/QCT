#!/usr/bin/env python3
"""Prepare and summarize isolated native-workbook inventory tasks."""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'source_evidence/enron_info1/private'
AUTHOR = PRIVATE / 'enron/Enron Errors Corpus'
INFO1 = PRIVATE / 'info1/Info1'
INVENTORY = PRIVATE / 'inventories'
CONVERTED = PRIVATE / 'converted'
SCRIPT = ROOT / 'tools/inventory_workbook_uno.py'
BATCH = ROOT / 'tools/batch_runner.py'

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()

def prepare(manifest: Path, scope: Path):
    files = []
    for path in sorted(AUTHOR.rglob('*')):
        if path.is_file() and path.suffix.lower() in ('.xls', '.xlsx', '.xlsm'):
            files.append(('enron_author', path))
    for path in sorted((INFO1 / 'spreadsheets').rglob('*')):
        if path.is_file() and path.suffix.lower() in ('.xls', '.xlsx', '.xlsm'):
            files.append(('info1', path))
    INVENTORY.mkdir(parents=True, exist_ok=True)
    CONVERTED.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    catalog = []
    for source, path in files:
        digest = sha(path)
        task_id = f'{source}_{digest[:20]}'
        inv = INVENTORY / f'{task_id}.json'
        xlsx = CONVERTED / f'{task_id}.xlsx'
        catalog.append({'source': source, 'relative_path': str(path.relative_to(PRIVATE)),
                        'source_sha256': digest, 'task_id': task_id,
                        'inventory': str(inv), 'converted_copy': str(xlsx)})
        if inv.exists() and xlsx.exists():
            continue
        rows.append({'id': task_id, 'argv': ['/usr/bin/python3', str(SCRIPT), '--input',
                      str(path), '--output', str(inv), '--xlsx', str(xlsx)],
                     'timeout_seconds': 180, 'outputs': [str(inv), str(xlsx)]})
    manifest.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    scope.write_text(json.dumps({'schema': 'enron-info1-inventory-scope-v1',
        'workbook_count': len(catalog), 'pending_count': len(rows),
        'author_archive_file_count': sum(x['source'] == 'enron_author' for x in catalog),
        'info1_workbook_file_count': sum(x['source'] == 'info1' for x in catalog),
        'workbooks': catalog}, indent=2) + '\n')
    print(json.dumps({'workbooks': len(catalog), 'pending': len(rows), 'manifest': str(manifest)}))

def read_props(path: Path):
    result = {}
    for line in path.read_text(encoding='latin1').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        result[key.strip()] = value.strip()
    labels = []
    for key, value in result.items():
        if re.fullmatch(r'FAULTY_CELLS_\d+', key):
            for item in value.split(';'):
                parts = item.strip().split('!')
                if len(parts) != 3:
                    labels.append({'raw': item, 'status': 'malformed'})
                    continue
                idx, col, row = parts
                labels.append({'sheet_index': int(idx), 'column': col, 'row': int(row),
                               'status': 'pending'})
    return result, labels

def xl_col(value):
    if not re.fullmatch(r'[A-Z]+', value):
        raise ValueError(f'Invalid annotated Excel column: {value!r}')
    return value

def summarize(scope_path: Path, result_path: Path):
    scope = json.loads(scope_path.read_text())
    inventory_by_hash = {}
    formula_total = {'enron_author': 0, 'info1': 0}
    conversion_differences = {'enron_author': 0, 'info1': 0}
    workbooks_with_diff = {'enron_author': 0, 'info1': 0}
    source_hash_mismatches = []
    missing_inventories = []
    missing_converted_copies = []
    roundtrip_equal = {'enron_author': 0, 'info1': 0}
    for item in scope['workbooks']:
        source_path = PRIVATE / item['relative_path']
        if not source_path.is_file() or sha(source_path) != item['source_sha256']:
            source_hash_mismatches.append(item['task_id'])
        inv_path = Path(item['inventory'])
        if not inv_path.exists():
            missing_inventories.append(item['task_id'])
            continue
        inv = json.loads(inv_path.read_text())
        if inv.get('input_sha256') != item['source_sha256']:
            source_hash_mismatches.append(item['task_id'] + ':inventory')
        if not Path(item['converted_copy']).is_file():
            missing_converted_copies.append(item['task_id'])
        inventory_by_hash[item['source_sha256']] = inv
        formulas = sum(c['type'] == 'FORMULA' for s in inv['native_sheets'] for c in s['cells'].values())
        formula_total[item['source']] += formulas
        diffs = len(inv['roundtrip_differences'])
        conversion_differences[item['source']] += diffs
        workbooks_with_diff[item['source']] += diffs > 0
        roundtrip_equal[item['source']] += bool(inv.get('roundtrip_content_equal'))
    info1_stats = {'properties_files': 0, 'labeled_cells': 0,
                   'label_formula': 0, 'label_value': 0, 'label_blank_or_missing': 0,
                   'label_ambiguous_or_unmapped_sheet': 0}
    info1_workbooks = []
    student_groups = collections.defaultdict(list)
    formula_layout_groups = collections.defaultdict(list)
    full_content_groups = collections.defaultdict(list)
    for prop in sorted((INFO1 / 'configuration_files').rglob('*.properties')):
        config, labels = read_props(prop)
        workbook_ref = config.get('EXCEL_SHEET', '')
        target = (prop.parent / workbook_ref.replace('\\', '/')).resolve()
        info1_stats['properties_files'] += 1
        info1_stats['labeled_cells'] += len(labels)
        key = str(prop.relative_to(INFO1))
        student_id = prop.parent.name + '/' + prop.stem.split('_')[0]
        student_groups[student_id].append(key)
        detail = {'configuration': key, 'student_group': student_id,
                  'labeled_cells': len(labels), 'formula_labels': 0,
                  'constant_labels': 0, 'blank_labels': 0, 'unmapped_labels': 0}
        info1_workbooks.append(detail)
        if not target.is_file():
            info1_stats['label_ambiguous_or_unmapped_sheet'] += len(labels)
            detail['unmapped_labels'] = len(labels)
            continue
        digest = sha(target)
        inv = inventory_by_hash.get(digest)
        if not inv:
            info1_stats['label_ambiguous_or_unmapped_sheet'] += len(labels)
            detail['unmapped_labels'] = len(labels)
            continue
        full_content_groups[inv['content_projection_sha256']].append(key)
        layout = [{'name': s['name'], 'cells': {a: c['type']
                   for a, c in s['cells'].items()}} for s in inv['native_sheets']]
        fingerprint = hashlib.sha256(json.dumps(layout, sort_keys=True).encode()).hexdigest()
        formula_layout_groups[fingerprint].append(key)
        detail.update(source_sha256=digest, layout_fingerprint=fingerprint,
                      full_content_fingerprint=inv['content_projection_sha256'])
        for label in labels:
            if label.get('status') == 'malformed' or label['sheet_index'] >= len(inv['native_sheets']):
                info1_stats['label_ambiguous_or_unmapped_sheet'] += 1
                detail['unmapped_labels'] += 1
                continue
            sheet = inv['native_sheets'][label['sheet_index']]
            addr = f"{xl_col(label['column'])}{label['row']}"
            cell = sheet['cells'].get(addr)
            if cell is None:
                info1_stats['label_blank_or_missing'] += 1
                detail['blank_labels'] += 1
            elif cell['type'] == 'FORMULA':
                info1_stats['label_formula'] += 1
                detail['formula_labels'] += 1
            else:
                info1_stats['label_value'] += 1
                detail['constant_labels'] += 1
    result = {'schema': 'enron-info1-native-inventory-summary-v1',
              'scope_workbooks': scope['workbook_count'],
              'inventories_complete': len(inventory_by_hash),
              'formula_cells_by_source': formula_total,
              'roundtrip_cell_content_differences_by_source': conversion_differences,
              'workbooks_with_roundtrip_differences_by_source': workbooks_with_diff,
              'roundtrip_content_equal_workbooks_by_source': roundtrip_equal,
              'integrity_checks': {'source_hash_mismatch_count': len(source_hash_mismatches),
                  'source_hash_mismatches': source_hash_mismatches,
                  'missing_inventories': missing_inventories,
                  'missing_converted_copies': missing_converted_copies},
              'info1_labels': info1_stats,
              'info1_grouping': {'course_student_groups': len(student_groups),
                  'students_with_multiple_versions': sum(len(v) > 1 for v in student_groups.values()),
                  'max_versions_per_student': max(map(len, student_groups.values())),
                  'exact_cell_type_layout_groups': len(formula_layout_groups),
                  'exact_full_content_groups': len(full_content_groups),
                  'note': 'Fingerprints and student ids give minimum grouping constraints, not independent template-family counts'},
              'source_pair_status': 'not scored here; corrected-cell pairs must be mapped separately'}
    (PRIVATE / 'INFO1_WORKBOOK_DETAILS.json').write_text(
        json.dumps(info1_workbooks, indent=2) + '\n')
    result_path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'info1_workbooks'}, indent=2))

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('prepare')
    a.add_argument('--manifest', type=Path, default=PRIVATE / 'inventory_tasks.jsonl')
    a.add_argument('--scope', type=Path, default=PRIVATE / 'inventory_scope.json')
    b = sub.add_parser('summarize')
    b.add_argument('--scope', type=Path, default=PRIVATE / 'inventory_scope.json')
    b.add_argument('--output', type=Path, default=ROOT / 'source_evidence/enron_info1/INVENTORY_SUMMARY.json')
    args = p.parse_args()
    if args.command == 'prepare':
        prepare(args.manifest, args.scope)
    else:
        summarize(args.scope, args.output)

if __name__ == '__main__':
    main()
