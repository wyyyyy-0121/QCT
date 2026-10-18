"""Re-evaluate every negative witness and a deterministic positive sample."""
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
import sys
import time
import sympy
from openpyxl import load_workbook
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'qa'), str(ROOT/'scripts'), str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read, save, sha
from build_keep_features_dev21 import BASE, case_path
from prepare_tristate_states_dev23 import DATA, KEEP
from independent_numeric_relations_dev23 import IndependentNumeric


def main():
    wall = time.perf_counter(); lock = read(DATA/'preparation_lock.json')
    assert sha(DATA/'source_lock.json') == lock['source_lock_sha256']
    for rel, value in read(DATA/'source_lock.json')['files'].items(): assert sha(ROOT/rel) == value, rel
    for rel, value in lock['files'].items(): assert sha(DATA/rel) == value, rel
    for rel, value in lock['inputs'].items(): assert sha(ROOT/rel) == value, rel
    assert sha(BASE/'label_preparation_lock.json') == lock['upstream_label_lock_sha256']
    truth = read(BASE/'heldout_truth.json.gz')['cases']; cases = []; totals = Counter(); origins = defaultdict(Counter)
    for item in read(BASE/'public_index.json'):
        case = item['case']; t = truth[case]; expected = t['expected_formulas']
        payload = read(BASE/'features'/(case_path(case)+'.json.gz'))
        states = read(DATA/'author_case_states'/(case_path(case)+'.json.gz'))['alternatives']
        workbook = load_workbook(ROOT/item['input'], data_only=False)
        interpreter = IndependentNumeric(workbook, expected)
        candidates = {c['id']: c for c in payload['candidates']}; counts = Counter()
        assert len(states) == len(candidates)+len({c['cell'] for c in candidates.values()})
        positive_candidates = sorted((s for s in states if s['label'] == 1 and s['kind'] == 'candidate'), key=lambda s:s['id'])
        sample = {s['id'] for s in positive_candidates[:32]}
        for state in states:
            assert state['case'] == case
            cell = state['cell']; sheet, address = cell.rsplit('!', 1)
            if state['kind'] == 'candidate':
                candidate = candidates[state['id']]; assert candidate['cell'] == cell
                formula = candidate['formula']; counts['candidates'] += 1
            else:
                assert state['kind'] == 'keep' and state['id'] == KEEP
                formula = workbook[sheet][address].value; counts['keep'] += 1
            if cell not in expected:
                assert state['label'] is None and state['reason'] == 'outside_reviewed_scope'
            if state['label'] == 0:
                witness = state['witness']; inputs = {name: Fraction(value) for name, value in witness['inputs'].items()}
                left = interpreter.formula(formula, sheet, inputs=inputs, stack=(cell,))
                right = interpreter.formula(expected[cell], sheet, inputs=inputs, stack=(cell,))
                assert left == Fraction(witness['candidate']) and right == Fraction(witness['expected'])
                assert left != right
                counts['negative_witnesses_recomputed'] += 1
            elif state['label'] == 1 and (state['kind'] == 'keep' or state['id'] in sample):
                left = interpreter.formula(formula, sheet, symbolic=True, stack=(cell,))
                right = interpreter.formula(expected[cell], sheet, symbolic=True, stack=(cell,))
                assert sympy.expand(left-right) == 0, (case, cell, formula)
                counts['positive_identities_recomputed'] += 1
            elif state['label'] is None:
                assert 'witness' not in state
            counts['state_'+str(state['label'])] += 1
        assert counts['candidates'] == len(payload['candidates'])
        workbook.close(); totals.update(counts); origins[t['origin_group']].update(counts)
        cases.append(dict(case=case, **dict(counts))); print('independent relation audit', case, dict(counts), flush=True)
    assert len(cases) == 213 and totals['candidates'] == 1861162 and totals['keep'] == 70006
    p = ROOT/'qa/TRISTATE_RELATIONS_DEV23_INDEPENDENT_AUDIT_20261018.json'; assert not p.exists()
    save(p, dict(cases=cases, totals=dict(totals), by_origin={key: dict(value) for key, value in origins.items()},
        all_negative_witnesses_recomputed=True, positive_scope='all positive keep states and first 32 positive candidates by ID per case',
        all_unknown_states_preserved=True, preparation_lock_sha256=sha(DATA/'preparation_lock.json'),
        auditor_sha256=sha(Path(__file__)), independent_interpreter_sha256=sha(ROOT/'qa/independent_numeric_relations_dev23.py'),
        wall_seconds=time.perf_counter()-wall, final_validation_eligible=False, repair_performance_not_estimated=True))
    print('DEV23 INDEPENDENT LABEL AUDIT PASSED', dict(totals), flush=True)


if __name__ == '__main__': main()
