"""Verify the actual saved dev21 evidence and comparison before reporting."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from run_relative_learning_dev21 import RUN, BASE, DATA, verify, case_path
from run_selector_dev5 import read, save, sha


def main():
    verify()
    checks = {}
    names = ['REPLAY', 'FEATURE_REPLAY', 'INDEPENDENT_COUNTS', 'TRAINING_AUDIT', 'IDENTIFIABILITY', 'MISS_DIAGNOSIS']
    evidence = {n: ROOT/'qa'/('RELATIVE_LEARNING_DEV21_'+n+'_20261018.json') for n in names}
    q = {n: read(p) for n, p in evidence.items()}
    assert q['REPLAY']['cases'] == q['FEATURE_REPLAY']['cases'] == 213
    assert q['REPLAY']['all_probabilities_and_suggestions_identical']
    assert q['FEATURE_REPLAY']['all_keep_features_identical']
    assert q['REPLAY']['labels_read'] == q['FEATURE_REPLAY']['labels_read'] == []
    assert q['INDEPENDENT_COUNTS']['all_counts_identical']
    assert q['INDEPENDENT_COUNTS']['integer_count_checks'] == 5964
    assert q['TRAINING_AUDIT']['all_positive_candidates_preserved']
    assert q['TRAINING_AUDIT']['all_unknown_candidates_excluded']
    assert q['TRAINING_AUDIT']['all_source_weight_checks_passed']
    assert len(q['TRAINING_AUDIT']['folds']) == 5
    sources = {'TRAINING_AUDIT': 'qa/audit_relative_training_dev21.py',
               'IDENTIFIABILITY': 'qa/audit_dev21_feature_identifiability.py',
               'MISS_DIAGNOSIS': 'scripts/diagnose_relative_learning_dev21.py'}
    for key, source in sources.items():
        assert q[key]['audit_source_sha256'] == sha(ROOT/source)
    for key in names:
        if 'prediction_lock_sha256' in q[key]:
            assert q[key]['prediction_lock_sha256'] == sha(RUN/'prediction_lock.json')
    lock = read(RUN/'prediction_lock.json')
    expected_reads = sorted(str((BASE/f['train_label_file']).resolve()) for f in read(BASE/'fold_index.json')['folds'])
    assert lock['training_labels_read'] == expected_reads and lock['heldout_labels_read'] == []
    score = read(RUN/'score.json')
    control = read(ROOT/'development/unit_learning_dev20_v1/score.json')
    additions = {}
    for version in ['unit_learning_dev20_v1', 'relative_learning_dev21_v1']:
        rows = set()
        for fold in read(BASE/'fold_index.json')['folds']:
            for case in fold['test_cases']:
                p = ROOT/'development'/version/'predictions'/fold['id']/(case_path(case)+'.json.gz')
                for r in read(p)['learned_only']:
                    rows.add((case, r['cell'], r['suggested_formula']))
        additions[version] = rows
    a, b = additions.values()
    assert len(a) == 7 and len(b) == 6 and b < a
    assert score['all']['keep_base_plus_learned']['correct'] == control['all']['keep_base_plus_learned']['correct']-1
    assert score['all']['keep_base_plus_learned']['wrong'] == control['all']['keep_base_plus_learned']['wrong'] == 29
    assert not score['main_candidate_adopted'] and not score['final_validation_eligible']
    test_log = ROOT/'qa/RELATIVE_LEARNING_DEV21_RECOVERY_TESTS_20261018.log'
    assert 'Ran 214 tests' in test_log.read_text() and test_log.read_text().rstrip().endswith('OK')
    target_count = sum(c['targets'] for c in read(DATA/'runtime.json')['cases'])
    assert target_count == 70006
    receipt = {'all_saved_checks_passed': True, 'cases': 213, 'candidate_count': 1861162,
               'keep_formula_targets': target_count, 'tests_passed': 214, 'integer_count_checks': 5964,
               'prediction_lock_sha256': sha(RUN/'prediction_lock.json'), 'score_sha256': sha(RUN/'score.json'),
               'evidence_sha256': {str(p.relative_to(ROOT)): sha(p) for p in evidence.values()},
               'test_log_sha256': sha(test_log), 'verifier_sha256': sha(Path(__file__)),
               'lost_vs_dev20': [list(r) for r in sorted(a-b)], 'new_vs_dev20': [],
               'main_candidate_adopted': False, 'final_validation_eligible': False,
               'goal_status': 'active', 'accepted_final_sources': 0, 'accepted_final_families': 0}
    p = ROOT/'qa/RELATIVE_LEARNING_DEV21_VERIFICATION_20261018.json'
    assert not p.exists()
    save(p, receipt)
    print(receipt)


if __name__ == '__main__':
    main()
