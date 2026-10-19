#!/usr/bin/env python3
"""Run the fixed relation-generator conditions; one 20-worker batch only."""
import json
from pathlib import Path
import subprocess
import sys

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, RUNNER, verify_frozen
from spreadsheetbench2_scoring import verify_prediction_lock, sha256

EXPERIMENT = EVIDENCE / 'model_m6_relation'


def main():
    original, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    if sys.executable != original['runtime_executable']:
        raise SystemExit('Use locked interpreter')
    input_lock = EXPERIMENT / 'input_lock.json'
    lock = json.loads(input_lock.read_text())
    for path, expected in lock['files_sha256'].items():
        if sha256(path) != expected:
            raise SystemExit('M6 locked input/source changed')
    if (EXPERIMENT / 'runs').exists() or (EXPERIMENT / 'output_lock.json').exists():
        raise SystemExit('Preserve existing M6 execution')
    subprocess.run([sys.executable, str(RUNNER), '--manifest', str(EXPERIMENT / 'manifest.jsonl'),
                    '--output-dir', str(EXPERIMENT / 'runs'), '--workers', '20',
                    '--worker-memory-mib', '475', '--timeout', '120'], cwd=ROOT, check=False)
    runtime = json.loads((EXPERIMENT / 'runs/runtime.json').read_text())
    verify_frozen(inputs)
    if runtime['worker_count'] != 20 or len(runtime['tasks']) != 16:
        raise SystemExit('M6 concurrency/task accounting differs')
    for path, expected in lock['files_sha256'].items():
        if sha256(path) != expected:
            raise SystemExit('M6 locked input/source changed during inference')
    outputs = []
    for task in runtime['tasks']:
        path = Path(task['cwd']) / 'prediction.json'
        if task['status'] == 'complete' and sha256(path) != task['output_sha256']['prediction.json']:
            raise SystemExit('M6 prediction hash changed')
        outputs.append(dict(id=task['id'], status=task['status'], path=str(path) if path.exists() else None,
                            sha256=sha256(path) if path.exists() else None))
    with (EXPERIMENT / 'output_lock.json').open('x') as handle:
        json.dump(dict(input_lock_sha256=sha256(input_lock),
                       runtime_sha256=sha256(EXPERIMENT / 'runs/runtime.json'),
                       outputs=outputs, scoring_may_begin=True,
                       runner_source_sha256=sha256(Path(__file__))), handle, indent=2)
        handle.write('\n')
    print('M6 OUTPUT TERMINAL STATES LOCKED', len(outputs), flush=True)


if __name__ == '__main__':
    main()
