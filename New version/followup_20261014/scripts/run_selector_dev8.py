"""Dev6 control with corrected, frozen parallel-sheet metadata.

This is a revealed-development configuration control, not a new selector or a
final experiment. Historical runners and predictions remain immutable.
"""
from collections import Counter
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
RUN = ROOT / 'development/selector_dev8_metadata_control_v1'
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from run_selector_dev5 import read, save, sha, verify_prior, metrics
from run_selector_dev6 import all_items as legacy_items
from selector_dev6 import augment, VERSION as SELECTOR_VERSION
from peer_metadata_dev8 import corrected_index, assert_parallel_sheets
from formulaguard.workbook import WorkbookModel

VERSION = 'dev8-dev6-corrected-metadata-control-v1'
GROUPS = ['regression', 'stress', 'tradeoff', 'crossdomain', 'adversarial']
FORBIDDEN = ['truth.json', 'registration.json', 'data_manifest.json',
             '/score', '/results/', 'failure_audit', 'input_oracle', 'mutation_log']


def verify_inputs(lock):
    assert sha(RUN / 'source_lock.json') == lock['source_lock_sha256']
    assert sha(RUN / 'public_index.json') == lock['public_index_sha256']
    for relative, expected in read(RUN / 'source_lock.json')['files'].items():
        assert sha(ROOT / relative) == expected, relative
    for relative, expected in lock['files'].items():
        assert sha(RUN / relative) == expected, relative
    for relative, expected in lock['inputs_and_upstream'].items():
        assert sha(ROOT / relative) == expected, relative
    assert lock['labels_read'] == []
    assert lock['final_validation_eligible'] is False


def guard_prediction(accesses, active):
    def guard(event, args):
        if active[0] and event == 'open' and isinstance(args[0], (str, bytes)):
            name = args[0].decode() if isinstance(args[0], bytes) else args[0]
            if any(word in name.casefold() for word in FORBIDDEN):
                raise PermissionError('Prediction cannot read scoring evidence: ' + name)
            if str(ROOT) in name:
                accesses.add(name)
    sys.addaudithook(guard)


def case_prediction(item):
    model = WorkbookModel.from_xlsx(ROOT / item['input'])
    assert_parallel_sheets(model, item['parallel_sheets'])
    source = read(ROOT / item['upstream'])
    prior = source['dev4'] if item['group'] in ['crossdomain', 'adversarial'] else source
    before = dict(model.formulas)
    prior_hash = hashlib.sha256(json.dumps(prior, sort_keys=True).encode()).hexdigest()
    prediction = augment(model, prior, item['parallel_sheets'])
    assert model.formulas == before
    assert hashlib.sha256(json.dumps(prior, sort_keys=True).encode()).hexdigest() == prior_hash
    assert {row['cell'] for row in prediction['rows']} == {s+'!'+a for s,a in before}
    assert len(prediction['rows']) == len(before)
    return prediction, len(before)


def predict():
    if RUN.exists():
        raise SystemExit('Preserve dev8 evidence; choose a new version for another experiment')
    verify_prior()
    sources = sorted((ROOT / 'scripts').glob('*.py'))
    sources += sorted((ROOT / 'baseline/source').rglob('*.py'))
    sources += sorted((ROOT / 'tests').glob('*.py'))
    save(RUN / 'source_lock.json', {
        'version': VERSION, 'selector': SELECTOR_VERSION,
        'files': {str(p.relative_to(ROOT)): sha(p) for p in sources}})
    accesses, active = set(), [True]
    guard_prediction(accesses, active)
    items = corrected_index(ROOT, legacy_items(), read, sha)
    save(RUN / 'public_index.json', items)
    files, inputs, timings = {}, {}, []
    wall, cpu = time.perf_counter(), time.process_time()
    for item in items:
        for field in ['input', 'upstream', 'parallel_metadata']:
            if field in item:
                assert sha(ROOT / item[field]) == item[field+'_sha256'], item[field]
                inputs[item[field]] = item[field+'_sha256']
        started, started_cpu = time.perf_counter(), time.process_time()
        prediction, formula_count = case_prediction(item)
        timings.append({'id': item['id'], 'group': item['group'],
                        'formula_cells': formula_count,
                        'wall_seconds': time.perf_counter()-started,
                        'cpu_seconds': time.process_time()-started_cpu})
        target = RUN / 'predictions' / item['group'] / (item['id']+'.json.gz')
        save(target, prediction)
        files[str(target.relative_to(RUN))] = sha(target)
        print(item['group'], item['id'], 'proposals',
              sum(r['status']=='propose' for r in prediction['rows']), flush=True)
    runtime = {'version': VERSION, 'selector': SELECTOR_VERSION, 'cases': timings,
               'wall_seconds': time.perf_counter()-wall,
               'cpu_seconds': time.process_time()-cpu,
               'process_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               'python': platform.python_version(), 'platform': platform.platform(),
               'command': [sys.executable, *sys.argv],
               'scope': 'workbook load and dev6 augmentation; upstream costs excluded',
               'gpu_used': False, 'utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    save(RUN / 'runtime.json', runtime)
    files['runtime.json'] = sha(RUN / 'runtime.json')
    save(RUN / 'prediction_lock.json', {'files': files, 'inputs_and_upstream': inputs,
         'source_lock_sha256': sha(RUN / 'source_lock.json'),
         'public_index_sha256': sha(RUN / 'public_index.json'),
         'labels_read': [], 'accesses': sorted(accesses),
         'final_validation_eligible': False,
         'role': 'revealed development; dev6 metadata configuration control'})
    print('Locked', len(items), 'cases in', runtime['wall_seconds'], 'seconds', flush=True)


def truth_and_observed(item):
    group, case = item['group'], item['id']
    if group == 'regression':
        truth = read(ROOT / 'baseline/data' / case / 'truth.json')
        observed = read(ROOT / 'baseline/predictions' / case / 'input_formulas.json.gz')
    else:
        folder = {'stress':'semantic_stress_dev1', 'tradeoff':'policy_tradeoff_dev1',
                  'crossdomain':'crossdomain_dev1', 'adversarial':'dev5_adversarial1'}[group]
        base = ROOT / 'development' / folder
        truth = next(c for c in read(base / 'truth.json')['cases'] if c['id']==case)
        suffix = '.json.gz' if group in ['crossdomain', 'adversarial'] else '.json'
        observed = read(base / 'predictions' / (case+suffix))['observed_formulas']
    return truth, observed


def totals(cases, key):
    counts = {k:sum(c[key][k] for c in cases) for k in
              ['proposals', 'correct', 'wrong', 'errors', 'harmful_correct_cells']}
    return {**counts, 'precision': counts['correct']/counts['proposals'] if counts['proposals'] else None,
            'coverage':counts['correct']/counts['errors'] if counts['errors'] else None}


def build_score():
    reports = {}
    index = read(RUN / 'public_index.json')
    for group in GROUPS:
        cases = []
        for item in [i for i in index if i['group']==group]:
            case = item['id']
            truth, observed = truth_and_observed(item)
            old = read(ROOT / 'development/selector_dev6_contract_v2/predictions' / group / (case+'.json.gz'))
            new = read(RUN / 'predictions' / group / (case+'.json.gz'))
            cases.append({'id':case, 'family':truth.get('family'), 'scenario':truth.get('scenario'),
                          'dev6':metrics(old, truth, observed), 'dev8':metrics(new, truth, observed),
                          'prediction_changed':old != new})
        reports[group] = {'cases':cases, 'dev6_totals':totals(cases, 'dev6'),
                          'totals':totals(cases, 'dev8'),
                          'changed_cases':sum(c['prediction_changed'] for c in cases)}
    return {'role':'revealed development configuration control; not final validation',
            'version':VERSION, 'prediction_lock_sha256':sha(RUN / 'prediction_lock.json'), **reports}


def score():
    verify_inputs(read(RUN / 'prediction_lock.json'))
    if (RUN / 'score.json').exists():
        raise SystemExit('Preserve existing score; use replay to verify it')
    result = build_score()
    save(RUN / 'score.json', result)
    print(json.dumps({g:{k:v for k,v in result[g].items() if k!='cases'} for g in GROUPS}, indent=2))


def replay():
    verify_inputs(read(RUN / 'prediction_lock.json'))
    accesses, active = set(), [True]
    guard_prediction(accesses, active)
    start = time.perf_counter()
    index = read(RUN / 'public_index.json')
    assert index == corrected_index(ROOT, legacy_items(), read, sha)
    for item in index:
        prediction, _count = case_prediction(item)
        assert prediction == read(RUN / 'predictions' / item['group'] / (item['id']+'.json.gz'))
        print('Replayed',item['group'],item['id'],flush=True)
    active[0] = False
    assert build_score() == read(RUN / 'score.json')
    save(ROOT / 'qa/DEV8_METADATA_CONTROL_REPLAY_20261018.json', {
        'all_predictions_replayed_exactly':True, 'all_source_files_rehashed':True,
        'labels_read_during_replay':False, 'score_recomputed_after_replay':True,
        'cases':len(index), 'wall_seconds':time.perf_counter()-start,
        'prediction_lock_sha256':sha(RUN / 'prediction_lock.json'),
        'score_sha256':sha(RUN / 'score.json'), 'accesses':sorted(accesses),
        'final_validation_eligible':False, 'utc':datetime.datetime.now(datetime.timezone.utc).isoformat()})
    print('Dev8 control replay and score verified',flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['predict', 'score', 'verify', 'replay'])
    args = parser.parse_args()
    if args.stage == 'verify':
        verify_inputs(read(RUN / 'prediction_lock.json'))
        print('Dev8 lock verified, including every source and metadata file')
    else:
        {'predict':predict, 'score':score, 'replay':replay}[args.stage]()
