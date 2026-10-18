"""Full nested evidence checkpoint; final acceptance remains incomplete."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from run_nested_calibration_dev25 import RUN,INNER,OUTER,LABELS,verify,MODES
from run_absolute_selection_dev24 import verify as verify24


def main():
    verify24();verify()
    training=read(ROOT/'qa/NESTED_CALIBRATION_DEV25_TRAINING_AUDIT_RUNTIME_20261018.json')
    assert training['runtime_checked'] and training['all_nested_origin_exclusions_verified'] and training['all_pairs_and_weights_independently_rebuilt']
    assert training['preparation_lock_sha256']==sha(LABELS/'preparation_lock.json')
    assert training['auditor_sha256']==sha(ROOT/'qa/audit_nested_training_dev25.py')
    calibration=read(ROOT/'qa/NESTED_CALIBRATION_DEV25_CALIBRATION_AUDIT_20261018.json')
    assert calibration['independent_pava_matches'] and calibration['all_nested_top_rows_reconstructed'] and calibration['all_training_only_repair_labels_verified']
    assert calibration['auditor_sha256']==sha(ROOT/'qa/audit_nested_calibration_dev25.py')
    assert calibration['prediction_lock_sha256']==sha(OUTER/'prediction_lock.json')
    for stage,count,folder in [('INNER',852,INNER),('OUTER',213,OUTER)]:
        replay=read(ROOT/('qa/NESTED_CALIBRATION_DEV25_'+stage+'_REPLAY_20261018.json'))
        assert replay['cases']==count and replay['labels_read']==[] and replay['all_probabilities_top_and_suggestions_identical']
        assert replay['prediction_lock_sha256']==sha(folder/'prediction_lock.json')
    counts=read(ROOT/'qa/NESTED_CALIBRATION_DEV25_INDEPENDENT_COUNTS_20261018.json')
    assert counts['integer_count_checks']==7455 and counts['all_counts_strata_ratios_and_NA_identical']
    assert counts['score_sha256']==sha(RUN/'score.json') and counts['prediction_lock_sha256']==sha(OUTER/'prediction_lock.json')
    assert counts['auditor_sha256']==sha(ROOT/'qa/audit_nested_results_dev25.py')
    diagnostic=read(ROOT/'qa/NESTED_CALIBRATION_DEV25_DIAGNOSTICS_20261018.json')
    assert sum(diagnostic['all'].values())==18073 and not diagnostic['parameters_changed']
    for path,count in [('qa/NESTED_CALIBRATION_DEV25_FULL_TESTS_20261018.log',259),('qa/NESTED_CALIBRATION_DEV25_PAVA_TESTS_20261018.log',2)]:
        text=(ROOT/path).read_text();assert f'Ran {count} tests' in text and text.rstrip().endswith('OK')
    assert 'rebuilt nested exact' in (ROOT/'qa/NESTED_CALIBRATION_DEV25_REBUILD_CHECK_20261018.log').read_text()
    score=read(RUN/'score.json');assert score['original_dev24_predictions_identical'] and not score['final_validation_eligible']
    assert len(score['cases'])==213
    for mode in MODES:assert score['all'][mode]['errors']==18073
    target=ROOT/'qa/NESTED_CALIBRATION_DEV25_VERIFICATION_20261018.json';assert not target.exists()
    save(target,dict(all_checks_passed=True,inner_models_trained=10,frozen_outer_rankers_reused=5,
        inner_cases_replayed=852,outer_cases_replayed=213,tests_passed=259,independent_pava_tests_passed=2,
        integer_count_checks=7455,independent_training_and_calibration_audits_passed=True,
        prediction_lock_sha256=sha(OUTER/'prediction_lock.json'),score_sha256=sha(RUN/'score.json'),
        historical_dev24_locks_verified=True,verifier_sha256=sha(Path(__file__)),
        accepted_final_sources=0,accepted_final_families=0,goal_status='active',final_validation_complete=False))
    print('DEV25 CHECKPOINT VERIFIED',flush=True)


if __name__=='__main__':main()
