"""Check all completed dev22 evidence before publishing the result."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read, save, sha
from run_certified_learning_dev22 import RUN, LABELS, verify, verify_preparation
from run_relative_learning_dev21 import verify as verify21


def main():
    verify(); verify21(); verify_preparation(include_label_bodies=True)
    evidence = {name: ROOT/('qa/CERTIFIED_LEARNING_DEV22_'+name+'_20261018.json')
                for name in ['PRETRAIN_AUDIT', 'RUNTIME_AUDIT', 'INDEPENDENT_COUNTS', 'REPLAY', 'MISS_DIAGNOSIS']}
    data = {name: read(path) for name, path in evidence.items()}
    for key in ['PRETRAIN_AUDIT', 'RUNTIME_AUDIT']:
        assert data[key]['pairs_match_independent_reconstruction']
        assert data[key]['all_case_states_match_independent_upstream_mapping']
        assert data[key]['wrong_wrong_and_unknown_pairs_absent']
        assert data[key]['source_balancing_verified'] and data[key]['mirrored_weights_equal']
        assert data[key]['audit_source_sha256'] == sha(ROOT/'qa/audit_certified_training_dev22.py')
        assert data[key]['preparation_lock_sha256'] == sha(LABELS/'preparation_lock.json')
        assert len(data[key]['folds']) == 5
    assert data['REPLAY']['cases'] == 213 and data['REPLAY']['all_probabilities_and_suggestions_identical']
    assert data['REPLAY']['labels_read'] == []
    assert data['INDEPENDENT_COUNTS']['integer_count_checks'] == 5964
    assert data['INDEPENDENT_COUNTS']['all_counts_identical']
    for key in ['REPLAY', 'INDEPENDENT_COUNTS', 'MISS_DIAGNOSIS']:
        assert data[key]['prediction_lock_sha256'] == sha(RUN/'prediction_lock.json')
    for key, script in [('INDEPENDENT_COUNTS', 'audit_certified_results_dev22.py'),
                        ('MISS_DIAGNOSIS', 'diagnose_certified_learning_dev22.py')]:
        assert data[key]['audit_source_sha256'] == sha(ROOT/'qa'/script)
    log = ROOT/'qa/CERTIFIED_LEARNING_DEV22_STRICT_FULL_TESTS_20261018.log'
    assert 'Ran 225 tests' in log.read_text() and log.read_text().rstrip().endswith('OK')
    score = read(RUN/'score.json'); assert len(score['cases']) == 213
    assert not score['final_validation_eligible'] and not score['main_candidate_adopted']
    target = ROOT/'qa/CERTIFIED_LEARNING_DEV22_VERIFICATION_20261018.json'; assert not target.exists()
    result = dict(all_saved_checks_passed=True, cases=213, tests_passed=225, integer_count_checks=5964,
        prediction_lock_sha256=sha(RUN/'prediction_lock.json'), score_sha256=sha(RUN/'score.json'),
        evidence_sha256={str(path.relative_to(ROOT)): sha(path) for path in evidence.values()},
        verifier_sha256=sha(Path(__file__)), historical_dev21_locks_verified=True,
        final_validation_eligible=False, main_candidate_adopted=False, goal_status='active',
        accepted_final_sources=0, accepted_final_families=0)
    save(target, result); print(result, flush=True)


if __name__ == '__main__': main()
