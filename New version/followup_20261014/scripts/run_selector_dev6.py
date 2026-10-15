"""Lock and score the revealed dev6 contract-candidate experiment."""
from collections import Counter
from pathlib import Path
import argparse
import datetime
import gzip
import hashlib
import json
import platform
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'development/selector_dev6_contract_v2'
BASE = ROOT / 'baseline'
DEV4 = ROOT / 'development/selector_dev4'
CROSS = ROOT / 'development/crossdomain_dev1'
ADV = ROOT / 'development/dev5_adversarial1'
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(BASE / 'source/HybridGuard_V5_handoff_20260904/src'))
from run_selector_dev5 import read, save, sha, verify_prior, input_index
from selector_dev6 import augment, VERSION


def all_items():
    items = input_index()
    for entry in read(ADV / 'public_index.json'):
        case = entry['id']
        upstream = ADV / 'predictions' / (case + '.json.gz')
        items.append({'id': case, 'group': 'adversarial',
                      'input': str((ADV / entry['input']).relative_to(ROOT)),
                      'upstream': str(upstream.relative_to(ROOT)),
                      'parallel_sheets': entry.get('parallel_sheets', ['A','B','C','D','E'])})
    assert len(items) == 107
    for item in items:
        item['input_sha256'] = sha(ROOT / item['input'])
        item['upstream_sha256'] = sha(ROOT / item['upstream'])
    return items


def verify_inputs(lock):
    assert sha(RUN / 'source_lock.json') == lock['source_lock_sha256']
    assert sha(RUN / 'public_index.json') == lock['public_index_sha256']
    for relative, expected in lock['files'].items():
        assert sha(RUN / relative) == expected, relative
    for relative, expected in lock['inputs_and_upstream'].items():
        assert sha(ROOT / relative) == expected, relative
    assert lock['labels_read'] == []


def predict():
    if RUN.exists():
        raise SystemExit('Preserve existing dev6 evidence; use another run for a new model')
    verify_prior()
    sources = [Path(__file__), ROOT / 'scripts/selector_dev6.py',
               ROOT / 'scripts/selector_dev5.py', ROOT / 'scripts/selector_dev4.py',
               ROOT / 'scripts/selector_dev3.py', ROOT / 'scripts/selector_dev2.py']
    sources += sorted((BASE / 'source').rglob('*.py'))
    sources += sorted((ROOT / 'tests').glob('*.py'))
    save(RUN / 'source_lock.json', {'version': VERSION,
         'files': {str(p.relative_to(ROOT)): sha(p) for p in sources}})
    items = all_items(); save(RUN / 'public_index.json', items)
    accesses = set()
    def guard(event, args):
        if event == 'open' and isinstance(args[0], (str, bytes)):
            name = str(args[0])
            if any(word in name.casefold() for word in ['truth.json','registration.json',
                    'data_manifest.json','/score','/results/','failure_audit',
                    'input_oracle','mutation_log']):
                raise PermissionError('Prediction may not access scoring evidence: ' + name)
            if str(ROOT) in name:
                accesses.add(name)
    sys.addaudithook(guard)
    files = {}; inputs = {}; timings = []
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    for item in items:
        path, upstream = ROOT / item['input'], ROOT / item['upstream']
        assert sha(path) == item['input_sha256']
        assert sha(upstream) == item['upstream_sha256']
        t, c = time.perf_counter(), time.process_time()
        from formulaguard.workbook import WorkbookModel
        model = WorkbookModel.from_xlsx(path)
        source = read(upstream)
        prior = source['dev4'] if item['group'] in ['crossdomain', 'adversarial'] else source
        before = dict(model.formulas)
        prior_hash = hashlib.sha256(json.dumps(prior, sort_keys=True).encode()).hexdigest()
        result = augment(model, prior, item['parallel_sheets'])
        assert model.formulas == before
        assert hashlib.sha256(json.dumps(prior, sort_keys=True).encode()).hexdigest() == prior_hash
        timing = {'id': item['id'], 'group': item['group'],
                  'wall_seconds': time.perf_counter()-t,
                  'cpu_seconds': time.process_time()-c,
                  'process_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  'rss_interpretation': 'cumulative process high-water mark on Linux',
                  'formula_cells': len(before)}
        target = RUN / 'predictions' / item['group'] / (item['id'] + '.json.gz')
        save(target, result); files[str(target.relative_to(RUN))] = sha(target)
        inputs[item['input']] = item['input_sha256']
        inputs[item['upstream']] = item['upstream_sha256']
        timings.append(timing)
        print(item['group'], item['id'],
              'proposals', sum(r['status'] == 'propose' for r in result['rows']),
              'wall_s', round(timing['wall_seconds'], 4), flush=True)
    runtime = {'command': [sys.executable, *sys.argv],
               'cwd': str(Path.cwd()),
               'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'python': platform.python_version(), 'platform': platform.platform(),
               'cases': timings, 'wall_seconds': time.perf_counter()-start_wall,
               'cpu_seconds': time.process_time()-start_cpu,
               'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               'scope': 'input loading and dev6 contract augmentation only; upstream execution excluded',
               'gpu_used': False}
    save(RUN / 'runtime.json', runtime); files['runtime.json'] = sha(RUN / 'runtime.json')
    save(RUN / 'prediction_lock.json', {'files': files, 'inputs_and_upstream': inputs,
         'source_lock_sha256': sha(RUN / 'source_lock.json'),
         'public_index_sha256': sha(RUN / 'public_index.json'), 'labels_read': [],
         'accesses': sorted(accesses),
         'role': 'revealed development only; not final validation'})
    print('Locked', len(items), 'cases;', runtime['wall_seconds'], 'seconds', flush=True)


def metrics(pred, truth, observed):
    rows = pred['rows']; expected = truth['expected_formulas']; errors = set(truth['errors'])
    assert len(rows) == len({r['cell'] for r in rows}) == len(expected) == len(observed)
    assert errors == {cell for cell in expected if expected[cell] != observed[cell]}
    proposals = {r['cell']: r['suggested_formula'] for r in rows
                 if r['status'] == 'propose' and r.get('suggested_formula')
                 and r['suggested_formula'] != observed[r['cell']]}
    correct = sum(formula == expected[cell] for cell, formula in proposals.items())
    return {'proposals': len(proposals), 'correct': correct,
            'wrong': len(proposals)-correct, 'errors': len(errors),
            'precision': correct/len(proposals) if proposals else None,
            'coverage': correct/len(errors) if errors else None,
            'harmful_correct_cells': sum(cell not in errors for cell in proposals),
            'statuses': dict(Counter(r['status'] for r in rows)),
            'reason_counts': dict(Counter(r.get('reason', 'unspecified') for r in rows))}


def total(cases):
    keys = ['proposals', 'correct', 'wrong', 'errors', 'harmful_correct_cells']
    counts = {key: sum(c['dev6'][key] for c in cases) for key in keys}
    return {**counts,
            'precision': counts['correct']/counts['proposals'] if counts['proposals'] else None,
            'coverage': counts['correct']/counts['errors'] if counts['errors'] else None}


def score():
    lock = read(RUN / 'prediction_lock.json'); verify_inputs(lock)
    entries = all_items(); reports = {}
    for group in ['regression', 'stress', 'tradeoff', 'crossdomain', 'adversarial']:
        cases = []
        for item in [x for x in entries if x['group'] == group]:
            case = item['id']
            if group == 'regression':
                truth = read(BASE / 'data' / case / 'truth.json')
                source = read(BASE / 'predictions' / case / 'input_formulas.json.gz')
                observed = source
                prior = read(DEV4 / 'predictions' / 'regression' / (case + '.json.gz'))
            elif group == 'stress':
                challenge = ROOT / 'development/semantic_stress_dev1'
                truth = next(c for c in read(challenge / 'truth.json')['cases'] if c['id'] == case)
                observed = read(challenge / 'predictions' / (case + '.json'))['observed_formulas']
                prior = read(DEV4 / 'predictions' / 'stress' / (case + '.json.gz'))
            elif group == 'tradeoff':
                challenge = ROOT / 'development/policy_tradeoff_dev1'
                truth = next(c for c in read(challenge / 'truth.json')['cases'] if c['id'] == case)
                observed = read(challenge / 'predictions' / (case + '.json'))['observed_formulas']
                prior = read(DEV4 / 'predictions' / 'tradeoff' / (case + '.json.gz'))
            elif group == 'crossdomain':
                truth = next(c for c in read(CROSS / 'truth.json')['cases'] if c['id'] == case)
                observed = read(CROSS / 'predictions' / (case + '.json.gz'))['observed_formulas']
                prior = read(CROSS / 'predictions' / (case + '.json.gz'))['dev4']
            else:
                truth = next(c for c in read(ADV / 'truth.json')['cases'] if c['id'] == case)
                observed = read(ADV / 'predictions' / (case + '.json.gz'))['observed_formulas']
                prior = read(ADV / 'predictions' / (case + '.json.gz'))['dev4']
            prediction = read(RUN / 'predictions' / group / (case + '.json.gz'))
            result = {'id': case, 'family': truth.get('family'), 'scenario': truth.get('scenario'),
                      'dev4': metrics(prior, truth, observed),
                      'dev6': metrics(prediction, truth, observed)}
            cases.append(result)
            print(group, case, 'dev6', result['dev6']['correct'], result['dev6']['wrong'], flush=True)
        reports[group] = {'cases': cases, 'totals': total(cases)}
    save(RUN / 'score.json', {'role': 'revealed development only; no final validation claim',
                              **reports, 'prediction_lock_sha256': sha(RUN / 'prediction_lock.json')})
    print(json.dumps({k: v['totals'] for k, v in reports.items()}, indent=2))


def verify():
    verify_inputs(read(RUN / 'prediction_lock.json'))
    print('Verified dev6 prediction lock')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['predict', 'score', 'verify'])
    args = parser.parse_args()
    {'predict': predict, 'score': score, 'verify': verify}[args.stage]()
