#!/usr/bin/env python3
"""Repeat frozen inference at 16 workers after validating the baseline lock.

This is a resource experiment, never an alternate accuracy baseline. It does
not open golden workbooks or task labels. The original runner remains frozen.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys

from resume_spreadsheetbench2_after_pilot import (
    EVIDENCE, INPUT_LOCK, ROOT, RUNNER, sha256, task_signature,
    validate_runtime, verify_frozen, write_json,
)
from spreadsheetbench2_scoring import verify_prediction_lock


def available_memory_bytes():
    return next(int(line.split()[1]) * 1024
                for line in Path('/proc/meminfo').read_text().splitlines()
                if line.startswith('MemAvailable:'))


def admission(available, workers=16, estimate_mib=550):
    budget = int(available * .7)
    effective = min(workers, budget // (estimate_mib * 1024 * 1024))
    if effective < workers:
        raise ValueError(f'Insufficient admission budget for {workers} workers; '
                         f'runner would use {effective}. Wait for memory; do not relabel.')
    return {'available_memory_bytes': available, 'memory_budget_bytes': budget,
            'requested_workers': workers, 'estimate_mib_per_worker': estimate_mib}


def differences(baseline, repeat):
    old, new = task_signature(baseline), task_signature(repeat)
    if set(old) != set(new):
        raise ValueError('Repeated task IDs differ from baseline')
    return {key: {'baseline': list(old[key]), 'repeat': list(new[key])}
            for key in old if old[key] != new[key]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    lock, inputs = verify_prediction_lock(EVIDENCE)
    if sys.executable != lock['runtime_executable'] or sys.version != lock['runtime_python']:
        raise SystemExit('Use the locked Python interpreter')
    verify_frozen(inputs)
    manifest = EVIDENCE / 'manifests/full_workers_8.jsonl'
    if sha256(manifest) != lock['full_runtime']['manifest_sha256']:
        raise SystemExit('Full manifest differs from baseline')
    validate_runtime(lock['full_runtime'], manifest)
    plan = admission(available_memory_bytes())
    if args.check_only:
        print(json.dumps(plan, indent=2))
        return
    target = EVIDENCE / 'runs/full_workers_16'
    record = EVIDENCE / 'resource_scaling_16_preflight.json'
    summary = EVIDENCE / 'resource_scaling_16_comparison.json'
    if target.exists() or record.exists() or summary.exists():
        raise SystemExit('Preserving existing scaling evidence; inspect its live process/runtime')
    plan.update(created_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                prediction_lock_sha256=sha256(EVIDENCE / 'prediction_lock.json'),
                input_model_lock_sha256=sha256(INPUT_LOCK),
                manifest_sha256=sha256(manifest),
                runner_sha256=sha256(RUNNER),
                scaling_script_sha256=sha256(Path(__file__)),
                scope='Independent post-baseline resource repeat, no accuracy selection')
    write_json(record, plan)
    result = subprocess.run([
        sys.executable, str(RUNNER), '--manifest', str(manifest),
        '--output-dir', str(target), '--workers', '16',
        '--worker-memory-mib', '550', '--timeout', '900',
    ], cwd=ROOT, check=False)
    runtime = json.loads((target / 'runtime.json').read_text())
    verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    validate_runtime(runtime, manifest)
    if runtime['worker_count'] != 16 or runtime['manifest_sha256'] != sha256(manifest):
        raise SystemExit('Resource repeat did not run 16 workers on the frozen manifest')
    delta = differences(lock['full_runtime'], runtime)
    comparison = {
        'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'prediction_lock_sha256': plan['prediction_lock_sha256'],
        'preflight_sha256': sha256(record), 'runner_returncode': result.returncode,
        'runtime_sha256': sha256(target / 'runtime.json'),
        'worker_count': runtime['worker_count'],
        'all_terminal_states_and_success_hashes_identical': not delta,
        'task_differences': delta,
        'wall_seconds_8': lock['full_runtime']['wall_seconds'],
        'wall_seconds_16': runtime['wall_seconds'],
        'child_cpu_seconds_16': runtime['child_cpu_seconds'],
        'cpu_accounting_complete_16': runtime['cpu_accounting_complete'],
        'aggregate_peak_rss_bytes_sampled_16': runtime['aggregate_peak_rss_bytes_sampled'],
        'speedup': None,
        'speedup_limitation': 'Censored tasks and incomplete CPU accounting; report raw wall times',
        'accuracy_baseline_replaced': False,
    }
    write_json(summary, comparison)
    print(json.dumps(comparison, indent=2))
    if delta:
        raise SystemExit('Resource results differ: preserve and investigate, do not select accuracy outputs')


if __name__ == '__main__':
    main()
