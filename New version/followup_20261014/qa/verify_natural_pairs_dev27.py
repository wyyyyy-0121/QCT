"""Verify immutable acquisition, locked inference and independent natural labels."""
from pathlib import Path
import hashlib
import re
import sys
import openpyxl

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'qa')]
from run_selector_dev5 import read,save,sha
import run_cv500_natural_dev27 as cv
import run_ldas_natural_dev27 as ld


def check_run(runner,expected_count,registration,acquirer):
    runner.engine.RUN=runner.RUN
    # Both wrappers share the immutable underlying worker module in this
    # audit process; verification uses the run's own frozen file list only.
    runner.engine.verify();root=runner.RUN
    a=read(root/'acquisition.json')
    assert a['preregistration_sha256']==sha(ROOT/registration)
    assert a['script_sha256']==sha(ROOT/'qa'/acquirer)
    for r in a['records']:
        data=(ROOT/r['path']).read_bytes();assert r['ok'] and hashlib.sha256(data).hexdigest()==r['sha256']
        assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==r['expected_git_blob']
    p=read(root/'prediction.json.gz');assert p['status']=='complete' and p['formula_cells']==expected_count
    assert p['labels_read']==p['correction_versions_read']==p['parallel_sheets']==[]
    assert len(p['input_accesses'])==1 and p['input_accesses'][0].endswith('/raw/before.xlsx')
    replay=read(root/'replay.json');assert replay['all_predictions_identical']
    assert replay['prediction_lock_sha256']==sha(root/'prediction_lock.json')
    diff=read(root/'author_diff.json.gz');assert diff['literal_ooxml_formula_audit_passed']
    assert diff['original_prediction_lock_sha256']==sha(root/'prediction_lock.json')
    assert diff['author_auditor_sha256']==sha(ROOT/'qa/diff_hobyah_natural_dev26.py')
    return p,diff


def main():
    p,d=check_run(cv,505,'CV500_NATURAL_DEV27_PREREGISTRATION_20261018.md','acquire_cv500_natural_dev27.py')
    root=cv.RUN;a=read(root/'acquisition.json')
    assert a['initial_receipt_sha256']==sha(root/'acquisition_initial_transfer_failure.json')
    assert a['recovery_script_sha256']==sha(ROOT/'qa/recover_cv500_acquisition_dev27.py')
    truth=read(root/'natural_truth.json.gz');score=read(root/'natural_score.json')
    assert truth['certification_script_sha256']==sha(ROOT/'qa/certify_cv500_natural_dev27.py')
    assert truth['author_diff_sha256']==sha(root/'author_diff.json.gz')
    assert truth['source_schema_receipt_sha256']==sha(ROOT/'source_discovery/natural_pair_docs_dev27_20261018/RECEIPT.json')
    assert score['truth_sha256']==sha(root/'natural_truth.json.gz')
    assert len(truth['cases'])==505 and truth['actual_output_mismatch_count']==505
    # Independent direct, string-literal-aware reference rewrite. It must
    # change exactly the unquoted meaning reference, never any quoted HTML.
    for r in truth['cases']:
        row=int(r['cell'].split('!E')[1]);old=r['original_formula'];new=r['accepted_formula']
        chunks=re.split(r'("(?:[^"]|"")*")',old)
        replacements=0
        for i in range(0,len(chunks),2):
            chunks[i],count=re.subn(r'(?<![A-Z0-9_])C'+str(row+1)+r'(?![0-9])',f'C{row}',chunks[i]);replacements+=count
        assert replacements==1 and ''.join(chunks)==new
        assert old==d['before']['formulas'][r['cell']] and new==d['after']['formulas'][r['cell']]
    for mode in ['paper','dev11']:
        assert not [r for r in p[mode]['rows'] if r.get('status')=='propose']
        assert score['metrics'][mode]['errors']==505 and score['metrics'][mode]['coverage']==0
        assert score['metrics'][mode]['precision'] is None
    p2,d2=check_run(ld,299,'LDAS_NATURAL_DEV27_PREREGISTRATION_20261018.md','acquire_ldas_natural_dev27.py')
    semantic=read(ld.RUN/'trial_semantics_audit.json')
    assert semantic['auditor_sha256']==sha(ROOT/'qa/audit_ldas_trial_semantics_dev27.py')
    assert semantic['author_diff_sha256']==sha(ld.RUN/'author_diff.json.gz')
    assert semantic['independent_cached_trial_values_checked']==576 and len(semantic['subject_mask_cases'])==15
    assert semantic['documented_valid_mask_count']==4 and semantic['natural_formula_error_labels_established']==0
    assert len(semantic['actual_first_box_counters_affected'])==72
    # Separately inspect natural input and its original visible limitation.
    w=openpyxl.load_workbook(ld.RUN/'raw/before.xlsx',data_only=False);s=w.active
    assert s['C10'].value is None and 'rightmost' in s['C11'].comment.text
    assert all(s[a].value=='.' for a in ['C11','E11','G11','I11'])
    target=ROOT/'qa/NATURAL_PAIRS_DEV27_VERIFICATION_20261018.json';assert not target.exists()
    save(target,dict(all_checks_passed=True,natural_original_formula_cells=804,original_models_each_replayed=True,
        cv500_confirmed_natural_formula_errors=505,cv500_actual_wrong_outputs=505,
        cv500_paper_precision=None,cv500_paper_coverage=0,cv500_dev11_precision=None,cv500_dev11_coverage=0,
        cv500_all_input_values_unchanged=True,ldas_reliable_formula_error_labels=0,
        ldas_15_masks_exhaustively_checked=True,ldas_576_cached_values_independently_checked=True,
        verified_natural_error_development_pairs=1,accepted_final_sources=0,accepted_final_families=0,
        final_validation_complete=False,goal_status='active',verifier_sha256=sha(Path(__file__))))
    print('DEV27 VERIFIED: one reliable natural-error development pair, 505 missed errors; final counts still zero',flush=True)


if __name__=='__main__':main()
