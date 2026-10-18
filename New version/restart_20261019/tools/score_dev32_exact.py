#!/usr/bin/env python3
"""Keep the paper's full-formula exact-match metric beside relation scoring."""
from collections import defaultdict
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT.parent / 'followup_20261014'
sys.path[:0] = [str(LEGACY / 'scripts'), str(LEGACY / 'qa'),
               str(LEGACY / 'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read, save, sha
from run_conditioned_relations_dev32 import RUN, MODES, OLD, PRIOR, verify


def main():
    target = ROOT / 'DEV32_EXACT_MATCH_SCORE.json'
    if target.exists():
        raise SystemExit('Preserve exact-match audit')
    verify()
    lock = read(RUN / 'prediction_lock.json')
    for rel, digest in lock['files'].items():
        assert sha(RUN / rel) == digest
    old = read(OLD / 'heldout_truth.json.gz')['cases']
    controls = {r['case']: r for r in read(RUN / 'control_truth.json')['cases']}
    prior = {r['case']: r for r in read(PRIOR / 'control_truth.json')['cases']}
    string = {r['id']: r for r in read(LEGACY / 'development/record_candidates_dev29_v1/controls_truth.json.gz')['cases']}
    natural = {r['cell']: r['accepted_formula'] for r in read(LEGACY / 'development/natural_cv500_dev27_v1/natural_truth.json.gz')['cases']}
    groups = defaultdict(lambda: defaultdict(lambda: dict(suggestions=0, correct=0, errors=0, unknown=0)))
    for item in read(RUN / 'public_index.json'):
        case, stratum = item['case'], item['stratum']
        if stratum == 'old213':
            truth = old[case]
        elif stratum == 'conditioned_control':
            truth = controls[case]
        elif stratum == 'new_control':
            truth = prior[case]
        elif stratum == 'string_control':
            row = string[item['id']]
            truth = dict(expected_formulas=row['all_expected'], errors=row['errors'])
        elif stratum == 'natural_original' and item['id'] == 'cv500':
            truth = dict(expected_formulas=natural, errors=list(natural))
        else:
            truth = {}
        expected, errors = truth.get('expected_formulas', {}), set(truth.get('errors', []))
        prediction = read(RUN / 'predictions' / (case.replace('/', '__') + '.json.gz'))
        for mode in MODES:
            rows = prediction[mode]
            assert len({row['cell'] for row in rows}) == len(rows)
            total = groups[stratum][mode]
            total['errors'] += len(errors)
            total['suggestions'] += len(rows)
            total['unknown'] += sum(row['cell'] not in expected for row in rows)
            total['correct'] += sum(row['cell'] in errors and row['suggested_formula'] == expected[row['cell']]
                                    for row in rows)
    for modes in groups.values():
        for total in modes.values():
            total.update(precision=total['correct'] / total['suggestions'] if total['suggestions'] else None,
                         coverage=total['correct'] / total['errors'] if total['errors'] else None)
    save(target, dict(metric='full formula text including equals; no execution-value or algebraic equivalence credit',
        prediction_lock_sha256=sha(RUN / 'prediction_lock.json'), by_stratum=dict(groups),
        final_validation_eligible=False))
    print(json.dumps(dict(groups), indent=2))


if __name__ == '__main__':
    main()
