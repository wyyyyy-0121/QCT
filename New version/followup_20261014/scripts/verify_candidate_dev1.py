"""Replay every locked candidate inventory and independently count exact hits."""
from collections import Counter, defaultdict
import datetime
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'development/candidate_dev1'
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formula_candidates_dev1 import generate
from formulaguard.workbook import WorkbookModel
from formulaguard.formula import parse_formula


def read(path):
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes())


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    lock = read(RUN / 'prediction_lock.json')
    assert sha(RUN / 'source_lock.json') == lock['source_lock_sha256']
    assert sha(RUN / 'public_index.json') == lock['public_index_sha256']
    assert lock['labels_read'] == [] and lock['proposals_generated'] is False
    source = read(RUN / 'source_lock.json')
    for relative, expected in source['files'].items(): assert sha(ROOT / relative) == expected
    for relative, expected in lock['files'].items(): assert sha(RUN / relative) == expected
    for folder, expected in source['upstream_locks'].items():
        upstream = ROOT / folder
        assert sha(upstream / 'prediction_lock.json') == expected
        old_lock = read(upstream / 'prediction_lock.json')
        assert sha(upstream / 'source_lock.json') == old_lock['source_lock_sha256']
        for relative, expected_source in read(upstream / 'source_lock.json')['files'].items():
            assert sha(ROOT / relative) == expected_source
    registration = read(RUN / 'registration.json')
    assert registration['new_final_families'] == 0 and registration['proposals_generated'] is False
    index = read(RUN / 'public_index.json')
    assert len(index) == registration['cases'] == 56
    # Replay is deliberately completed before this process opens any truth file.
    formula_cells = 0
    for item in index:
        assert sha(ROOT / item['input']) == item['input_sha256']
        model = WorkbookModel.from_xlsx(ROOT / item['input'])
        observed = {s + '!' + a: f for (s, a), f in model.formulas.items()}
        prediction = read(RUN / 'predictions' / item['group'] / (item['id'] + '.json.gz'))
        assert prediction['proposals'] == prediction['labels_read'] == []
        assert len(prediction['rows']) == len(observed)
        assert {row['cell'] for row in prediction['rows']} == set(observed)
        for row in prediction['rows']:
            assert row['observed_formula'] == observed[row['cell']]
            assert generate(observed[row['cell']]) == row['inventory'], (item['id'], row['cell'])
        formula_cells += len(observed)
    scored = read(RUN / 'score.json')
    assert scored['prediction_lock_sha256'] == sha(RUN / 'prediction_lock.json')
    assert scored['precision'] is scored['coverage'] is None and not scored['proposals_generated']
    scored_cases = {(c['group'], c['id']): c for c in scored['cases']}
    totals, by_group, by_scenario = Counter(), defaultdict(Counter), defaultdict(Counter)
    candidate_histogram, error_histogram = Counter(), Counter()
    all_statuses, clean_cells_with_candidates, truncated_cells = Counter(), 0, 0
    truth_inputs = {}
    for item in index:
        truth_path = ROOT / item['truth']
        truth_inputs[str(truth_path.relative_to(ROOT))] = sha(truth_path)
        truth = next(t for t in read(truth_path)['cases'] if t['id'] == item['id'])
        result = read(RUN / 'predictions' / item['group'] / (item['id'] + '.json.gz'))
        observations = {row['cell']: row['observed_formula'] for row in result['rows']}
        expected = truth['expected_formulas']
        assert set(observations) == set(expected)
        errors = {cell for cell in expected if expected[cell] != observations[cell]}
        assert errors == set(truth['errors'])
        counts = Counter(); error_rows = []
        for row in result['rows']:
            inventory = row['inventory']; candidates = inventory['candidates']
            candidate_histogram[len(candidates)] += 1; all_statuses[inventory['status']] += 1
            truncated_cells += int(inventory['search_truncated'])
            if row['cell'] not in errors:
                clean_cells_with_candidates += int(bool(candidates)); continue
            formulas = {candidate['formula'] for candidate in candidates}
            hit = expected[row['cell']] in formulas
            if hit:
                # Exact target membership is also checked using parser-node
                # equality, without trusting the generator's structural key.
                assert any(parse_formula(candidate) == parse_formula(expected[row['cell']])
                           for candidate in formulas)
            error_rows.append({'cell': row['cell'], 'candidate_count': len(formulas),
                'correct_formula_in_inventory': hit, 'status': inventory['status']})
            error_histogram[len(formulas)] += 1
            counts.update({'errors': 1, 'candidate_hits': int(hit),
                'errors_with_zero_candidates': int(not formulas),
                'errors_with_unique_candidate': int(len(formulas) == 1),
                'errors_with_multiple_candidates': int(len(formulas) > 1)})
        case = scored_cases[item['group'], item['id']]
        assert error_rows == case['errors'] and len(errors) == case['error_count']
        assert case['correct_formula_candidate_recall'] == (counts['candidate_hits'] / len(errors) if errors else None)
        totals.update(counts); by_group[item['group']].update(counts)
        by_scenario[item['group'] + '/' + str(truth.get('scenario'))].update(counts)
    assert dict(totals) == scored['totals']
    assert scored['candidate_recall'] == totals['candidate_hits'] / totals['errors']
    report = {'all_locks_verified': True, 'all_candidate_inventories_replayed_exactly': True,
        'labels_read_during_replay': False, 'cases': len(index), 'formula_cells': formula_cells,
        'totals': dict(totals), 'by_group': dict(by_group), 'by_scenario': dict(by_scenario),
        'all_statuses': dict(all_statuses), 'truncated_cells': truncated_cells,
        'candidate_count_histogram_all_formula_cells': dict(candidate_histogram),
        'candidate_count_histogram_error_cells': dict(error_histogram),
        'clean_formula_cells_with_candidates': clean_cells_with_candidates,
        'truth_file_hashes': truth_inputs, 'source_lock_sha256': sha(RUN / 'source_lock.json'),
        'prediction_lock_sha256': sha(RUN / 'prediction_lock.json'),
        'score_sha256': sha(RUN / 'score.json'), 'verifier_sha256': sha(Path(__file__)),
        'repair_precision': None, 'correct_repair_coverage': None,
        'repair_proposals_generated': False, 'final_validation_eligible': False,
        'interpretation': 'A hypothesis inventory is not a repair decision; no acceptance metrics improved.',
        'utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    target = ROOT / 'qa/CANDIDATE_DEV1_VERIFICATION_20261015.json'
    target.write_text(json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in {
        'candidate_count_histogram_all_formula_cells', 'candidate_count_histogram_error_cells', 'by_scenario'}}, indent=2))


if __name__ == '__main__': verify()
