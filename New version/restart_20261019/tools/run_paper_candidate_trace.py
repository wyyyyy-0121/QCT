#!/usr/bin/env python3
"""Run and lock the fixed M2 candidate observation batch; no scoring labels."""
import datetime as dt
import gzip
import json
from pathlib import Path
import subprocess
import sys

from resume_spreadsheetbench2_after_pilot import (
    ROOT, EVIDENCE, RUNNER, sha256, verify_frozen, safe_id,
)
from spreadsheetbench2_scoring import verify_prediction_lock

EXPERIMENT = EVIDENCE / 'model_m2_trace'


def main():
    lock, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    if sys.executable != lock['runtime_executable']:
        raise SystemExit('Use the locked interpreter')
    script = ROOT / 'tools/trace_paper_candidates.py'
    source_hashes = {str(p.relative_to(ROOT)): sha256(p) for p in (
        script, Path(__file__), RUNNER, ROOT / 'MODEL_M2_TRACE_PLAN.md')}
    available = next(int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()
                     if line.startswith('MemAvailable:'))
    if .7 * available < 20 * 475 * 1024**2:
        raise SystemExit('Not enough current memory for 20 trace workers; no batch started')
    EXPERIMENT.mkdir(exist_ok=False)
    prelock = dict(created_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                   prediction_lock_sha256=sha256(EVIDENCE / 'prediction_lock.json'),
                   source_sha256=source_hashes, workers=20,
                   baseline_timeout_policy='Input XML inventory only; no repeated inference',
                   role='Post-exposure mechanism diagnosis; no new repair algorithm')
    (EXPERIMENT / 'prelock.json').write_text(json.dumps(prelock, indent=2) + '\n')
    input_by_id = {safe_id(row['archive_path']): row for row in inputs['inputs']}
    tasks = []
    for task in lock['full_runtime']['tasks']:
        argv = [sys.executable, str(script), '--input', input_by_id[task['id']]['local_path'],
                '--output', 'trace.json.gz']
        if task['status'] == 'complete':
            argv += ['--frozen-prediction', str(Path(task['cwd']) / 'prediction.json')]
        tasks.append(dict(id=task['id'], argv=argv, outputs=['trace.json.gz'], timeout_seconds=900))
    manifest = EXPERIMENT / 'manifest.jsonl'
    manifest.write_text(''.join(json.dumps(t) + '\n' for t in tasks))
    process = subprocess.run([sys.executable, str(RUNNER), '--manifest', str(manifest),
                              '--output-dir', str(EXPERIMENT / 'runs'), '--workers', '20',
                              '--worker-memory-mib', '475', '--timeout', '900'], cwd=ROOT, check=False)
    runtime = json.loads((EXPERIMENT / 'runs/runtime.json').read_text())
    verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    if any(sha256(ROOT / path) != expected for path, expected in source_hashes.items()):
        raise SystemExit('Trace source changed; preserve batch')
    outputs = []
    original = {task['id']: task for task in lock['predictions']}
    consistent = True
    for task in runtime['tasks']:
        path = Path(task['cwd']) / 'trace.json.gz'
        row = dict(id=task['id'], trace_status=task['status'],
                   baseline_status=original[task['id']]['status'],
                   path=str(path) if path.exists() else None,
                   sha256=sha256(path) if path.exists() else None)
        if task['status'] == 'complete':
            if row['sha256'] != task['output_sha256']['trace.json.gz']:
                raise SystemExit('Trace hash mismatch')
            with gzip.open(path, 'rt') as handle:
                result = json.load(handle)
            if original[task['id']]['status'] == 'complete':
                consistent &= result.get('paper_content_identical') is True
                consistent &= result.get('observed_formulas_identical') is True
        else:
            consistent = False
        outputs.append(row)
    ready = (process.returncode == 0 and runtime['worker_count'] == 20
             and len(outputs) == 100 and runtime['all_tasks_complete'] and consistent)
    payload = dict(prelock_sha256=sha256(EXPERIMENT / 'prelock.json'),
                   runtime_sha256=sha256(EXPERIMENT / 'runs/runtime.json'),
                   manifest_sha256=sha256(manifest), outputs=outputs,
                   all_observed_paper_outputs_identical=consistent, scoring_may_begin=ready)
    with (EXPERIMENT / 'output_lock.json').open('x') as handle:
        json.dump(payload, handle, indent=2)
        handle.write('\n')
    print('M2 LOCKED; SCORING READY:', ready, flush=True)
    if not ready:
        raise SystemExit('M2 failed a trace/comparison requirement; preserve and investigate')


if __name__ == '__main__':
    main()
