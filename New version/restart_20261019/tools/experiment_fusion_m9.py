#!/usr/bin/env python3
"""Freeze and run one emitted-SG-priority ablation with 20 workers."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, RUNNER, verify_frozen
from spreadsheetbench2_scoring import sha256, verify_prediction_lock

EXPERIMENT = EVIDENCE / 'model_m9_fusion'
M2 = EVIDENCE / 'model_m2_trace'


def write(path, data):
    with path.open('x') as handle:
        json.dump(data, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write('\n')


def verify_files(lock):
    for name, expected in lock['files_sha256'].items():
        if sha256(Path(name)) != expected:
            raise SystemExit('M9 artifact changed: ' + name)


def verify_context():
    baseline, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    if sys.executable != baseline['runtime_executable']:
        raise SystemExit('Use locked interpreter')
    terminal = json.loads((M2 / 'output_lock.json').read_text())
    prelock = json.loads((M2 / 'prelock.json').read_text())
    if sha256(M2 / 'prelock.json') != terminal['prelock_sha256'] or sha256(EVIDENCE / 'prediction_lock.json') != prelock['prediction_lock_sha256']:
        raise SystemExit('M2/baseline lock changed')
    if not terminal.get('all_observed_paper_outputs_identical') or not terminal.get('scoring_may_begin'):
        raise SystemExit('M2 not ready')
    for path, expected in prelock['source_sha256'].items():
        if sha256(ROOT / path) != expected:
            raise SystemExit('M2 source changed')
    for path, key in [('runs/runtime.json', 'runtime_sha256'), ('manifest.jsonl', 'manifest_sha256')]:
        if sha256(M2 / path) != terminal[key]:
            raise SystemExit('M2 execution changed')
    originals = {row['id']: row for row in baseline['predictions']}
    if len(terminal['outputs']) != 100 or {row['id'] for row in terminal['outputs']} != set(originals):
        raise SystemExit('M2 task accounting differs')
    for row in terminal['outputs']:
        if (row['trace_status'] != 'complete' or row['baseline_status'] != originals[row['id']]['status']
                or sha256(Path(row['path'])) != row['sha256']):
            raise SystemExit('M2 trace changed')
    return baseline, inputs, terminal


def prepare():
    baseline, _, terminal = verify_context()
    EXPERIMENT.mkdir(exist_ok=False)
    rows, files = [], [M2 / 'output_lock.json', M2 / 'prelock.json', EVIDENCE / 'prediction_lock.json']
    for item in terminal['outputs']:
        if item['baseline_status'] != 'complete':
            continue
        files.append(Path(item['path']))
        rows.append(dict(id=item['id'], argv=[sys.executable, str(ROOT / 'tools/fusion_priority_m9.py'),
                    '--trace', item['path'], '--output', 'prediction.json'], outputs=['prediction.json'], timeout_seconds=120))
    if len(rows) != 90:
        raise SystemExit('Expected 90 completed baseline tasks')
    manifest = EXPERIMENT / 'manifest.jsonl'
    with manifest.open('x') as handle:
        handle.write(''.join(json.dumps(row) + '\n' for row in rows))
    files += [manifest, Path(__file__), RUNNER, ROOT / 'MODEL_M9_FUSION_PLAN.md']
    files += [ROOT / 'tools' / name for name in ['fusion_priority_m9.py', 'score_fusion_m9.py',
              'test_fusion_priority_m9.py', 'spreadsheetbench2_scoring.py']]
    write(EXPERIMENT / 'input_lock.json', dict(files_sha256={str(path): sha256(path) for path in files},
          requested_workers=20, inference_task_count=90, original_task_count=100,
          inherited_terminal_states=[dict(id=row['id'], status=row['status']) for row in baseline['predictions']
                                     if row['status'] != 'complete'],
          source_prediction_lock_sha256=sha256(EVIDENCE / 'prediction_lock.json'),
          final_validation_eligible=False))
    print('M9 INPUTS LOCKED', len(rows))


def run():
    _, inputs, _ = verify_context()
    lock_path = EXPERIMENT / 'input_lock.json'
    lock = json.loads(lock_path.read_text())
    verify_files(lock)
    if (EXPERIMENT / 'runs').exists() or (EXPERIMENT / 'output_lock.json').exists():
        raise SystemExit('Preserve existing M9 execution')
    subprocess.run([sys.executable, str(RUNNER), '--manifest', str(EXPERIMENT / 'manifest.jsonl'),
                    '--output-dir', str(EXPERIMENT / 'runs'), '--workers', '20',
                    '--worker-memory-mib', '475', '--timeout', '120'], cwd=ROOT, check=False)
    runtime = json.loads((EXPERIMENT / 'runs/runtime.json').read_text())
    verify_files(lock)
    verify_frozen(inputs)
    if len(runtime['tasks']) != 90 or runtime['requested_worker_count'] != 20:
        raise SystemExit('M9 task/worker accounting changed')
    outputs = []
    for row in runtime['tasks']:
        path = Path(row.get('cwd', '')) / 'prediction.json'
        if row['status'] == 'complete' and sha256(path) != row['output_sha256']['prediction.json']:
            raise SystemExit('Output changed')
        outputs.append(dict(id=row['id'], status=row['status'], path=str(path) if path.exists() else None,
                            sha256=sha256(path) if path.exists() else None))
    write(EXPERIMENT / 'output_lock.json', dict(input_lock_sha256=sha256(lock_path),
          runtime_sha256=sha256(EXPERIMENT / 'runs/runtime.json'), outputs=outputs,
          inherited_terminal_states=lock['inherited_terminal_states'], scoring_may_begin=True))
    print('M9 OUTPUTS LOCKED', len(outputs))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'run'))
    (prepare if parser.parse_args().stage == 'prepare' else run)()
