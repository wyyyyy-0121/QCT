"""Review-candidate and symbolic-unit audit over all 107 revealed dev6 inputs.

No selector changes. Every formula receives a unit diagnostic; review and
unsupported rows receive the existing business-agnostic single-edit inventory.
Candidate availability and unit consistency never emit a repair proposal.
"""
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import platform
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'development/evidence_gap_dev1'
DEV6 = ROOT / 'development/selector_dev6_contract_v2'
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from run_selector_dev5 import read, save, sha, metrics, total, verify_files
from run_selector_dev6 import verify as verify_dev6
from formula_candidates_dev1 import generate, structural_key
from unit_evidence_dev1 import UnitEvidence, VERSION, PARAMETERS
from formulaguard.workbook import WorkbookModel

REVIEW_STATUSES = {'review', 'unsupported'}


def verify_lock():
    lock = read(RUN / 'prediction_lock.json')
    assert lock['labels_read'] == [] and not lock['repair_proposals_generated']
    assert sha(RUN / 'source_lock.json') == lock['source_lock_sha256']
    assert sha(RUN / 'public_index.json') == lock['public_index_sha256']
    assert sha(RUN / 'registration.json') == lock['registration_sha256']
    verify_files(ROOT, read(RUN / 'source_lock.json')['files'])
    verify_files(ROOT, lock['inputs_and_upstream'])
    verify_files(RUN, lock['files'])
    return lock


def predict():
    if RUN.exists():
        raise SystemExit('Preserve evidence; create a new run for changed hypotheses')
    verify_dev6()
    items = read(DEV6 / 'public_index.json')
    for item in items:
        path = DEV6 / 'predictions' / item['group'] / (item['id'] + '.json.gz')
        item['dev6_prediction'] = str(path.relative_to(ROOT))
        item['dev6_prediction_sha256'] = sha(path)
    assert len(items) == 107
    save(RUN / 'registration.json', {
        'role': 'revealed development evidence-gap audit; no final acceptance',
        'version': VERSION, 'unit_parameters': PARAMETERS, 'cases': len(items),
        'candidate_selection': 'dev6 status review or unsupported only; no labels',
        'all_other_formula_cells_retained': True,
        'candidate_generator': 'immutable formula_candidates_dev1.py',
        'repair_proposals_generated': False, 'new_final_sources': 0, 'new_final_families': 0,
        'purpose': 'distinguish missing hypotheses from missing authorization; unit evidence is necessary only when explicit annotations are trusted',
        'limits': ['developer-selected revealed data', 'no automatic unit conversion',
                   'unit compatibility cannot resolve sign or dimensionless coefficient intent',
                   'header units are unverified declarations; never business truth'],
        'utc': datetime.datetime.now(datetime.timezone.utc).isoformat()})
    registration_sha = sha(RUN / 'registration.json')
    save(RUN / 'public_index.json', items)
    sources = sorted((ROOT / 'scripts').glob('*.py'))
    sources += sorted((ROOT / 'tests').glob('*.py'))
    sources += sorted((ROOT / 'baseline/source').rglob('*.py'))
    save(RUN / 'source_lock.json', {'files': {str(p.relative_to(ROOT)): sha(p) for p in sources},
                                  'unit_version': VERSION})
    accesses = set()
    def guard(event, args):
        if event == 'open' and isinstance(args[0], (str, bytes)):
            name = str(args[0])
            if any(term in name.casefold() for term in [
                    'truth.json', 'registration.json', 'data_manifest.json',
                    '/score', '/results/', 'input_oracle', 'mutation_log', 'failure_audit']):
                raise PermissionError('diagnostic prediction cannot read labels: ' + name)
            if str(ROOT) in name:
                accesses.add(name)
    sys.addaudithook(guard)
    files, inputs, timings = {}, {}, []
    start, cpu = time.perf_counter(), time.process_time()
    cached_generate = lru_cache(maxsize=2048)(generate)
    for item in items:
        t, c = time.perf_counter(), time.process_time()
        path, upstream = ROOT / item['input'], ROOT / item['dev6_prediction']
        assert sha(path) == item['input_sha256']
        assert sha(upstream) == item['dev6_prediction_sha256']
        model = WorkbookModel.from_xlsx(path)
        original = dict(model.formulas)
        unit = UnitEvidence(model)
        prior = read(upstream)
        by_cell = {r['cell']: r for r in prior['rows']}
        assert set(by_cell) == {s+'!'+a for s, a in model.formulas}
        rows, counts = [], Counter()
        for (sheet, address), formula in sorted(model.formulas.items()):
            cell = sheet + '!' + address
            old = by_cell[cell]
            current = unit.check(formula, sheet, address)
            counts['formula_cells'] += 1
            counts['unit_' + current['status']] += 1
            row = {'cell': cell, 'observed_formula': formula,
                   'prior_status': old['status'], 'unit_current': current,
                   'inventory_requested': old['status'] in REVIEW_STATUSES,
                   'candidates': []}
            if row['inventory_requested']:
                inventory = cached_generate(formula)
                row.update(inventory_status=inventory['status'],
                           search_truncated=inventory['search_truncated'])
                for candidate in inventory['candidates']:
                    check = unit.check(candidate['formula'], sheet, address)
                    row['candidates'].append({
                        'formula': candidate['formula'],
                        'edit_kinds': sorted({e['kind'] for e in candidate['edits']}),
                        'unit_status': check['status'], 'unit_reason': check.get('reason')})
                counts['inventory_rows'] += 1
                counts['candidate_hypotheses'] += len(row['candidates'])
            rows.append(row)
        assert model.formulas == original
        assert sha(path) == item['input_sha256']
        target = RUN / 'predictions' / item['group'] / (item['id'] + '.json.gz')
        save(target, {'rows': rows, 'repair_proposals': [], 'labels_read': [],
                      'unit_version': VERSION, 'selector_changes': False})
        files[str(target.relative_to(RUN))] = sha(target)
        inputs[item['input']] = item['input_sha256']
        inputs[item['dev6_prediction']] = item['dev6_prediction_sha256']
        timing = {'id': item['id'], 'group': item['group'], **dict(counts),
                  'wall_seconds': time.perf_counter()-t, 'cpu_seconds': time.process_time()-c}
        timings.append(timing)
        print(item['group'], item['id'], dict(counts), 'wall_s', round(timing['wall_seconds'], 3), flush=True)
    runtime = {'cases': timings, 'wall_seconds': time.perf_counter()-start,
               'cpu_seconds': time.process_time()-cpu,
               'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               'gpu_used': False, 'python': platform.python_version(),
               'platform': platform.platform(), 'command': [sys.executable, *sys.argv],
               'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'scope': 'input loading, unit evidence and bounded candidate inventories; upstream selector execution excluded'}
    save(RUN / 'runtime.json', runtime)
    files['runtime.json'] = sha(RUN / 'runtime.json')
    save(RUN / 'prediction_lock.json', {
        'files': files, 'inputs_and_upstream': inputs,
        'source_lock_sha256': sha(RUN / 'source_lock.json'),
        'public_index_sha256': sha(RUN / 'public_index.json'),
        'registration_sha256': registration_sha,
        'repair_proposals_generated': False, 'labels_read': [], 'accesses': sorted(accesses),
        'role': 'revealed development diagnostic only'})
    print('Locked', len(items), 'cases in', runtime['wall_seconds'], 'seconds', flush=True)


def truth_for(item):
    group, case = item['group'], item['id']
    if group == 'regression':
        path = ROOT / 'baseline/data' / case / 'truth.json'
        return read(path), path
    folder = {'stress': 'semantic_stress_dev1', 'tradeoff': 'policy_tradeoff_dev1',
              'crossdomain': 'crossdomain_dev1', 'adversarial': 'dev5_adversarial1'}[group]
    path = ROOT / 'development' / folder / 'truth.json'
    return next(c for c in read(path)['cases'] if c['id'] == case), path


def score_case(item):
    result = read(RUN / 'predictions' / item['group'] / (item['id'] + '.json.gz'))
    prior = read(ROOT / item['dev6_prediction'])
    truth, truth_path = truth_for(item)
    rows = result['rows']
    observed = {r['cell']: r['observed_formula'] for r in rows}
    expected = truth['expected_formulas']
    assert len(rows) == len(observed) and set(observed) == set(expected)
    errors = {k for k in expected if expected[k] != observed[k]}
    assert errors == set(truth['errors'])
    assert result['repair_proposals'] == result['labels_read'] == []
    prior_rows = {r['cell']: r for r in prior['rows']}
    counts, unit_confusion, missed_examples = Counter(), Counter(), []
    for row in rows:
        cell = row['cell']; is_error = cell in errors
        fixed = (prior_rows[cell]['status'] == 'propose'
                 and prior_rows[cell].get('suggested_formula') == expected[cell])
        counts['formula_cells'] += 1
        counts['errors'] += is_error
        counts['prior_correct'] += fixed
        unit_confusion[('error' if is_error else 'clean') + '/' + row['unit_current']['status']] += 1
        counts['review_inventory_rows'] += row['inventory_requested']
        candidates = row['candidates']
        counts['candidate_hypotheses'] += len(candidates)
        if not is_error:
            counts['clean_rows_with_multiple_hypotheses'] += len(candidates) > 1
        if not is_error or fixed:
            continue
        counts['missed_errors'] += 1
        counts['missed_without_inventory'] += not row['inventory_requested']
        exact_hits = [c for c in candidates if c['formula'] == expected[cell]]
        key = structural_key(expected[cell])
        ast_hits = [c for c in candidates if structural_key(c['formula']) == key]
        counts['missed_with_exact_target_in_inventory'] += bool(exact_hits)
        counts['missed_with_ast_target_in_inventory'] += bool(ast_hits)
        counts['missed_target_absent_from_requested_inventory'] += row['inventory_requested'] and not ast_hits
        counts['missed_target_unit_compatible'] += any(c['unit_status'] == 'compatible' for c in ast_hits)
        counts['missed_target_unit_unknown'] += any(c['unit_status'] == 'unknown' for c in ast_hits)
        counts['missed_target_unit_incompatible'] += any(c['unit_status'] == 'incompatible' for c in ast_hits)
        counts['missed_with_multiple_hypotheses'] += len(candidates) > 1
        counts['missed_with_truncated_inventory'] += row.get('search_truncated', False)
        if len(missed_examples) < 4:
            missed_examples.append({'cell': cell, 'observed': observed[cell], 'expected': expected[cell],
                                    'candidate_count': len(candidates), 'target_exact_hit': bool(exact_hits),
                                    'target_unit_statuses': sorted({c['unit_status'] for c in ast_hits})})
    return {'id': item['id'], 'group': item['group'], 'scenario': truth.get('scenario'),
            'family': truth.get('family'), 'counts': dict(counts),
            'unit_confusion': dict(unit_confusion), 'missed_examples': missed_examples,
            'dev6': metrics(prior, truth, observed),
            'truth_path': str(truth_path.relative_to(ROOT)), 'truth_sha256': sha(truth_path)}


def build_score():
    cases = [score_case(item) for item in read(RUN / 'public_index.json')]
    groups = {}
    for group in sorted({c['group'] for c in cases}):
        selected = [c for c in cases if c['group'] == group]
        counts, confusion = Counter(), Counter()
        for case in selected:
            counts.update(case['counts']); confusion.update(case['unit_confusion'])
        groups[group] = {'counts': dict(counts), 'unit_confusion': dict(confusion),
                         'unchanged_dev6': total(selected, 'dev6')}
    return {'cases': cases, 'groups': groups,
            'repair_precision': None, 'correct_repair_coverage': None,
            'repair_proposals_generated': False, 'selector_changed': False,
            'final_validation_eligible': False,
            'interpretation': 'Unit checks and inventory hits are diagnostic evidence, not repair authorization or unseen accuracy.',
            'prediction_lock_sha256': sha(RUN / 'prediction_lock.json')}


def score():
    if (RUN / 'score.json').exists():
        raise SystemExit('Preserve score')
    verify_lock()
    report = build_score()
    save(RUN / 'score.json', report)
    print(json.dumps(report['groups'], indent=2))


def verify():
    verify_lock()
    assert read(RUN / 'score.json') == build_score()
    print('Verified 107 locked diagnostics and independently recomputed all group counts')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['predict', 'score', 'verify'])
    args = parser.parse_args()
    {'predict': predict, 'score': score, 'verify': verify}[args.stage]()
