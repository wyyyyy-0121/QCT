#!/usr/bin/env python3
"""Lock and execute unchanged M9 on full natural and authored-control groups."""
import argparse
import gzip
import json
from pathlib import Path
import subprocess
import sys

from openpyxl import load_workbook

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, RUNNER, verify_frozen
from spreadsheetbench2_scoring import sha256, verify_prediction_lock

LEGACY = ROOT.parent / 'followup_20261014'
EXPERIMENT = EVIDENCE / 'model_m9_natural'
CV = LEGACY / 'development/natural_cv500_dev27_v1'
TEXT = LEGACY / 'development/record_candidates_dev29_v1'
FINANCE = LEGACY / 'development/conditioned_relations_dev32_v3'


def read(path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def write(path, data):
    with path.open('x') as handle:
        json.dump(data, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write('\n')


def verify_files(lock):
    for name, digest in lock['files_sha256'].items():
        if sha256(Path(name)) != digest:
            raise SystemExit('Natural M9 locked artifact changed: ' + name)


def verify_context():
    baseline, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    if sys.executable != baseline['runtime_executable']:
        raise SystemExit('Use locked interpreter')
    for name in ('model_m9_fusion', 'model_m9_external'):
        verify_files(read(EVIDENCE / name / 'input_lock.json'))
    for pack, prefix in [(CV, LEGACY), (TEXT, LEGACY), (FINANCE, LEGACY)]:
        source_lock = read(pack / 'source_lock.json')
        for rel, digest in source_lock['files'].items():
            if sha256(prefix / rel) != digest:
                raise SystemExit('Historical source lock changed: ' + rel)
    for pack, truth_name, truth_key in [(TEXT, 'controls_truth.json.gz', 'controls_truth_sha256'),
                                       (FINANCE, 'control_truth.json', 'control_truth_sha256')]:
        preparation = read(pack / 'preparation_lock.json')
        for name, digest in preparation['inputs'].items():
            if sha256(LEGACY / name) != digest:
                raise SystemExit('Historical prepared input changed: ' + name)
        for path, digest in [(pack / 'source_lock.json', preparation['source_lock_sha256']),
                             (pack / ('index.json' if pack == TEXT else 'public_index.json'), preparation['index_sha256']),
                             (pack / truth_name, preparation[truth_key])]:
            if sha256(path) != digest:
                raise SystemExit('Historical preparation changed: ' + str(path))
    finance_predictions = read(FINANCE / 'prediction_lock.json')
    for name, digest in finance_predictions['files'].items():
        if sha256(FINANCE / name) != digest:
            raise SystemExit('Historical finance prediction changed: ' + name)
    for name in ('source_lock', 'preparation_lock'):
        if sha256(FINANCE / (name + '.json')) != finance_predictions[name + '_sha256']:
            raise SystemExit('Historical finance lock chain changed')
    for folder in ('source_evidence/epa_pairs/xlsx_prediction_lock.json', 'source_evidence/metrics_pair/prediction_lock.json'):
        for rel, digest in read(ROOT / folder)['files'].items():
            if sha256(ROOT / rel) != digest:
                raise SystemExit('Natural source/prediction changed: ' + rel)
    return inputs


def prepare():
    verify_context()
    if EXPERIMENT.exists():
        raise SystemExit('Preserve natural M9 preparation')
    rows, cases, files = [], {}, []

    def add(name, source, group, errors=None, correct=None, historical=None, comparison='full',
            candidate_targets=None, blank_controls=None, provenance=None):
        cases[name] = dict(workbook=str(source), group=group, errors=errors or {}, correct=correct or {},
                           historical=str(historical) if historical else None, comparison=comparison,
                           candidate_targets=candidate_targets or {}, blank_controls=blank_controls or [],
                           provenance=provenance, final_validation_eligible=False)
        rows.append(dict(id=name, argv=[sys.executable, str(ROOT / 'tools/predict_fusion_m9.py'), str(source),
                                        '--output', 'prediction.json'], outputs=['prediction.json'], timeout_seconds=900))
        files.append(source)
        if historical:
            files.append(historical)

    cv_truth = read(CV / 'natural_truth.json.gz')
    cv_errors = {row['cell']: row['accepted_formula'] for row in cv_truth['cases']}
    if len(cv_errors) != 505 or not cv_truth['all_original_formula_cells_labelled']:
        raise SystemExit('CV certified scope changed')
    cv_lock = read(CV / 'prediction_lock.json')
    if sha256(CV / 'raw/before.xlsx') != cv_lock['input_sha256']:
        raise SystemExit('CV original differs')
    for rel, digest in cv_lock['files'].items():
        if sha256(CV / rel) != digest:
            raise SystemExit('CV historical prediction differs')
    add('natural_cv500', CV / 'raw/before.xlsx', 'natural_errors', errors=cv_errors,
        historical=CV / 'prediction.json.gz', provenance='All505 certified same-record formula defects; exposed')
    add('corrected_cv500', CV / 'raw/after.xlsx', 'corrected_controls', correct=cv_errors,
        provenance='Same exposed source; all505 formulas independently certified in historical audit')
    for name, cells in [('flares', ['Design Parameters!B' + str(i) for i in range(39,44)]),
                        ('oxidizers', ['Design Parameters!D36'])]:
        pair = ROOT / 'source_evidence/raw/epa_pairs' / (name + '_pair_inventory.local.json.gz')
        inventory = read(pair)
        accepted = {cell: inventory['after']['formulas'][cell] for cell in cells}
        files.append(pair)
        add('natural_epa_' + name, ROOT / 'source_evidence/raw/epa_pairs/xlsx_export' / (name + '_before.xlsx'),
            'natural_errors', errors=accepted,
            historical=ROOT / 'source_evidence/raw/epa_pairs/xlsx_run/tasks' / name / 'prediction.json',
            provenance='Official errata targets only; other differences unknown; exposed EPA source')
    aed = ROOT / 'source_evidence/raw/aedist_err510'
    aed_expected = {'Power plants!N254': '=1330/2', 'Power plants!N255': '=N254'}
    for stage, folder, file, digest in [
        ('original','xlsx_original','original_9ba17cd.xlsx','c4f362478121f50771341e4dcc72c307201fee1598ae8adf3f3691b204f459cf'),
        ('corrected','xlsx_corrected','corrected_2ad5b21.xlsx','a7191b168c0bacfb249bd48b783d4b59b0e9bdd5dbc69e4e3d93d03f9b1fec7e')]:
        source = aed / folder / file
        if sha256(source) != digest:
            raise SystemExit('AEDIST conversion differs')
        add('aedist_' + stage, source, 'natural_errors' if stage == 'original' else 'corrected_controls',
            errors=aed_expected if stage == 'original' else {}, correct=aed_expected if stage == 'corrected' else {},
            historical=aed / 'workers1' / stage / 'prediction.json',
            provenance='Two author-corrected targets; known conversion boundary; rest of workbook unknown')
    audit_path = ROOT / 'source_evidence/metrics_pair/E1_BASELINE_AUDIT_V2.json'
    audit = read(audit_path)
    before, after = ROOT / 'source_evidence/raw/metrics_pair/before.xlsx', ROOT / 'source_evidence/raw/metrics_pair/after.xlsx'
    book = load_workbook(after, read_only=True, data_only=False)
    candidates, controls = {}, []
    try:
        for record in audit['records']:
            cell = record['cell']
            sheet, address = cell.rsplit('!', 1)
            if record['label'] == 'formula_defect_candidate':
                candidates[cell] = book[sheet][address].value
            elif record['label'] == 'blank_boundary_control':
                controls.append(cell)
    finally:
        book.close()
    if (len(candidates),len(controls)) != (28,160):
        raise SystemExit('Metrics candidate scope changed')
    add('metrics_original', before, 'range_candidates', candidate_targets=candidates, blank_controls=controls,
        historical=ROOT / 'source_evidence/raw/metrics_pair/original_run/tasks/metrics/prediction.json',
        provenance='28 range candidates;8 realized output differences;160 blank controls; not certified natural513')
    files += [after, audit_path]
    text_cases = read(TEXT / 'controls_truth.json.gz')['cases']
    if len(text_cases) != 16:
        raise SystemExit('Text control scope changed')
    for case in text_cases:
        errors = {cell: row['original_formula'] for cell,row in case['errors'].items()}
        correct = {cell: formula for cell,formula in case['all_expected'].items() if cell not in errors}
        add('text_' + case['id'], TEXT / 'controls' / (case['id'] + '.xlsx'), 'authored_text',
            errors=errors, correct=correct, provenance=case['truth_source'])
    finance_truth = {row['case']:row for row in read(FINANCE / 'control_truth.json')['cases']}
    index = [row for row in read(FINANCE / 'public_index.json') if row['stratum'] == 'conditioned_control']
    if len(index) != 26:
        raise SystemExit('Finance control scope changed')
    for row in index:
        source = LEGACY / row['input']
        if sha256(source) != row['input_sha256'] or row.get('parallel_sheets'):
            raise SystemExit('Finance source/parallel scope changed')
        truth = finance_truth[row['case']]
        errors = {cell:truth['expected_formulas'][cell] for cell in truth['errors']}
        correct = {cell:formula for cell,formula in truth['expected_formulas'].items() if cell not in errors}
        add('finance_' + row['id'], source, 'authored_finance', errors=errors, correct=correct,
            historical=FINANCE / 'predictions' / (row['case'].replace('/','__') + '.json.gz'), comparison='suggestions_only',
            provenance=truth['scope'])
    if len(rows) != 49 or sum(len(row['errors']) for row in cases.values() if row['group']=='natural_errors') != 513:
        raise SystemExit('Natural/control denominator changed')
    files += [CV / 'natural_truth.json.gz', CV / 'prediction_lock.json', CV / 'source_lock.json',
              TEXT / 'controls_truth.json.gz', TEXT / 'source_lock.json', TEXT / 'preparation_lock.json',
              FINANCE / 'control_truth.json', FINANCE / 'public_index.json', FINANCE / 'source_lock.json',
              FINANCE / 'prediction_lock.json', FINANCE / 'preparation_lock.json']
    key = EXPERIMENT / 'scoring/expected.json'
    # Validate all generated paths and implementation files before creating an
    # immutable evidence directory; a preparation error must not masquerade as a run.
    implementation = [Path(__file__), RUNNER, ROOT / 'MODEL_M9_NATURAL_PLAN.md']
    implementation += [ROOT / 'tools' / name for name in ['predict_fusion_m9.py','fusion_priority_m9.py',
                       'trace_paper_candidates.py','score_natural_m9.py','spreadsheetbench2_scoring.py']]
    for path in files + implementation:
        if not path.is_file():
            raise SystemExit('Missing preparation artifact: ' + str(path))
    EXPERIMENT.mkdir(exist_ok=False)
    (EXPERIMENT / 'scoring').mkdir()
    write(key, cases)
    manifest = EXPERIMENT / 'manifest.jsonl'
    with manifest.open('x') as handle:
        handle.write(''.join(json.dumps(row) + '\n' for row in rows))
    files += [key, manifest] + implementation
    write(EXPERIMENT / 'input_lock.json', dict(files_sha256={str(path):sha256(path) for path in files},
          task_count=49, requested_workers=20, natural_error_denominator=513, final_validation_eligible=False,
          group_counts={name:sum(row['group']==name for row in cases.values()) for name in sorted({row['group'] for row in cases.values()})}))
    print('M9 NATURAL INPUTS LOCKED',len(rows))


def run():
    inputs = verify_context()
    lock_path = EXPERIMENT / 'input_lock.json'
    lock = read(lock_path)
    verify_files(lock)
    if (EXPERIMENT / 'runs').exists() or (EXPERIMENT / 'output_lock.json').exists():
        raise SystemExit('Preserve natural M9 execution')
    subprocess.run([sys.executable,str(RUNNER),'--manifest',str(EXPERIMENT/'manifest.jsonl'),
                    '--output-dir',str(EXPERIMENT/'runs'),'--workers','20',
                    '--worker-memory-mib','475','--timeout','900'],cwd=ROOT,check=False)
    runtime = read(EXPERIMENT/'runs/runtime.json')
    verify_files(lock)
    verify_frozen(inputs)
    if len(runtime['tasks']) != 49 or runtime['requested_worker_count'] != 20:
        raise SystemExit('Natural task/worker accounting changed')
    outputs=[]
    for row in runtime['tasks']:
        path=Path(row.get('cwd',''))/'prediction.json'
        if row['status']=='complete' and sha256(path)!=row['output_sha256']['prediction.json']:
            raise SystemExit('Natural prediction changed')
        outputs.append(dict(id=row['id'],status=row['status'],path=str(path) if path.exists() else None,
                            sha256=sha256(path) if path.exists() else None))
    write(EXPERIMENT/'output_lock.json',dict(input_lock_sha256=sha256(lock_path),
          runtime_sha256=sha256(EXPERIMENT/'runs/runtime.json'),outputs=outputs,scoring_may_begin=True))
    print('M9 NATURAL OUTPUTS LOCKED',len(outputs))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('prepare','run'))
    (prepare if parser.parse_args().stage=='prepare' else run)()
