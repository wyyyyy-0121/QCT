#!/usr/bin/env python3
"""Run fixed M9 fusion on every historically locked faultsfw xlsx input."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, RUNNER, verify_frozen
from spreadsheetbench2_scoring import sha256, verify_prediction_lock

EXPERIMENT = EVIDENCE / 'model_m9_external'
FAULTS = ROOT / 'source_evidence/raw/zenodo_581672'
HISTORICAL = ROOT / 'benchmark_runs_faultsfw_v1'


def write(path, data):
    with path.open('x') as handle:
        json.dump(data, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write('\n')


def verify_files(lock):
    for name, digest in lock['files_sha256'].items():
        if sha256(Path(name)) != digest:
            raise SystemExit('External M9 artifact changed: ' + name)


def verify_context():
    baseline, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    if sys.executable != baseline['runtime_executable']:
        raise SystemExit('Use locked interpreter')
    verify_files(json.loads((EVIDENCE / 'model_m9_fusion/input_lock.json').read_text()))
    old_lock = json.loads((FAULTS / 'input_lock.json').read_text())
    if sha256(FAULTS / 'faultsfw.zip') != old_lock['archive_sha256']:
        raise SystemExit('faultsfw archive differs')
    if sha256(FAULTS / 'prediction_manifest.jsonl') != old_lock['manifest_sha256']:
        raise SystemExit('Historical manifest differs')
    for row in old_lock['inputs']:
        if sha256(FAULTS / 'unpacked' / row['relative_path']) != row['sha256']:
            raise SystemExit('faultsfw input changed')
    runtime = json.loads((HISTORICAL / 'runtime.json').read_text())
    if len(runtime['tasks']) != 225:
        raise SystemExit('Historical task accounting differs')
    for row in runtime['tasks']:
        if row['status'] != 'complete' or sha256(Path(row['cwd']) / 'prediction.json') != row['output_sha256']['prediction.json']:
            raise SystemExit('Historical prediction changed')
    return inputs, old_lock, runtime


def prepare():
    _, old_lock, runtime = verify_context()
    EXPERIMENT.mkdir(exist_ok=False)
    allowed = {str((FAULTS / 'unpacked' / row['relative_path']).resolve()) for row in old_lock['inputs']}
    rows, files, books = [], [], set()
    for row in runtime['tasks']:
        source = str(Path(row['argv'][2]).resolve())
        books.add(source)
        rows.append(dict(id=row['id'], argv=[sys.executable, str(ROOT / 'tools/predict_fusion_m9.py'),
                    source, '--output', 'prediction.json'], outputs=['prediction.json'], timeout_seconds=900))
        files += [Path(source), Path(row['cwd']) / 'prediction.json']
    if books != allowed or len(rows) != 225:
        raise SystemExit('External scope differs from all225 locked inputs')
    manifest = EXPERIMENT / 'manifest.jsonl'
    with manifest.open('x') as handle:
        handle.write(''.join(json.dumps(row) + '\n' for row in rows))
    files += [manifest, Path(__file__), RUNNER, FAULTS / 'input_lock.json', FAULTS / 'score_inventory.json',
              FAULTS / 'prediction_manifest.jsonl', HISTORICAL / 'runtime.json', ROOT / 'MODEL_M9_EXTERNAL_PLAN.md',
              EVIDENCE / 'model_m9_fusion/input_lock.json', EVIDENCE / 'model_m9_fusion/output_lock.json']
    files += [ROOT / 'tools' / name for name in ['fusion_priority_m9.py', 'predict_fusion_m9.py',
              'score_external_m9.py', 'trace_paper_candidates.py', 'spreadsheetbench2_scoring.py']]
    write(EXPERIMENT / 'input_lock.json', dict(files_sha256={str(path): sha256(path) for path in files},
          task_count=225, requested_workers=20, final_validation_eligible=False,
          truth_unknown_versions=6, unsupported_xls_versions=27,
          rule='Unchanged M9 SG emitted priority; no external-data tuning'))
    print('M9 EXTERNAL INPUTS LOCKED', len(rows))


def run():
    inputs, _, _ = verify_context()
    lock_path = EXPERIMENT / 'input_lock.json'
    lock = json.loads(lock_path.read_text())
    verify_files(lock)
    if (EXPERIMENT / 'runs').exists() or (EXPERIMENT / 'output_lock.json').exists():
        raise SystemExit('Preserve external M9 execution')
    subprocess.run([sys.executable, str(RUNNER), '--manifest', str(EXPERIMENT / 'manifest.jsonl'),
                    '--output-dir', str(EXPERIMENT / 'runs'), '--workers', '20',
                    '--worker-memory-mib', '475', '--timeout', '900'], cwd=ROOT, check=False)
    runtime = json.loads((EXPERIMENT / 'runs/runtime.json').read_text())
    verify_files(lock)
    verify_frozen(inputs)
    if len(runtime['tasks']) != 225 or runtime['requested_worker_count'] != 20:
        raise SystemExit('External M9 task accounting changed')
    outputs = []
    for row in runtime['tasks']:
        path = Path(row.get('cwd', '')) / 'prediction.json'
        if row['status'] == 'complete' and sha256(path) != row['output_sha256']['prediction.json']:
            raise SystemExit('External prediction differs')
        outputs.append(dict(id=row['id'], status=row['status'], path=str(path) if path.exists() else None,
                            sha256=sha256(path) if path.exists() else None))
    write(EXPERIMENT / 'output_lock.json', dict(input_lock_sha256=sha256(lock_path),
          runtime_sha256=sha256(EXPERIMENT / 'runs/runtime.json'), outputs=outputs, scoring_may_begin=True))
    print('M9 EXTERNAL TERMINAL OUTPUTS LOCKED', len(outputs))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'run'))
    (prepare if parser.parse_args().stage == 'prepare' else run)()
