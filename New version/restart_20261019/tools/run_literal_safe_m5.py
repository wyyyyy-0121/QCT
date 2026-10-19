#!/usr/bin/env python3
"""Freeze and run M5 paper inference plus independent Calc semantic controls."""
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, RUNNER, safe_id, verify_frozen
from spreadsheetbench2_scoring import verify_prediction_lock, sha256

EXPERIMENT = EVIDENCE / 'model_m5_literal'
CALC_WORKER = ROOT.parent / 'followup_20261014/scripts/libreoffice_reference_worker.py'


def prepare_calc():
    import openpyxl
    from trace_paper_candidates import ROOT as _root
    import formulaguard.formula as native
    from literal_safe_candidates import wrap_transforms
    _, safe = wrap_transforms(native)
    cases = [
        ('=IF(A1=0,"A1+B1 / SUM",B1)', 'A1+B1 / SUM', 'text'),
        ('=IF(A1=0,"A1 ""quote""",B1)', 'A1 "quote"', 'text'),
        ('=IF(A1>0,"A1+B1",B1+$B$1)', 13, 'number'),
        ('=IF(A1=0,"New York",B1)', 'New York', 'text'),
        ('=IF(A1=0,"SUM / A1",B1)', 'SUM / A1', 'text'),
        ('=IF(A1>0,"A1",\'A+B SUM\'!$A$1+B1)', 11, 'number'),
        ('=A1+B1*$B$1', 36, 'number'),
        ('=IF(A1=0,"first", "A1+B1")', 'first', 'text'),
    ]
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = 'S'
    sheet['A1'], sheet['A2'], sheet['B1'], sheet['B2'] = 0, 0, 9, 4
    book.create_sheet('A+B SUM')['A1'] = 7
    expected = {}
    for number, (formula, value, kind) in enumerate(cases, 1):
        sheet[f'H{number}'] = safe['translate_formula'](formula, 'C1', 'C2')
        sheet[f'J{number}'] = native.translate_formula(formula, 'C1', 'C2')
        expected['S!H' + str(number)] = dict(kind=kind, value=value)
        expected['S!J' + str(number)] = dict(kind=kind, value=value)
    path = EXPERIMENT / 'calc_control.xlsx'
    book.save(path)
    request = EXPERIMENT / 'calc_request.json'
    request.write_text(json.dumps(dict(input=str(path), cells=list(expected)), indent=2) + '\n')
    expected_path = EXPERIMENT / 'calc_expected.json'
    expected_path.write_text(json.dumps(expected, indent=2) + '\n')
    return path, request, expected_path


def main():
    baseline, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    if sys.executable != baseline['runtime_executable']:
        raise SystemExit('Use locked interpreter')
    available = next(int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()
                     if line.startswith('MemAvailable:'))
    if available * .7 < 20 * 475 * 1024**2:
        raise SystemExit('Not enough current memory for 20 workers; no batch started')
    EXPERIMENT.mkdir(exist_ok=False)
    calc_files = prepare_calc()
    predictor = ROOT / 'tools/predict_literal_safe_m5.py'
    files = [predictor, Path(__file__), ROOT / 'tools/literal_safe_candidates.py',
             ROOT / 'tools/trace_paper_candidates.py', RUNNER, ROOT / 'MODEL_M5_LITERAL_PLAN.md',
             CALC_WORKER, *calc_files]
    prelock = dict(created_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                   prediction_lock_sha256=sha256(EVIDENCE / 'prediction_lock.json'),
                   files_sha256={str(p): sha256(p) for p in files}, workers=20)
    (EXPERIMENT / 'prelock.json').write_text(json.dumps(prelock, indent=2) + '\n')
    input_by_id = {safe_id(r['archive_path']): r for r in inputs['inputs']}
    tasks = [dict(id=t['id'], argv=[sys.executable, str(predictor), '--input',
                  input_by_id[t['id']]['local_path'], '--output', 'prediction.json'],
                  outputs=['prediction.json'], timeout_seconds=900)
             for t in baseline['full_runtime']['tasks'] if t['status'] == 'complete']
    tasks.append(dict(id='calc_semantic_control', argv=['/usr/bin/python3', str(CALC_WORKER), str(calc_files[1]), 'calc_result.json'],
                      outputs=['calc_result.json'], timeout_seconds=120))
    manifest = EXPERIMENT / 'manifest.jsonl'
    manifest.write_text(''.join(json.dumps(t) + '\n' for t in tasks))
    subprocess.run([sys.executable, str(RUNNER), '--manifest', str(manifest), '--output-dir', str(EXPERIMENT / 'runs'),
                    '--workers', '20', '--worker-memory-mib', '475', '--timeout', '900'], cwd=ROOT, check=False)
    runtime = json.loads((EXPERIMENT / 'runs/runtime.json').read_text())
    verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    if runtime['worker_count'] != 20 or len(runtime['tasks']) != 91:
        raise SystemExit('M5 concurrency or task coverage differs')
    if any(sha256(p) != digest for p, digest in prelock['files_sha256'].items()):
        raise SystemExit('M5 source or Calc control changed')
    outputs = []
    for task in runtime['tasks']:
        output = 'calc_result.json' if task['id'] == 'calc_semantic_control' else 'prediction.json'
        path = Path(task['cwd']) / output
        if task['status'] == 'complete' and sha256(path) != task['output_sha256'][output]:
            raise SystemExit('M5 output hash differs')
        outputs.append(dict(id=task['id'], status=task['status'],
                            path=str(path) if task['status'] == 'complete' else None,
                            sha256=sha256(path) if task['status'] == 'complete' else None))
    with (EXPERIMENT / 'output_lock.json').open('x') as handle:
        json.dump(dict(prelock_sha256=sha256(EXPERIMENT / 'prelock.json'),
                       manifest_sha256=sha256(manifest), runtime_sha256=sha256(EXPERIMENT / 'runs/runtime.json'),
                       outputs=outputs, scoring_may_begin=True), handle, indent=2)
        handle.write('\n')
    print('M5 TERMINAL OUTPUTS LOCKED', len(outputs), flush=True)


if __name__ == '__main__':
    main()
