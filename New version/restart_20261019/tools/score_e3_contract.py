#!/usr/bin/env python3
"""Independently score locked E3 outputs and compare 1/8-worker runs."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys
import argparse

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'e3_contract_v4/outputs'
EXPECTED = ROOT / 'e3_contract_v4/scoring/expected.json'
LOCK = ROOT / 'e3_contract_v4/input_lock.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=None)
    args = parser.parse_args()
    lock = json.loads(LOCK.read_text())
    expected = json.loads(EXPECTED.read_text())
    if sha(EXPECTED) != lock['expected_sha256']:
        raise SystemExit('Locked score key changed')
    manifest_path = LOCK.parent / 'manifest.jsonl'
    if sha(manifest_path) != lock['manifest_sha256']:
        raise SystemExit('Locked task manifest changed')
    for relative, digest in lock['files'].items():
        path = (ROOT / 'source_evidence/raw/epa_pairs/xlsx_export/oxidizers_before.xlsx'
                if relative == 'external:epa_oxidizers_before.xlsx' else LOCK.parent / relative)
        if sha(path) != digest:
            raise SystemExit(f'Locked input changed: {relative}')
    if sha(ROOT / 'tools/e3_contract.py') != lock['implementation_sha256']:
        raise SystemExit('Frozen implementation changed after input lock')
    if sha(ROOT / 'tools/batch_runner.py') != lock['runner_sha256']:
        raise SystemExit('Frozen batch runner changed after input lock')
    if sha(ROOT / 'tools/prepare_e3_contract.py') != lock['input_builder_sha256']:
        raise SystemExit('Frozen input builder changed after input lock')
    no_units = json.loads((LOCK.parent / 'requests/counter_none.json').read_text())
    units_only = json.loads((LOCK.parent / 'requests/counter_units.json').read_text())
    no_units.pop('workbook_sha256')
    units_only.pop('workbook_sha256')
    if no_units['constraints'] != units_only['constraints'] or no_units['symbols'] == units_only['symbols']:
        raise SystemExit('Unit-only control does not differ by unit metadata alone')
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
            prediction = json.loads(pred_path.read_text())
            request_path = LOCK.parent / f'requests/{row["id"]}.json'
            request = json.loads(request_path.read_text())
            if prediction.get('request_sha256') != sha(request_path):
                raise SystemExit(f'{row["id"]}: prediction request hash mismatch')
            if prediction.get('workbook_sha256') != request['workbook_sha256']:
                raise SystemExit(f'{row["id"]}: prediction workbook hash mismatch')
            actual[row['id']] = prediction
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
    output = args.output or LOCK.parent / 'score_independent_v2.json'
    if not output.is_absolute():
        output = LOCK.parent / output
    if output.exists():
        raise SystemExit(f'Preserving existing score: {output}')
    output.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
