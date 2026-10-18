"""Replay every v2 declaration and audit immutable independent-reference evidence."""
from pathlib import Path
from collections import Counter
import hashlib
import sys

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'qa'),
               str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read, save, sha
from run_string_execution_dev28 import RUN as PRIOR, CASES, value_record
from run_string_execution_dev28_v2 import RUN
from hard_reference_string_execution_dev28 import verify_execution, check_provenance
from string_execution_dev28_v2 import execute, parse, Unsupported
from typed_execution_adapter import load_typed_inputs


def main():
    target = ROOT / 'qa/STRING_EXECUTION_DEV28_VERIFICATION_20261018.json'
    assert not target.exists()
    verify_execution()
    lock = read(RUN / 'source_lock.json')
    for rel, digest in {**lock['files'], **lock['local_references']}.items():
        assert sha(ROOT / rel) == digest, rel
    execution_lock = read(RUN / 'execution_lock.json')
    assert execution_lock['source_lock_sha256'] == sha(RUN / 'source_lock.json')
    assert execution_lock['execution_sha256'] == sha(RUN / 'execution.json.gz')
    assert lock['prior_execution_lock_sha256'] == sha(PRIOR / 'execution_lock.json')
    assert lock['prior_hard_reference_sha256'] == sha(PRIOR / 'hard_recalculation_reference.json')
    prior_ref = read(PRIOR / 'hard_recalculation_reference.json')
    for rel, digest in read(PRIOR / 'hard_reference_source_lock.json')['files'].items():
        assert sha(ROOT / rel) == digest, rel
    assert prior_ref['source_lock_sha256'] == sha(PRIOR / 'hard_reference_source_lock.json')
    assert prior_ref['forced_calculate_all'] and prior_ref['read_only'] and not prior_ref['workbook_saved']
    assert prior_ref['exact_text_agreements'] == 505
    assert prior_ref['smoke']['executed'] == 18 and prior_ref['smoke']['agreements'] == 17
    mismatch = [r for r in prior_ref['smoke']['rows'] if r.get('exact_agreement') is False]
    assert len(mismatch) == 1 and mismatch[0]['cell'] == 'B3'
    assert not prior_ref['preserved_conversion_only_diagnostic']['accepted_as_recalculation_evidence']
    frozen = read(RUN / 'execution.json.gz')
    assert frozen['labels_read'] == frozen['reference_outputs_read'] == []
    assert not frozen['repair_suggestions_generated'] and not frozen['final_validation_eligible']
    expected_paths = {str(p) for _, p in CASES} | {str(PRIOR / 'local/hard_reference_smoke.xlsx')}
    assert set(frozen['input_accesses']) == expected_paths
    paths = dict(CASES + [('smoke', PRIOR / 'local/hard_reference_smoke.xlsx')])
    checked = 0
    for case in frozen['cases']:
        path = paths[case['case']]
        book = openpyxl.load_workbook(path, data_only=False)
        typed = load_typed_inputs(path)
        formulas = {(s.title, c.coordinate): c.value for s in book for row in s for c in row if c.data_type == 'f'}
        assert len(formulas) == case['formulas'] == len(case['cells'])
        for r in case['cells']:
            sheet, address = r['cell'].rsplit('!', 1)
            formula = formulas[(sheet, address)]
            assert r['formula_sha256'] == hashlib.sha256(formula.encode()).hexdigest()
            try:
                node = parse(formula)
                references = check_provenance(formula, sheet)
                value = execute(node, sheet, typed, formulas, book.sheetnames)
                assert r['status'] == 'executed' and r['value'] == value_record(value)
                assert r['independent_references_checked'] == references
            except Unsupported as error:
                assert r['status'] == 'unsupported' and r['reason'] == error.code
            checked += 1
        assert case['counts'] == dict(Counter(
            r['reason'] if r['status'] == 'unsupported' else 'executed' for r in case['cells']))
    assert checked == 1027
    independent = read(RUN / 'independent_reference.json')
    assert independent['execution_lock_sha256'] == sha(RUN / 'execution_lock.json')
    assert independent['exact_agreements'] == independent['compared'] == 522
    inventory = {(case['case'], r['cell']): r for case in frozen['cases'] for r in case['cells']}
    references = {'cv500': read(PRIOR / 'local/hard_reference_cv500_uno.json.gz'),
                  'smoke': read(PRIOR / 'local/hard_reference_smoke_uno.json.gz')}
    for case, reference in references.items():
        assert reference['forced_calculate_all'] and reference['read_only'] and not reference['workbook_saved']
        expected = {key for key, row in inventory.items() if key[0] == case and row['status'] == 'executed'}
        got = {(r['case'], r['cell']) for r in independent['rows'] if r['case'] == case}
        assert expected == got
        for key in expected:
            raw = reference['cells'][key[1]]
            record = inventory[key]['value']
            if raw['kind'] == 'text':
                assert record['kind'] == 'text'
                assert record['sha256'] == hashlib.sha256(raw['value'].encode()).hexdigest()
            elif raw['kind'] == 'error':
                assert record['kind'] == 'error' and record['error'] == raw['error']
            else:
                assert raw['kind'] == 'number' and record['kind'] in ('int', 'float')
                assert record['value'] == raw['value']
    # Old original-model and learning experiment source/prediction locks remain intact.
    from run_selector_dev11 import verify as verify11
    from run_absolute_selection_dev24 import verify as verify24
    from run_nested_calibration_dev25 import verify as verify25
    from run_hobyah_natural_dev26 import verify as verify26
    verify11(); verify24(); verify25(); verify26()
    from verify_natural_pairs_dev27 import check_run
    import run_cv500_natural_dev27 as cv
    import run_ldas_natural_dev27 as ld
    check_run(cv, 505, 'CV500_NATURAL_DEV27_PREREGISTRATION_20261018.md', 'acquire_cv500_natural_dev27.py')
    check_run(ld, 299, 'LDAS_NATURAL_DEV27_PREREGISTRATION_20261018.md', 'acquire_ldas_natural_dev27.py')
    full = (ROOT / 'qa/STRING_EXECUTION_DEV28_V2_FULL_TESTS_20261018.log').read_text()
    assert 'Ran 272 tests' in full and full.rstrip().endswith('OK')
    save(target, dict(all_checks_passed=True, declarations_replayed=checked,
         original_declarations=1003, original_executed=505, original_unsupported=498,
         original_text_exact_matches=505, smoke_declarations=24, smoke_exact_matches=17, smoke_unsupported=7,
         independent_compared=522, independent_exact_agreements=522,
         full_tests_passed=272, v1_boolean_smoke_failure_preserved=True,
         conversion_only_diagnostic_rejected_as_recalculation_evidence=True,
         old_dev11_dev24_dev25_dev26_dev27_locks_unchanged=True,
         main_candidate_changed=False, performance_improvement_established=False,
         accepted_final_sources=0, accepted_final_families=0, goal_status='active',
         final_validation_complete=False, verifier_sha256=sha(Path(__file__)),
         execution_lock_sha256=sha(RUN / 'execution_lock.json'),
         independent_reference_sha256=sha(RUN / 'independent_reference.json')))
    print('DEV28 VERIFIED: 1027 declarations replayed, 522 independent matches, 505 unsupported retained;',
          '272 tests; old locks unchanged; repair metrics unchanged', flush=True)


if __name__ == '__main__':
    main()
