#!/usr/bin/env python3
"""Apply M1 to frozen predictions using 20 workers, then lock outputs. No labels."""
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, RUNNER, sha256, verify_frozen
from spreadsheetbench2_scoring import verify_prediction_lock

EXPERIMENT = EVIDENCE / 'model_m1'


def main():
    lock, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    if sys.executable != lock['runtime_executable']:
        raise SystemExit('Use the locked interpreter')
    EXPERIMENT.mkdir(exist_ok=False)
    script = ROOT / 'tools/candidate_gate_m1.py'
    source_hashes = {str(p.relative_to(ROOT)): sha256(p) for p in (
        script, Path(__file__), RUNNER, ROOT / 'MODEL_M1_PLAN.md')}
    prelock = {'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
               'prediction_lock_sha256': sha256(EVIDENCE / 'prediction_lock.json'),
               'source_sha256': source_hashes, 'workers': 20,
               'role': 'Development experiment after full dataset exposure; no holdout claim'}
    (EXPERIMENT / 'prelock.json').write_text(json.dumps(prelock, indent=2) + '\n')
    manifest = EXPERIMENT / 'manifest.jsonl'
    tasks = [dict(id=t['id'], argv=[sys.executable, str(script), '--frozen-prediction',
                  str(Path(t['cwd']) / 'prediction.json'), '--output', 'prediction.json'],
                  outputs=['prediction.json'], timeout_seconds=120)
             for t in lock['full_runtime']['tasks'] if t['status'] == 'complete']
    manifest.write_text(''.join(json.dumps(t) + '\n' for t in tasks))
    subprocess.run([sys.executable, str(RUNNER), '--manifest', str(manifest),
                    '--output-dir', str(EXPERIMENT / 'runs'), '--workers', '20',
                    '--worker-memory-mib', '256', '--timeout', '120'], cwd=ROOT, check=True)
    runtime = json.loads((EXPERIMENT / 'runs/runtime.json').read_text())
    if runtime['worker_count'] != 20 or not runtime['all_tasks_complete']:
        raise SystemExit('M1 batch incomplete or concurrency changed; preserve evidence')
    verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    if any(sha256(ROOT / p) != value for p, value in source_hashes.items()):
        raise SystemExit('M1 implementation changed during experiment')
    outputs = []
    for t in runtime['tasks']:
        path = Path(t['cwd']) / 'prediction.json'
        if sha256(path) != t['output_sha256']['prediction.json']:
            raise SystemExit('Output hash mismatch')
        outputs.append(dict(id=t['id'], path=str(path), sha256=sha256(path)))
    payload = dict(prelock_sha256=sha256(EXPERIMENT / 'prelock.json'),
                   manifest_sha256=sha256(manifest),
                   runtime_sha256=sha256(EXPERIMENT / 'runs/runtime.json'),
                   outputs=outputs, inherited_terminal_states=[
                       {'id': t['id'], 'status': t['status']}
                       for t in lock['predictions'] if t['status'] != 'complete'],
                   scoring_may_begin=True)
    with (EXPERIMENT / 'output_lock.json').open('x') as handle:
        json.dump(payload, handle, indent=2)
        handle.write('\n')
    print('M1 OUTPUTS LOCKED', len(outputs), flush=True)


if __name__ == '__main__':
    main()
