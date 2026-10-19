#!/usr/bin/env python3
"""Freeze, execute and lock the single-factor M3 generator using 20 workers."""
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, RUNNER, verify_frozen
from spreadsheetbench2_scoring import verify_prediction_lock, sha256

EXPERIMENT = EVIDENCE / 'model_m3_horizontal'


def main():
    baseline, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    if sys.executable != baseline['runtime_executable']:
        raise SystemExit('Use locked interpreter')
    EXPERIMENT.mkdir(exist_ok=False)
    script = ROOT / 'tools/horizontal_candidates_m3.py'
    sources = {str(p.relative_to(ROOT)): sha256(p) for p in (
        script, Path(__file__), RUNNER, ROOT / 'MODEL_M3_HORIZONTAL_PLAN.md')}
    prelock = dict(created_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                   prediction_lock_sha256=sha256(EVIDENCE / 'prediction_lock.json'),
                   m2_output_lock_sha256=sha256(EVIDENCE / 'model_m2_trace/output_lock.json'),
                   source_sha256=sources, workers=20)
    (EXPERIMENT / 'prelock.json').write_text(json.dumps(prelock, indent=2) + '\n')
    manifest = EXPERIMENT / 'manifest.jsonl'
    tasks = [dict(id=t['id'], argv=[sys.executable, str(script), '--frozen-prediction',
                  str(Path(t['cwd']) / 'prediction.json'), '--output', 'candidates.json.gz'],
                  outputs=['candidates.json.gz'], timeout_seconds=120)
             for t in baseline['full_runtime']['tasks'] if t['status'] == 'complete']
    manifest.write_text(''.join(json.dumps(t) + '\n' for t in tasks))
    subprocess.run([sys.executable, str(RUNNER), '--manifest', str(manifest),
                    '--output-dir', str(EXPERIMENT / 'runs'), '--workers', '20',
                    '--worker-memory-mib', '256', '--timeout', '120'], cwd=ROOT, check=True)
    runtime = json.loads((EXPERIMENT / 'runs/runtime.json').read_text())
    verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    if runtime['worker_count'] != 20 or not runtime['all_tasks_complete'] or len(runtime['tasks']) != 90:
        raise SystemExit('Incomplete batch or concurrency changed')
    if any(sha256(ROOT / path) != digest for path, digest in sources.items()):
        raise SystemExit('M3 sources changed')
    outputs = []
    for task in runtime['tasks']:
        path = Path(task['cwd']) / 'candidates.json.gz'
        if sha256(path) != task['output_sha256']['candidates.json.gz']:
            raise SystemExit('Candidate hash differs')
        outputs.append(dict(id=task['id'], path=str(path), sha256=sha256(path)))
    lock = dict(prelock_sha256=sha256(EXPERIMENT / 'prelock.json'),
                manifest_sha256=sha256(manifest), runtime_sha256=sha256(EXPERIMENT / 'runs/runtime.json'),
                outputs=outputs, inherited_timeout_ids=[t['id'] for t in baseline['predictions'] if t['status'] != 'complete'],
                scoring_may_begin=True)
    with (EXPERIMENT / 'output_lock.json').open('x') as handle:
        json.dump(lock, handle, indent=2)
        handle.write('\n')
    print('M3 CANDIDATES LOCKED', len(outputs), flush=True)


if __name__ == '__main__':
    main()
