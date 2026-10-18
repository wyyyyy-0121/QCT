#!/usr/bin/env python3
"""Independently score locked E3 outputs and compare 1/8-worker runs."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'e3_contract_v3/outputs'
EXPECTED = ROOT / 'e3_contract_v3/scoring/expected.json'
LOCK = ROOT / 'e3_contract_v3/input_lock.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    lock = json.loads(LOCK.read_text())
    expected = json.loads(EXPECTED.read_text())
    if sha(EXPECTED) != lock['expected_sha256']:
        raise SystemExit('Locked score key changed')
    if sha(ROOT / 'tools/e3_contract.py') != lock['implementation_sha256']:
        raise SystemExit('Frozen implementation changed after input lock')
    if sha(ROOT / 'tools/batch_runner.py') != lock['runner_sha256']:
        raise SystemExit('Frozen batch runner changed after input lock')
    observed_hashes = {}
    summaries = {}
    for workers in (1, 8):
        runtime_path = RUNS / f'workers_{workers}/runtime.json'
        runtime = json.loads(runtime_path.read_text())
        if runtime['worker_count'] != workers or not runtime['all_tasks_complete']:
            raise SystemExit(f'{workers}-worker benchmark incomplete or admission-capped')
        actual = {}
        for row in runtime['tasks']:
            pred_path = RUNS / f'workers_{workers}/tasks/{row["id"]}/prediction.json'
            if row['status'] != 'complete' or not pred_path.is_file():
                raise SystemExit(f'Incomplete prediction: {row["id"]}/{workers}')
            if sha(pred_path) != row['output_sha256']['prediction.json']:
                raise SystemExit(f'Prediction hash mismatch: {row["id"]}/{workers}')
            actual[row['id']] = json.loads(pred_path.read_text())
        observed_hashes[workers] = {case: sha(RUNS / f'workers_{workers}/tasks/{case}/prediction.json')
                                    for case in sorted(expected)}
        summaries[workers] = {
            'wall_seconds': runtime['wall_seconds'],
            'child_cpu_seconds': runtime['child_cpu_seconds'],
            'sampled_peak_aggregate_rss_bytes': runtime['aggregate_peak_rss_bytes_sampled'],
            'throughput_cases_per_second': runtime['throughput_tasks_per_second'],
            'speedup_vs_1_worker': None,
        }
        for case, target in expected.items():
            result = actual[case]
            for key in ('status', 'suggested_formula', 'reason'):
                if result.get(key) != target[key]:
                    raise SystemExit(f'{case}: {key} expected {target[key]!r}, got {result.get(key)!r}')
            if result.get('final_validation_eligible') is not False:
                raise SystemExit(f'{case}: incorrectly marked final-validation eligible')
    if observed_hashes[1] != observed_hashes[8]:
        raise SystemExit('Per-case 1/8 worker output hashes differ')
    if summaries[1]['wall_seconds']:
        summaries[8]['speedup_vs_1_worker'] = summaries[1]['wall_seconds'] / summaries[8]['wall_seconds']

    # Independent Fraction checks; d=1 is intentionally not used to distinguish formulas.
    ratio = lambda q, d: Fraction(q, 1) / Fraction(d, 1)
    affine = lambda q, d: Fraction(q, 1) * (2 - Fraction(d, 1))
    points = [(10, 1), (10, 2), (9, 3), (13, 4)]
    relation_checks = [{'q': q, 'd': d, 'ratio': str(ratio(q, d)),
                        'affine': str(affine(q, d)), 'equal': ratio(q, d) == affine(q, d)}
                       for q, d in points]
    if sum(item['equal'] for item in relation_checks) != 1:
        raise SystemExit('Counterfactual equivalence controls did not distinguish formulas')
    report = {
        'schema': 'hybridguard-e3-independent-score-v1',
        'input_lock_sha256': sha(LOCK), 'expected_key_sha256': sha(EXPECTED),
        'all_eight_conditions_match_preregistered_expectations': True,
        'per_case_prediction_hashes_identical_1_8_workers': observed_hashes[1] == observed_hashes[8],
        'conditions_scored': len(expected), 'accepted_natural_sources': 0,
        'natural_accuracy_claim': False, 'original_model_modified_or_scored': False,
        'multiple_rational_point_checks': relation_checks,
        'resource_measurements': summaries,
        'interpretation': 'Prototype engineering pass only. Candidate selection under supplied constraints; no natural error accuracy, coverage, or model improvement claim.',
    }
    output = ROOT / 'e3_contract_v1/score.json'
    if output.exists():
        raise SystemExit(f'Preserving existing score: {output}')
    output.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
