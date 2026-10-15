"""Lock a policy guard over verified immutable dev2 outputs, then score.

Both the 39 old regression cases and eight revealed stress cases are retained.
The guard consumes inputs and dev2 predictions; it never consumes answer files.
"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'baseline'
RUN = ROOT / 'development/selector_dev3'
DEV2 = ROOT / 'development/selector_dev2'
STRESS = ROOT / 'development/semantic_stress_dev1'
sys.path.insert(0, str(BASE / 'source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
from selector_dev3 import review_guard, VERSION


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    if path.suffix == '.gz':
        with gzip.open(path, 'rt') as handle:
            return json.load(handle)
    return json.loads(path.read_text())


def save(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == '.gz':
        with gzip.GzipFile(filename=str(path), mode='wb', mtime=0) as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode())
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')


def verify_files(root, lock):
    for relative, expected in read(lock)['files'].items():
        assert sha(root / relative) == expected, relative


def predict():
    if RUN.exists():
        raise SystemExit('Preserve existing dev3 evidence')
    verify_files(BASE, BASE / 'protocol/source_lock.json')
    verify_files(BASE, BASE / 'protocol/prediction_lock.json')
    for prior in [DEV2, STRESS]:
        lock = read(prior / 'prediction_lock.json')
        assert sha(prior / 'source_lock.json') == lock['source_lock_sha256']
        verify_files(prior, prior / 'prediction_lock.json')
        verify_files(ROOT, prior / 'source_lock.json')
    sources = [Path(__file__), ROOT / 'scripts/selector_dev3.py', ROOT / 'scripts/selector_dev2.py']
    sources += [BASE / 'scripts/score.py'] + sorted((BASE / 'source').rglob('*.py'))
    save(RUN / 'source_lock.json', {'version': VERSION,
        'files': {str(p.relative_to(ROOT)): sha(p) for p in sources}})
    accesses = set()
    def guard(event, args):
        if event == 'open' and isinstance(args[0], (str, bytes)):
            name = str(args[0])
            if any(x in name.lower() for x in ['truth.json', '/results/', '/score', 'failure_audit',
                                              'registration.json', 'data_manifest.json']):
                raise PermissionError('Prediction cannot access labels: ' + name)
            if str(ROOT) in name:
                accesses.add(name)
    sys.addaudithook(guard)
    inputs = []
    for entry in read(BASE / 'protocol/public_index.json'):
        case = entry['id']
        inputs.append(('regression', case, BASE / 'data' / case / 'input.xlsx',
                       DEV2 / 'predictions' / (case + '.json.gz')))
    for entry in read(STRESS / 'public_index.json'):
        path = STRESS / entry['input']; assert sha(path) == entry['sha256']
        inputs.append(('stress', entry['id'], path, STRESS / 'predictions' / (entry['id'] + '.json')))
    files = {}; inputs_lock = {}
    for kind, case, path, upstream in inputs:
        model = WorkbookModel.from_xlsx(path)
        pred = read(upstream)
        if kind == 'stress':
            pred = pred['dev2']
        before = dict(model.formulas)
        got = review_guard(model, pred)
        assert before == model.formulas
        target = RUN / 'predictions' / kind / (case + '.json.gz')
        save(target, got); files[str(target.relative_to(RUN))] = sha(target)
        inputs_lock[str(path.relative_to(ROOT))] = sha(path)
        inputs_lock[str(upstream.relative_to(ROOT))] = sha(upstream)
        print(kind, case, 'reviewed', sum(r.get('reason') == 'unresolved_visible_business_policy' for r in got['rows']), flush=True)
    save(RUN / 'prediction_lock.json', {'files': files, 'inputs_and_upstream': inputs_lock,
        'source_lock_sha256': sha(RUN / 'source_lock.json'), 'labels_read': [], 'accesses': sorted(accesses),
        'role': 'revealed development; dev3 is dev2 plus unresolved-policy review guard'})


def score():
    if (RUN / 'score.json').exists():
        raise SystemExit('Preserve existing scores')
    lock = read(RUN / 'prediction_lock.json')
    assert sha(RUN / 'source_lock.json') == lock['source_lock_sha256']
    verify_files(RUN, RUN / 'prediction_lock.json')
    verify_files(ROOT, RUN / 'source_lock.json')
    for relative, expected in lock['inputs_and_upstream'].items():
        assert sha(ROOT / relative) == expected, relative
    reports = {}
    for kind in ['regression', 'stress']:
        entries = read(BASE / 'protocol/data_manifest.json') if kind == 'regression' else read(STRESS / 'truth.json')['cases']
        cases = []
        for entry in entries:
            case = entry['id']
            truth = read(BASE / 'data' / case / 'truth.json') if kind == 'regression' else entry
            observed = read(BASE / 'predictions' / case / 'input_formulas.json.gz') if kind == 'regression' else read(STRESS / 'predictions' / (case + '.json'))['observed_formulas']
            pred = read(RUN / 'predictions' / kind / (case + '.json.gz'))
            assert len(pred['rows']) == len({r['cell'] for r in pred['rows']}) == len(observed)
            assert {r['cell'] for r in pred['rows']} == set(truth['expected_formulas'])
            proposals = {r['cell']: r['suggested_formula'] for r in pred['rows'] if r['status'] == 'propose'
                         and r.get('suggested_formula') and r['suggested_formula'] != observed[r['cell']]}
            correct = sum(v == truth['expected_formulas'][k] for k, v in proposals.items())
            cases.append({'id': case, 'family': entry.get('family', entry.get('scenario')),
                'proposals': len(proposals), 'correct': correct, 'errors': len(truth['errors']),
                'wrong': len(proposals) - correct,
                'policy_reviewed': sum(r.get('reason') == 'unresolved_visible_business_policy' for r in pred['rows']),
                'harmful_correct_cells': sum(k not in truth['errors'] for k in proposals)})
        report = {'cases': cases}
        # Deliberately do not pool the incompatible-policy stress pair as accuracy.
        if kind == 'regression':
            p = sum(c['proposals'] for c in cases); c = sum(c['correct'] for c in cases); e = sum(c['errors'] for c in cases)
            report['totals'] = {'proposals': p, 'correct': c, 'errors': e, 'precision': c/p if p else None,
                'coverage': c/e if e else None, 'harmful_correct_cells': sum(x['harmful_correct_cells'] for x in cases)}
        reports[kind] = report
    save(RUN / 'score.json', {'role': 'revealed development only; final gate not passed',
         **reports, 'prediction_lock_sha256': sha(RUN / 'prediction_lock.json')})
    print('regression', reports['regression']['totals'])
    for case in reports['stress']['cases']:
        print('stress', case)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('stage', choices=['predict', 'score'])
    args = parser.parse_args()
    predict() if args.stage == 'predict' else score()
