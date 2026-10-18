"""Independent replay and integrity checks for the dev32 development run.

This verifier runs only after prediction and scoring.  It checks the immutable
locks, replays every prediction, and rebuilds the per-case metrics from the
stored labels.  The controls remain development evidence and are never marked
as final validation data.
"""
from pathlib import Path
import math
import json
import os
import re
import sys

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'qa'),
               str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read, save, sha
from run_conditioned_relations_dev32 import RUN, MODES, prediction, verify, PRIOR, OLD
from run_visible_relations_dev30 import totals
from relation_algebra_dev30 import equivalent as fraction_equivalent
from formulaguard.workbook import WorkbookModel
from run_public_execution_audit import run_worker
from hard_reference_string_execution_dev28 import reference_value


def execution_witnesses(index, predictions, controls):
    """Independent numeric output evidence, never a business-intent oracle."""
    book = openpyxl.Workbook(); book.remove(book.active)
    queries, pairs = [], []
    for ordinal, item in enumerate(i for i in index if i['stratum'] == 'conditioned_control'):
        source = openpyxl.load_workbook(ROOT / item['input'])
        names = {s.title: f'c{ordinal}_{s.title}' for s in source}
        def rename(formula):
            for old, new in names.items():
                formula = formula.replace("'" + old.replace("'", "''") + "'!", "'" + new + "'!")
                formula = formula.replace(old + '!', "'" + new + "'!")
            return formula
        for original in source:
            target = book.create_sheet(names[original.title])
            for row in original:
                for cell in row:
                    if cell.value is not None:
                        target[cell.coordinate] = rename(cell.value) if cell.data_type == 'f' else cell.value
        for number, row in enumerate(predictions[item['case']]['conditioned_only'], 2):
            sheet, address = row['cell'].rsplit('!', 1)
            target = book[names[sheet]]
            candidate_address = 'AZ' + str(number)
            assert target[candidate_address].value is None
            target[candidate_address] = rename(row['suggested_formula'])
            original_label = names[sheet] + '!' + address
            candidate_label = names[sheet] + '!' + candidate_address
            queries += [original_label, candidate_label]
            pairs.append(dict(case=item['case'], cell=row['cell'], original=original_label,
                              candidate=candidate_label, labelled_error=row['cell'] in controls[item['case']]['errors'],
                              original_expected=row['evidence']['original_execution']['value']['value'],
                              candidate_expected=row['evidence']['candidate_execution']['value']['value']))
        source.close()
    path = RUN / 'control_execution_witness.xlsx'; assert not path.exists()
    book.save(path); before = sha(path)
    reference = run_worker(path, queries, timeout=60)
    save(RUN / 'control_execution_reference.json.gz', reference)
    assert reference['status'] == 'complete', reference
    assert reference['forced_calculate_all'] and reference['read_only'] and not reference['workbook_saved']
    assert sha(path) == before
    rows = []
    for pair in pairs:
        a, b = [reference_value(reference['cells'][pair[k]]) for k in ['original', 'candidate']]
        assert type(a) in (int, float) and type(b) in (int, float)
        assert math.isclose(a, pair['original_expected'], rel_tol=1e-9, abs_tol=1e-8), pair
        assert math.isclose(b, pair['candidate_expected'], rel_tol=1e-9, abs_tol=1e-8), pair
        rows.append(dict(**pair, original_reference=a, candidate_reference=b,
                         output_changed=not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-10)))
    save(RUN / 'control_execution_impact.json', dict(rows=rows, original_inputs_unchanged=True,
         witness_sha256=before, reference_sha256=sha(RUN / 'control_execution_reference.json.gz'),
         business_intent_not_supplied_by_reference=True))
    return dict(checked_suggestions=len(rows), checked_results=2 * len(rows),
                changed_outputs=sum(r['output_changed'] for r in rows),
                legal_outputs_changed=sum(r['output_changed'] and not r['labelled_error'] for r in rows))


def ratio(num, den):
    return num / den if den else None


def main():
    target = ROOT / 'qa/CONDITIONED_RELATIONS_DEV32_VERIFICATION_20261018.json'
    assert not target.exists()
    verify()
    prep = read(RUN / 'preparation_lock.json')
    lock = read(RUN / 'prediction_lock.json')
    score = read(RUN / 'score.json')
    assert lock['source_lock_sha256'] == sha(RUN / 'source_lock.json')
    assert lock['preparation_lock_sha256'] == sha(RUN / 'preparation_lock.json')
    assert lock['labels_read'] == []
    for rel, digest in lock['files'].items():
        assert sha(RUN / rel) == digest, rel
    assert score['prediction_lock_sha256'] == sha(RUN / 'prediction_lock.json')
    assert score['control_truth_sha256'] == sha(RUN / 'control_truth.json')
    assert prep['control_truth_sha256'] == sha(RUN / 'control_truth.json')
    assert score['old_truth_sha256'] == sha(OLD / 'heldout_truth.json.gz')
    index = read(RUN / 'public_index.json')
    assert len(index) == 277
    assert sum(i['stratum'] == 'conditioned_control' for i in index) == 26

    # Replay is isolated from labels and must reproduce every locked artifact.
    active, accesses = [True], set()
    def guard(event, args):
        if not active[0] or event != 'open' or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        path = os.fsdecode(args[0])
        if any(x in path.lower() for x in ['truth', 'training_labels', 'author_diff',
                                            'product_sum_oracle', 'natural_pair_docs', 'natural_score',
                                            'after.xlsx', '_uno.json']):
            raise PermissionError('DEV32 replay cannot read scoring evidence: ' + path)
        if path.endswith(('.xlsx', '.xlsm')):
            accesses.add(path)
    sys.addaudithook(guard)
    predictions = {}
    for item in index:
        path = RUN / 'predictions' / (item['case'].replace('/', '__') + '.json.gz')
        prior = read(path)
        # JSON locks store coordinate tuples as arrays. Compare the same
        # serialization representation rather than rejecting tuple/list types.
        current = json.loads(json.dumps(prediction(item)))
        assert prior == current, item['case']
        predictions[item['case']] = prior
        print('DEV32 REPLAY', item['case'], len(prior['conditioned_only']), flush=True)
    active[0] = False
    assert accesses == set(lock['input_accesses'])

    controls = {r['case']: r for r in read(RUN / 'control_truth.json')['cases']}
    old = read(OLD / 'heldout_truth.json.gz')['cases']
    legacy = {r['case']: r for r in read(PRIOR / 'control_truth.json')['cases']}
    string = {r['id']: r for r in read(ROOT / 'development/record_candidates_dev29_v1/controls_truth.json.gz')['cases']}
    natural = {r['cell']: r['accepted_formula'] for r in read(ROOT / 'development/natural_cv500_dev27_v1/natural_truth.json.gz')['cases']}
    stored = {r['case']: r for r in score['cases']}
    checked = 0
    for item in index:
        case, stratum = item['case'], item['stratum']
        pred = predictions[case]
        if stratum == 'old213':
            truth = old[case]
        elif stratum == 'conditioned_control':
            truth = controls[case]
            wb = openpyxl.load_workbook(ROOT / item['input'])
            actual = {s.title + '!' + c.coordinate: c.value for s in wb for row in s for c in row if c.data_type == 'f'}
            assert actual == truth['observed_formulas']
            wb.close()
        elif stratum == 'new_control':
            truth = legacy[case]
        elif stratum == 'string_control':
            t = string[item['id']]
            truth = dict(expected_formulas=t['all_expected'], errors=t['errors'])
        elif stratum == 'natural_original' and item['id'] == 'cv500':
            truth = dict(expected_formulas=natural, errors=list(natural))
        elif stratum in ('natural_original', 'public_original'):
            truth = {}
        else:
            raise AssertionError(stratum)
        expected = truth.get('expected_formulas', {})
        errors = set(truth.get('errors', []))
        model = None
        for mode in MODES + (['paper'] if stratum == 'conditioned_control' else []):
            right, wrong, unknown, unnecessary = [], [], [], []
            for row in pred[mode]:
                cell = row['cell']
                if cell not in expected:
                    unknown.append(cell)
                elif cell not in errors:
                    wrong.append(cell); unnecessary.append(cell)
                else:
                    matches = row['suggested_formula'] == expected[cell]
                    if not matches and stratum not in ('natural_original', 'string_control'):
                        if model is None:
                            model = WorkbookModel.from_xlsx(ROOT / item['input'])
                        matches = fraction_equivalent(row['suggested_formula'], expected[cell],
                                                      cell.rsplit('!', 1)[0], model)
                    (right if matches else wrong).append(cell)
            metric = dict(suggestions=len(pred[mode]), correct=len(right), wrong=len(wrong), unknown=len(unknown),
                          errors=len(errors), correct_errors=len(set(right)), unnecessary=len(unnecessary),
                          precision_confirmed_lower_bound=ratio(len(right), len(pred[mode])),
                          coverage=ratio(len(set(right)), len(errors)))
            for key, value in metric.items():
                assert stored[case][mode][key] == value, (case, mode, key)
                checked += 1
            assert stored[case][mode]['correct_cells'] == right
            assert stored[case][mode]['wrong_cells'] == wrong
            assert stored[case][mode]['unknown_cells'] == unknown

    by_stratum = score['by_stratum']
    for stratum, modes in by_stratum.items():
        members = [r for r in score['cases'] if r['stratum'] == stratum]
        for mode, metric in modes.items():
            rebuilt = totals([r[mode] for r in members])
            assert metric == rebuilt, (stratum, mode)
    # Immutable historical baseline and the known natural-error limitation.
    assert by_stratum['old213']['dev11']['correct'] == 14184
    assert by_stratum['old213']['dev11']['errors'] == 18073
    assert by_stratum['natural_original']['combined']['correct_errors'] == 0
    assert score['accepted_final_sources'] == 0 and score['accepted_final_families'] == 0
    witness = execution_witnesses(index, predictions, controls)
    verify()
    full_path = ROOT / 'qa/CONDITIONED_RELATIONS_DEV32_FULL_TESTS_V3_20261018.log'
    full = full_path.read_text()
    count = int(re.search(r'Ran (\d+) tests', full).group(1))
    assert count >= 321 and full.rstrip().endswith('OK')
    save(target, dict(all_checks_passed=True, cases_replayed=len(index), independent_metric_checks=checked,
                      full_test_count=count, full_test_log_sha256=sha(full_path), baseline_dev11_correct=14184,
                      baseline_dev11_precision=by_stratum['old213']['dev11']['precision_confirmed_lower_bound'],
                      baseline_dev11_coverage=by_stratum['old213']['dev11']['coverage'],
                      dev32_candidate=by_stratum['old213']['combined'],
                      conditioned_controls=score['new_control_by_family'],
                      independent_execution=witness,
                      natural_development=by_stratum['natural_original']['combined'],
                      accepted_final_sources=0, accepted_final_families=0,
                      final_validation_complete=False, main_candidate_adopted=False,
                      goal_status='active', verifier_sha256=sha(Path(__file__)),
                      prediction_lock_sha256=sha(RUN / 'prediction_lock.json'),
                      score_sha256=sha(RUN / 'score.json')))
    print('DEV32 VERIFIED:', len(index), 'cases replayed;', checked, 'metric checks;',
          'controls remain development-only; no adoption', flush=True)


if __name__ == '__main__':
    main()
