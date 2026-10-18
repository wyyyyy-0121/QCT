#!/usr/bin/env python3
"""Development-only no-VBA packaging with byte-level retained-part verification."""
from pathlib import Path
import copy
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

from acquire_epa_pairs import ROOT, RAW, OUT, sha, save, verify_lock


def export(source, target):
    before_hash = sha(source)
    assert not target.exists()
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        removed = [name for name in names if 'vba' in name.lower()]
        assert removed == ['xl/vbaProject.bin'], removed
        edited = {}
        types = ET.fromstring(archive.read('[Content_Types].xml'))
        main_changed = project_removed = 0
        for item in list(types):
            if item.get('PartName') == '/xl/vbaProject.bin':
                types.remove(item)
                project_removed += 1
            elif item.get('PartName') == '/xl/workbook.xml':
                assert item.get('ContentType') == 'application/vnd.ms-excel.sheet.macroEnabled.main+xml'
                item.set('ContentType', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml')
                main_changed += 1
        assert main_changed == project_removed == 1
        edited['[Content_Types].xml'] = ET.tostring(types, encoding='utf-8', xml_declaration=True)
        relations = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        macro_relationships = [item for item in relations if item.get('Type', '').endswith('/vbaProject')]
        assert len(macro_relationships) == 1 and macro_relationships[0].get('Target') == 'vbaProject.bin'
        relations.remove(macro_relationships[0])
        edited['xl/_rels/workbook.xml.rels'] = ET.tostring(relations, encoding='utf-8', xml_declaration=True)
        with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as result:
            for item in archive.infolist():
                if item.filename not in removed:
                    result.writestr(copy.copy(item), edited.get(item.filename, archive.read(item.filename)))
        with zipfile.ZipFile(target) as result:
            assert set(result.namelist()) == set(names) - set(removed)
            retained = {name: archive.read(name) == result.read(name)
                        for name in result.namelist() if name not in edited}
            assert all(retained.values())
            worksheets = [name for name in retained if name.startswith('xl/worksheets/') and name.endswith('.xml')]
        assert sha(source) == before_hash
    return dict(original_sha256=before_hash, export_sha256=sha(target),
        removed_parts=removed, edited_parts=list(edited),
        byte_identical_retained_parts=len(retained), byte_identical_worksheet_parts=len(worksheets),
        original_unchanged=True, macros_executed=False, macro_behavior_supported=False,
        revisions_already_acquired=True, final_validation_eligible=False)


def main():
    verify_lock()
    directory = RAW / 'xlsx_export'
    directory.mkdir(exist_ok=False)
    receipts, tasks = {}, []
    for name in ('flares', 'oxidizers'):
        target = directory / f'{name}_before.xlsx'
        receipts[name] = export(RAW / f'{name}_before.xlsm', target)
        tasks.append(dict(id=name, argv=[sys.executable, str(ROOT / 'tools/predict_workbook.py'),
            str(target), '--output', 'prediction.json'], outputs=['prediction.json']))
    save(OUT / 'xlsx_export_receipt.json', dict(books=receipts,
        amendment_sha256=sha(ROOT / 'EPA_EXPORT_AMENDMENT.md')))
    manifest = OUT / 'xlsx_manifest.jsonl'
    with manifest.open('x') as handle:
        for task in tasks:
            handle.write(json.dumps(task) + '\n')
    command = [sys.executable, str(ROOT / 'tools/batch_runner.py'), '--manifest', str(manifest),
        '--output-dir', str(RAW / 'xlsx_run'), '--workers', '8', '--worker-memory-mib', '1024', '--timeout', '300']
    run = subprocess.run(command, capture_output=True, text=True, timeout=360)
    save(OUT / 'xlsx_batch_invocation.json', dict(argv=command, returncode=run.returncode,
        stdout=run.stdout, stderr=run.stderr, revisions_already_acquired=True))
    runtime = RAW / 'xlsx_run/runtime.json'
    if runtime.exists():
        save(OUT / 'xlsx_runtime.json', json.loads(runtime.read_text()))
    files = [path for path in (RAW / 'xlsx_run').rglob('*') if path.is_file()]
    files += list(directory.glob('*.xlsx'))
    files += [OUT / 'xlsx_export_receipt.json', OUT / 'xlsx_runtime.json', OUT / 'xlsx_batch_invocation.json']
    save(OUT / 'xlsx_prediction_lock.json', dict(
        files={str(path.relative_to(ROOT)): sha(path) for path in files if path.exists()},
        revisions_already_acquired=True, final_validation_eligible=False))
    print(json.dumps(dict(exports=receipts, returncode=run.returncode,
                          stdout=run.stdout, stderr=run.stderr), indent=2))


if __name__ == '__main__':
    main()
