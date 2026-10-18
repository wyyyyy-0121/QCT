"""Close the natural-source audit without manufacturing a correction label."""
from pathlib import Path
import hashlib
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'qa')]
from run_selector_dev5 import read, save, sha
from run_hobyah_natural_dev26 import RUN, verify


def main():
    verify()
    acquisition = read(RUN / 'acquisition.json')
    assert acquisition['preregistration_sha256'] == sha(ROOT / 'HOBYAH_NATURAL_DEV26_PREREGISTRATION_20261018.md')
    assert acquisition['license_review_sha256'] == sha(ROOT / 'source_discovery/HOBYAH_LICENSE_REVIEW_DEV26_20261018.md')
    assert acquisition['acquisition_script_sha256'] == sha(ROOT / 'qa/acquire_hobyah_natural_dev26.py')
    assert acquisition['initial_raw_timeout_receipt_sha256'] == sha(RUN / 'acquisition_initial_raw_timeouts.json')
    for receipt in [acquisition, read(RUN / 'odf_acquisition.json')]:
        for row in receipt['records']:
            data = (ROOT / row['path']).read_bytes()
            assert row['ok'] and hashlib.sha256(data).hexdigest() == row['sha256']
            assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == row['expected_git_blob']
    prediction = read(RUN / 'prediction.json.gz')
    assert prediction['status'] == 'complete' and prediction['formula_cells'] == 199
    assert prediction['labels_read'] == prediction['correction_versions_read'] == prediction['parallel_sheets'] == []
    assert len(prediction['input_accesses']) == 1 and prediction['input_accesses'][0].endswith('/raw/before.xlsx')
    for mode in ['paper', 'dev11']:
        assert not [r for r in prediction[mode]['rows'] if r.get('status') == 'propose']
    replay = read(RUN / 'replay.json')
    assert replay['all_predictions_identical'] and replay['prediction_lock_sha256'] == sha(RUN / 'prediction_lock.json')
    diff = read(RUN / 'author_diff.json.gz')
    assert diff['literal_ooxml_formula_audit_passed'] and diff['author_auditor_sha256'] == sha(ROOT / 'qa/diff_hobyah_natural_dev26.py')
    assert len(diff['before']['formulas']) == 199 and len(diff['after']['formulas']) == 202
    assert len(diff['formula_changes']) == 398 and len(diff['all_value_changes']) == 754
    role = read(RUN / 'role_alignment_audit.json')
    assert role['auditor_sha256'] == sha(ROOT / 'qa/audit_hobyah_role_alignment_dev26.py')
    assert role['author_diff_sha256'] == sha(RUN / 'author_diff.json.gz')
    assert role['odf_acquisition_sha256'] == sha(RUN / 'odf_acquisition.json')
    assert not role['current_correction_formula_truth_supported'] and role['verified_error_labels'] == 0
    assert role['precision'] is role['coverage'] is None
    assert len(role['checked_roles']) == 2
    assert all(r['equivalent_after_verified_role_alignment'] and r['claimed_car_area_misuse_absent_in_both_pinned_versions'] for r in role['checked_roles'])
    target = ROOT / 'qa/HOBYAH_NATURAL_DEV26_VERIFICATION_20261018.json'; assert not target.exists()
    save(target, dict(all_checks_passed=True, original_formula_cells=199, corrected_formula_cells=202,
        original_predictions_replayed=True, paper_suggestions=0, dev11_suggestions=0,
        independent_ooxml_formula_inventory_passed=True, shared_formula_translation_crosschecked=True,
        original_and_corrected_odf_roles_crosschecked=True, claimed_terms_already_matching=2,
        reliable_natural_error_pair_established=False, precision=None, coverage=None,
        final_validation_eligible=False, accepted_final_sources=0, accepted_final_families=0,
        prediction_lock_sha256=sha(RUN / 'prediction_lock.json'), role_audit_sha256=sha(RUN / 'role_alignment_audit.json'),
        verifier_sha256=sha(Path(__file__)), goal_status='active'))
    print('DEV26 VERIFIED: no fabricated labels; source correction remains unqualified', flush=True)


if __name__ == '__main__': main()
