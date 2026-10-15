"""Evaluate business-agnostic formula hypotheses after dev5 freeze.

Prediction creates candidate inventories from formulas only. Scoring later
reads revealed development truth and reports candidate recall, not repair
precision; no candidate is emitted as a proposed edit.
"""
from collections import Counter
from pathlib import Path
import datetime
import gzip
import hashlib
import json
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'development/candidate_dev1'
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formula_candidates_dev1 import generate, VERSION, PARAMETERS
from formulaguard.workbook import WorkbookModel


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    payload = path.read_bytes()
    return json.loads(gzip.decompress(payload) if path.suffix == '.gz' else payload)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
    if path.suffix == '.gz':
        with gzip.GzipFile(filename=str(path), mode='wb', mtime=0) as handle: handle.write(payload.encode())
    else: path.write_text(payload)


def entries():
    result = []
    for group, folder in [('crossdomain', ROOT / 'development/crossdomain_dev1'),
                          ('adversarial', ROOT / 'development/dev5_adversarial1')]:
        for item in read(folder / 'public_index.json'):
            path = folder / item['input']
            result.append({'id': item['id'], 'group': group,
                           'input': str(path.relative_to(ROOT)), 'input_sha256': sha(path),
                           'truth': str((folder / ('truth.json' if group == 'adversarial' else 'truth.json')).relative_to(ROOT))})
    assert len(result) == 56
    return result


def prior_locks():
    for folder in ['development/crossdomain_dev1', 'development/dev5_adversarial1']:
        lock = read(ROOT / folder / 'prediction_lock.json')
        assert lock['labels_read'] == []
        for path, expected in read(ROOT / folder / 'source_lock.json')['files'].items(): assert sha(ROOT / path) == expected
        for path, expected in lock['files'].items(): assert sha(ROOT / folder / path) == expected
    return True


def register():
    if RUN.exists(): raise SystemExit('Preserve candidate evidence')
    prior_locks()
    items = entries()
    sources = [Path(__file__), ROOT / 'scripts/formula_candidates_dev1.py', ROOT / 'tests/test_formula_candidates_dev1.py']
    save(RUN / 'registration.json', {'role': 'revealed development candidate inventory',
        'version': VERSION, 'parameters': PARAMETERS, 'cases': len(items), 'new_final_families': 0,
        'selection': 'all 32 crossdomain and all 24 frozen adversarial cases',
        'truth_read_before_prediction': False, 'proposals_generated': False,
        'selection_authority': 'none; generated hypotheses require independent evidence',
        'source_exclusion': 'existing development families; not final validation',
        'utc': datetime.datetime.now(datetime.timezone.utc).isoformat()})
    save(RUN / 'public_index.json', items)
    save(RUN / 'source_lock.json', {'files': {str(p.relative_to(ROOT)): sha(p) for p in sources},
        'upstream_locks': {folder: sha(ROOT / folder / 'prediction_lock.json') for folder in
                           ['development/crossdomain_dev1', 'development/dev5_adversarial1']}})
    print('Registered', len(items), 'candidate-inventory cases')


def predict():
    if (RUN / 'prediction_lock.json').exists(): raise SystemExit('Preserve predictions')
    prior_locks()
    registration = read(RUN / 'registration.json')
    assert registration['truth_read_before_prediction'] is False
    accesses = set()
    def guard(event, args):
        if event == 'open' and isinstance(args[0], (str, bytes)):
            name = str(args[0])
            if any(term in name.casefold() for term in ['truth.json', 'score.json', 'registration.json', 'mutation_log']):
                raise PermissionError('candidate prediction cannot read scoring evidence: ' + name)
            if str(ROOT) in name: accesses.add(name)
    sys.addaudithook(guard)
    files = {}; timings = []
    for item in read(RUN / 'public_index.json'):
        path = ROOT / item['input']; assert sha(path) == item['input_sha256']
        started = time.perf_counter(); model = WorkbookModel.from_xlsx(path)
        rows = []
        for (sheet, address), formula in sorted(model.formulas.items()):
            inventory = generate(formula)
            rows.append({'cell': sheet + '!' + address, 'observed_formula': formula,
                         'inventory': inventory})
        result = {'id': item['id'], 'group': item['group'], 'rows': rows,
                  'selector_version': VERSION, 'proposals': [], 'labels_read': []}
        target = RUN / 'predictions' / item['group'] / (item['id'] + '.json.gz')
        save(target, result); files[str(target.relative_to(RUN))] = sha(target)
        timings.append({'id': item['id'], 'formula_cells': len(rows),
                        'wall_seconds': time.perf_counter() - started})
        print(item['group'], item['id'], 'formula_cells', len(rows), flush=True)
    runtime = {'cases': timings, 'version': VERSION, 'gpu_used': False,
               'command': [sys.executable, *sys.argv], 'python': platform.python_version(),
               'proposals_generated': False, 'labels_read': []}
    save(RUN / 'runtime.json', runtime); files['runtime.json'] = sha(RUN / 'runtime.json')
    save(RUN / 'prediction_lock.json', {'files': files, 'source_lock_sha256': sha(RUN / 'source_lock.json'),
        'public_index_sha256': sha(RUN / 'public_index.json'), 'labels_read': [],
        'proposals_generated': False, 'accesses': sorted(accesses), 'role': 'revealed development only'})


def score():
    if (RUN / 'score.json').exists(): raise SystemExit('Preserve score')
    lock = read(RUN / 'prediction_lock.json'); assert not lock['labels_read'] and not lock['proposals_generated']
    for path, expected in lock['files'].items(): assert sha(RUN / path) == expected
    totals = Counter(); cases = []
    truth_cache = {}
    for item in read(RUN / 'public_index.json'):
        folder = ROOT / ('development/crossdomain_dev1' if item['group'] == 'crossdomain' else 'development/dev5_adversarial1')
        truth_cache.setdefault(str(folder), read(folder / 'truth.json'))
        truth = next(case for case in truth_cache[str(folder)]['cases'] if case['id'] == item['id'])
        prediction = read(RUN / 'predictions' / item['group'] / (item['id'] + '.json.gz'))
        by_error = []
        for row in prediction['rows']:
            if row['cell'] not in truth['errors']: continue
            formulas = {candidate['formula'] for candidate in row['inventory']['candidates']}
            hit = truth['expected_formulas'][row['cell']] in formulas
            record = {'cell': row['cell'], 'candidate_count': len(formulas),
                      'correct_formula_in_inventory': hit,
                      'status': row['inventory']['status']}
            by_error.append(record); totals.update({'errors': 1, 'candidate_hits': int(hit),
                'errors_with_zero_candidates': int(not formulas),
                'errors_with_unique_candidate': int(len(formulas) == 1),
                'errors_with_multiple_candidates': int(len(formulas) > 1)})
        result = {'id': item['id'], 'group': item['group'], 'scenario': truth.get('scenario'),
                  'family': truth.get('family'), 'errors': by_error,
                  'error_count': len(by_error), 'correct_formula_candidate_recall':
                  (sum(r['correct_formula_in_inventory'] for r in by_error) / len(by_error) if by_error else None),
                  'candidate_authorization': 'none'}
        cases.append(result)
    report = {'version': VERSION, 'cases': cases, 'totals': dict(totals),
              'candidate_recall': totals['candidate_hits'] / totals['errors'],
              'precision': None, 'coverage': None, 'proposals_generated': False,
              'interpretation': 'Candidate recall is diagnostic; no formula is proposed or accepted.',
              'prediction_lock_sha256': sha(RUN / 'prediction_lock.json')}
    save(RUN / 'score.json', report); print(json.dumps(report['totals'], indent=2))


def verify():
    lock = read(RUN / 'prediction_lock.json')
    for path, expected in lock['files'].items(): assert sha(RUN / path) == expected
    assert sha(RUN / 'source_lock.json') == lock['source_lock_sha256']
    assert sha(RUN / 'public_index.json') == lock['public_index_sha256']
    score_report = read(RUN / 'score.json'); assert score_report['prediction_lock_sha256'] == sha(RUN / 'prediction_lock.json')
    assert score_report['precision'] is score_report['coverage'] is None and not score_report['proposals_generated']
    print('Verified candidate inventory lock and diagnostic-only score')


if __name__ == '__main__':
    {'register': register, 'predict': predict, 'score': score, 'verify': verify}[sys.argv[1]]()
