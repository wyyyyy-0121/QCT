"""Bind audited supervision, locked fits, replay and independent score evidence."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from run_absolute_selection_dev24 import RUN,LABELS,BASE,ARMS,MODES,verify
from run_certified_learning_dev22 import verify as verify22


def main():
    verify22();verify()
    audit=read(ROOT/'qa/ABSOLUTE_SELECTION_DEV24_TRAINING_AUDIT_RUNTIME_20261018.json')
    assert audit['all_options_and_pairs_independently_rebuilt'] and audit['runtime_checked'] and audit['all_weights_verified']
    assert audit['preparation_lock_sha256']==sha(LABELS/'preparation_lock.json')
    assert audit['auditor_sha256']==sha(ROOT/'qa/audit_absolute_training_dev24.py')
    replay=read(ROOT/'qa/ABSOLUTE_SELECTION_DEV24_REPLAY_20261018.json')
    assert replay['cases_by_arm']=={'absolute':213,'relative':213} and replay['all_probabilities_and_suggestions_identical']
    assert replay['labels_read']==[] and replay['prediction_lock_sha256']==sha(RUN/'prediction_lock.json')
    counts=read(ROOT/'qa/ABSOLUTE_SELECTION_DEV24_INDEPENDENT_COUNTS_20261018.json')
    assert counts['all_counts_and_strata_identical'] and counts['integer_count_checks']==11928
    assert counts['auditor_sha256']==sha(ROOT/'qa/audit_absolute_results_dev24.py')
    assert counts['prediction_lock_sha256']==sha(RUN/'prediction_lock.json') and counts['score_sha256']==sha(RUN/'score.json')
    diagnostic=read(ROOT/'qa/ABSOLUTE_SELECTION_DEV24_DIAGNOSTICS_20261018.json')
    assert diagnostic['prediction_lock_sha256']==sha(RUN/'prediction_lock.json') and not diagnostic['parameters_changed']
    for arm in ARMS:assert sum(diagnostic['all'][arm].values())==18073
    collisions=read(ROOT/'qa/ABSOLUTE_SELECTION_DEV24_FEATURE_COLLISIONS_20261018.json')
    assert collisions['all']['options']==813899 and not collisions['heldout_labels_used_for_model']
    assert collisions['auditor_sha256']==sha(ROOT/'qa/audit_absolute_feature_collisions_dev24.py')
    assert collisions['prediction_lock_sha256']==sha(RUN/'prediction_lock.json')
    log=(ROOT/'qa/ABSOLUTE_SELECTION_DEV24_FULL_TESTS_20261018.log').read_text()
    assert 'Ran 249 tests' in log and log.rstrip().endswith('OK')
    assert 'rebuilt dev24 exact' in (ROOT/'qa/ABSOLUTE_SELECTION_DEV24_REBUILD_CHECK_20261018.log').read_text()
    runtime=read(RUN/'runtime.json');assert len(runtime['folds'])==10 and not runtime['gpu_used']
    score=read(RUN/'score.json')
    for arm in ARMS:
        assert len(score['arms'][arm]['cases'])==213
        for mode in MODES:assert score['arms'][arm]['all'][mode]['errors']==18073
    assert not score['final_validation_eligible'] and not score['main_candidate_adopted']
    target=ROOT/'qa/ABSOLUTE_SELECTION_DEV24_VERIFICATION_20261018.json';assert not target.exists()
    save(target,dict(all_checks_passed=True,arms=ARMS,cases_per_arm=213,models=10,tests_passed=249,
        integer_count_checks=11928,full_probability_replay=True,training_labels_independently_rebuilt=True,
        original_dev22_lock_verified=True,prediction_lock_sha256=sha(RUN/'prediction_lock.json'),
        score_sha256=sha(RUN/'score.json'),verifier_sha256=sha(Path(__file__)),
        accepted_final_sources=0,accepted_final_families=0,goal_status='active',final_validation_complete=False))
    print('DEV24 CHECKPOINT VERIFIED',flush=True)


if __name__=='__main__':main()
