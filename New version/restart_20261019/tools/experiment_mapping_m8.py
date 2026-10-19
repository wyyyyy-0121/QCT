#!/usr/bin/env python3
"""Prepare/run locked static-mapping experiment; preserve historical M7 inputs."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

from openpyxl import load_workbook

from metadata_mapping_m8 import snapshot
from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, RUNNER, verify_frozen
from spreadsheetbench2_scoring import sha256, verify_prediction_lock

EXPERIMENT = EVIDENCE / 'model_m8_mapping'
M7 = EVIDENCE / 'model_m7_source'
EPA = EVIDENCE.parent / 'epa_pairs/xlsx_export/oxidizers_before.xlsx'
STANDARD = 'Inlet volumetric flow rate(Qwi) at 77oF and 1 atm.'
ACTUAL = 'Inlet volumetric flow rate(Qwi) (actual conditions)'


def write(path, data):
    with path.open('x') as handle:
        json.dump(data, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write('\n')


def verify_files(lock):
    for name, expected in lock['files_sha256'].items():
        if sha256(Path(name)) != expected:
            raise SystemExit('M8 input changed: ' + name)


def verify_context():
    original, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    if sys.executable != original['runtime_executable']:
        raise SystemExit('Use locked interpreter')
    m7_lock = json.loads((M7 / 'input_lock.json').read_text())
    verify_files(m7_lock)
    return inputs


def prepare():
    verify_context()
    EXPERIMENT.mkdir(exist_ok=False)
    for directory in ('requests', 'metadata', 'workbooks', 'scoring'):
        (EXPERIMENT / directory).mkdir()
    variants = {'original': EPA, 'fault_ratio': M7 / 'workbooks/injected_ratio.xlsx',
                'fault_adjusted': M7 / 'workbooks/injected_adjusted.xlsx'}
    for name in ('static_units', 'duplicate', 'moved_value'):
        book = load_workbook(EPA)
        sheet = book['Data Inputs']
        if name == 'static_units':
            sheet['C23'], sheet['C24'] = 'scfm', 'acfm'
        elif name == 'duplicate':
            sheet['A60'], sheet['B60'], sheet['C60'] = sheet['A22'].value, 8000, 'hours/year'
        else:
            sheet['D22'], sheet['B22'] = sheet['B22'].value, None
        path = EXPERIMENT / 'workbooks' / (name + '.xlsx')
        book.save(path)
        book.close()
        variants[name] = path
    files, metadata = list(variants.values()), {}
    for name, path in variants.items():
        target = EXPERIMENT / 'metadata' / (name + '.json')
        write(target, snapshot(path))
        metadata[name] = target
        files.append(target)
    if not (sha256(metadata['original']) == sha256(metadata['fault_ratio']) == sha256(metadata['fault_adjusted'])):
        raise SystemExit('Formula-only changes altered metadata; preserve diagnostic and stop')
    rows, expected = [], {}

    def add(name, variant, query=None, reference=None, reason=None, pipeline=None, kind='real_mapping_query'):
        workbook = variants[variant]
        request = dict(mode='map', workbook=str(workbook), workbook_sha256=sha256(workbook),
                       metadata=str(metadata[variant]), metadata_sha256=sha256(metadata[variant]), query=query)
        if pipeline is not None:
            request.update(deepcopy(pipeline))
            request['mode'] = 'repair'
            request.pop('query')
            request.pop('references')
            request['fields'] = {row['symbol']: dict(term=row['text'], unit='ppmv', sheet=request['sheet'])
                                 for row in request['aliases']}
        path = EXPERIMENT / 'requests' / (name + '.json')
        write(path, request)
        files.append(path)
        rows.append(dict(id=name, argv=[sys.executable, str(ROOT / 'tools/metadata_mapping_m8.py'), str(path),
                                       '--output', 'prediction.json'], outputs=['prediction.json'], timeout_seconds=120))
        expected[name] = dict(kind=kind, reference=reference,
                              status='abstain' if pipeline is not None else ('mapped' if reference else 'unresolved'),
                              reason='field_mapping_incomplete' if pipeline is not None else (reason or 'unique_structural_match'),
                              is_fault=variant.startswith('fault_') and pipeline is not None)

    scope = {'sheet': 'Data Inputs'}
    add('qwi_ambiguous', 'original', dict(scope, term='Qwi'), reason='ambiguous_fields')
    add('qwi_dynamic_units', 'original', dict(scope, term='Qwi', unit='scfm'), reason='unit_not_statically_verified')
    add('qualified_standard', 'original', dict(scope, term=STANDARD), dict(sheet='Data Inputs', cell='B23'))
    add('qualified_actual', 'original', dict(scope, term=ACTUAL), dict(sheet='Data Inputs', cell='B24'))
    add('tfi_global', 'original', dict(term='Tfi'), reason='ambiguous_fields')
    hours = dict(scope, term='Number of operating hours/year', unit='hours/year')
    add('hours', 'original', hours, dict(sheet='Data Inputs', cell='B22'))
    add('catalyst_cost', 'original', dict(scope, term='CC', unit='$/ft3'), dict(sheet='Data Inputs', cell='B34'))
    add('missing_field', 'original', dict(scope, term='Missing flow'), reason='no_structural_field_match')
    add('qwi_static_standard', 'static_units', dict(scope, term='Qwi', unit='scfm'),
        dict(sheet='Data Inputs', cell='B23'), kind='engineering_unit_control')
    add('qwi_static_actual', 'static_units', dict(scope, term='Qwi', unit='acfm'),
        dict(sheet='Data Inputs', cell='B24'), kind='engineering_unit_control')
    add('wrong_unit', 'static_units', dict(scope, term=STANDARD, unit='acfm'), reason='unit_mismatch',
        kind='engineering_unit_control')
    add('duplicate_label', 'duplicate', hours, reason='ambiguous_fields', kind='engineering_layout_control')
    add('moved_value', 'moved_value', hours, reason='no_structural_field_match', kind='engineering_layout_control')
    add('changed_formula', 'fault_ratio', dict(scope, term=STANDARD), dict(sheet='Data Inputs', cell='B23'),
        kind='engineering_invariance_control')
    for name, variant in [('epa_ratio', 'original'), ('epa_adjusted', 'original'),
                          ('injected_ratio', 'fault_ratio'), ('injected_adjusted', 'fault_adjusted')]:
        pipeline = json.loads((M7 / 'requests' / (name + '.json')).read_text())
        add('repair_' + name, variant, pipeline=pipeline, kind='end_to_end_fault' if variant != 'original' else 'end_to_end_correct')
    if len(rows) != 18:
        raise SystemExit('Fixed count changed')
    manifest = EXPERIMENT / 'manifest.jsonl'
    with manifest.open('x') as handle:
        handle.write(''.join(json.dumps(row) + '\n' for row in rows))
    key = EXPERIMENT / 'scoring/expected.json'
    write(key, expected)
    files += [manifest, key, Path(__file__), ROOT / 'MODEL_M8_MAPPING_PLAN.md', RUNNER,
              M7 / 'input_lock.json', M7 / 'output_lock.json']
    files += [ROOT / 'tools' / name for name in ['metadata_mapping_m8.py', 'score_mapping_m8.py',
              'test_metadata_mapping_m8.py', 'source_relations_m7.py', 'relation_candidates_m6.py',
              'e3_contract.py', 'candidate_gate_m1.py', 'trace_paper_candidates.py']]
    write(EXPERIMENT / 'input_lock.json', dict(files_sha256={str(path): sha256(path) for path in files},
          requested_workers=20, task_count=18, final_validation_eligible=False,
          metadata_formula_text_included=False, metadata_numeric_values_included=False,
          mapping_queries_manually_supplied=True, paper_input_lock_sha256=sha256(EVIDENCE / 'input_model_lock.json')))
    print('M8 INPUTS LOCKED', len(rows))


def run():
    inputs = verify_context()
    lock_path = EXPERIMENT / 'input_lock.json'
    lock = json.loads(lock_path.read_text())
    verify_files(lock)
    if (EXPERIMENT / 'runs').exists() or (EXPERIMENT / 'output_lock.json').exists():
        raise SystemExit('Preserve existing M8 execution')
    subprocess.run([sys.executable, str(RUNNER), '--manifest', str(EXPERIMENT / 'manifest.jsonl'),
                    '--output-dir', str(EXPERIMENT / 'runs'), '--workers', '20',
                    '--worker-memory-mib', '475', '--timeout', '120'], cwd=ROOT, check=False)
    runtime = json.loads((EXPERIMENT / 'runs/runtime.json').read_text())
    verify_files(lock)
    verify_frozen(inputs)
    if len(runtime['tasks']) != 18 or runtime['requested_worker_count'] != 20:
        raise SystemExit('Task/worker accounting changed')
    outputs = []
    for task in runtime['tasks']:
        path = Path(task.get('cwd', '')) / 'prediction.json'
        if task['status'] == 'complete' and sha256(path) != task['output_sha256']['prediction.json']:
            raise SystemExit('Output hash differs')
        outputs.append(dict(id=task['id'], status=task['status'], path=str(path) if path.exists() else None,
                            sha256=sha256(path) if path.exists() else None))
    write(EXPERIMENT / 'output_lock.json', dict(input_lock_sha256=sha256(lock_path),
          runtime_sha256=sha256(EXPERIMENT / 'runs/runtime.json'), outputs=outputs, scoring_may_begin=True))
    print('M8 TERMINAL OUTPUTS LOCKED', len(outputs))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'run'))
    (prepare if parser.parse_args().stage == 'prepare' else run)()
