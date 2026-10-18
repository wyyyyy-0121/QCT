"""Verify certificate evidence, independent audit, transitions and old locks."""
from collections import Counter, defaultdict
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read, save, sha
from run_certified_learning_dev22 import verify as verify22
from prepare_tristate_states_dev23 import DATA
from build_keep_features_dev21 import BASE, case_path


def main():
    verify22(); lock = read(DATA/'preparation_lock.json')
    assert sha(DATA/'source_lock.json') == lock['source_lock_sha256']
    for rel, value in read(DATA/'source_lock.json')['files'].items(): assert sha(ROOT/rel) == value, rel
    for rel, value in lock['files'].items(): assert sha(DATA/rel) == value, rel
    for rel, value in lock['inputs'].items(): assert sha(ROOT/rel) == value, rel
    assert lock['old_repair_labels_and_scores_unchanged'] and not lock['final_validation_eligible']
    audit_path = ROOT/'qa/TRISTATE_RELATIONS_DEV23_INDEPENDENT_AUDIT_20261018.json'
    audit = read(audit_path)
    assert audit['preparation_lock_sha256'] == sha(DATA/'preparation_lock.json')
    assert audit['auditor_sha256'] == sha(ROOT/'qa/audit_tristate_states_dev23.py')
    assert audit['independent_interpreter_sha256'] == sha(ROOT/'qa/independent_numeric_relations_dev23.py')
    summaries = read(DATA/'state_counts.json'); counts = Counter(); reasons = Counter(); transitions = Counter(); origins = defaultdict(Counter)
    audit_cases = {r['case']: r for r in audit['cases']}
    for item in read(BASE/'public_index.json'):
        case = item['case']; payload = read(BASE/'features'/(case_path(case)+'.json.gz'))
        states = read(DATA/'author_case_states'/(case_path(case)+'.json.gz'))['alternatives']
        candidates = [r for r in states if r['kind'] == 'candidate']; keeps = [r for r in states if r['kind'] == 'keep']
        assert len(states) == len({(r['cell'], r['id']) for r in states})
        assert {r['id'] for r in candidates} == {r['id'] for r in payload['candidates']}
        assert {r['cell'] for r in keeps} == {r['cell'] for r in payload['candidates']}
        assert len(candidates) == len(payload['candidates'])
        c = Counter(str(r['label']) for r in states)
        for value in ['0', '1', 'None']: assert c[value] == audit_cases[case].get('state_'+value, 0)
    for row in summaries:
        counts.update(row['counts']); reasons.update(row['reasons']); transitions.update(row['old_repair_to_relation_states'])
        origins[row['source']].update(row['counts'])
    assert len(summaries) == len(audit_cases) == 213
    assert sum(row['candidates'] for row in summaries) == 1861162
    assert sum(row['targets'] for row in summaries) == 70006
    negative = sum(value for key, value in counts.items() if key.endswith('_0'))
    positive = sum(value for key, value in counts.items() if key.endswith('_1'))
    unknown = sum(value for key, value in counts.items() if key.endswith('_unknown'))
    assert negative == audit['totals']['negative_witnesses_recomputed'] == audit['totals']['state_0']
    assert positive == audit['totals']['state_1'] and unknown == audit['totals']['state_None']
    assert negative+positive+unknown == 1861162+70006
    log = ROOT/'qa/TRISTATE_RELATIONS_DEV23_FULL_TESTS_20261018.log'
    independent_log = ROOT/'qa/TRISTATE_RELATIONS_DEV23_INDEPENDENT_INTERPRETER_TESTS_V2_20261018.log'
    for p, n in [(log, 237), (independent_log, 3)]:
        assert f'Ran {n} tests' in p.read_text() and p.read_text().rstrip().endswith('OK')
    p = ROOT/'qa/TRISTATE_RELATIONS_DEV23_VERIFICATION_20261018.json'; assert not p.exists()
    result = dict(all_saved_checks_passed=True, cases=213, candidates=1861162, keep_targets=70006,
        counts=dict(counts), reasons=dict(reasons), old_repair_to_relation_states=dict(transitions),
        by_origin={key: dict(value) for key, value in origins.items()}, negative_witnesses_recomputed=negative,
        positive_identities_recomputed=audit['totals']['positive_identities_recomputed'],
        clean_targets_with_certified_negative=sum(row['clean_targets_with_certified_negative'] for row in summaries),
        targets_with_certified_contrast=sum(row['targets_with_certified_contrast'] for row in summaries),
        research_tests_passed=237, independent_interpreter_tests_passed=3,
        preparation_lock_sha256=sha(DATA/'preparation_lock.json'), audit_sha256=sha(audit_path),
        verifier_sha256=sha(Path(__file__)), historical_dev22_locks_verified=True,
        model_trained=False, repair_performance_not_estimated=True,
        accepted_final_sources=0, accepted_final_families=0, final_validation_eligible=False, goal_status='active')
    save(p, result); print('DEV23 VERIFIED', negative, positive, unknown, flush=True)


if __name__ == '__main__': main()
