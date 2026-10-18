"""Lock dev11 on 107 legacy cases and 11 unlabelled public cases."""
from collections import Counter
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import platform
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
RUN = ROOT / 'development/selector_dev11_complete_ast_v1'
PUBLIC = ROOT / 'development/public_candidate_pipeline_dev10'
LEGACY = ROOT / 'development/selector_dev8_metadata_control_v1'
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from run_selector_dev5 import read, save, sha, metrics
from run_selector_dev8 import (case_prediction as dev6_prediction,
                               truth_and_observed, GROUPS, guard_prediction)
from selector_dev11 import qualify, VERSION
from formulaguard.workbook import WorkbookModel


def verify():
    lock = read(RUN / 'prediction_lock.json')
    assert sha(RUN / 'source_lock.json') == lock['source_lock_sha256']
    for rel, expected in read(RUN / 'source_lock.json')['files'].items():
        assert sha(ROOT / rel) == expected, rel
    for rel, expected in lock['inputs_and_upstream'].items():
        assert sha(REPO / rel) == expected, rel
    for rel, expected in lock['files'].items():
        assert sha(RUN / rel) == expected, rel
    assert not lock['final_validation_eligible'] and lock['labels_read'] == []
    return lock


def items():
    legacy = read(LEGACY / 'public_index.json')
    public = read(PUBLIC / 'public_index.json')
    return legacy + [dict(p, group='public', input=p['relative_path'],
                          upstream=str((PUBLIC / 'predictions' / (p['id'] + '.json.gz')).relative_to(ROOT)))
                     for p in public]


def predict_case(item):
    if item['group'] != 'public':
        baseline, count = dev6_prediction(item)
        locked = read(LEGACY / 'predictions' / item['group'] / (item['id'] + '.json.gz'))
        assert baseline == locked, ('dev6 replay mismatch', item['id'])
        model = WorkbookModel.from_xlsx(ROOT / item['input'])
    else:
        report = read(ROOT / item['upstream'])
        if report['status'] != 'inference_complete_unscored':
            return {'id': item['id'], 'status': report['status'], 'rows': [],
                    'upstream_error': report['error'], 'business_labels_available': False,
                    'note': 'Retained unsupported case; no formulas read in dev11.'}
        baseline = report['predictions']['dev6']
        model = WorkbookModel.from_xlsx(REPO / item['input'])
        count = len(model.formulas)
    before = dict(model.formulas)
    prior_sha = hashlib.sha256(json.dumps(baseline, sort_keys=True).encode()).hexdigest()
    result = qualify(model, baseline)
    assert before == model.formulas
    assert prior_sha == hashlib.sha256(json.dumps(baseline, sort_keys=True).encode()).hexdigest()
    assert len(result['rows']) == count
    assert {r['cell'] for r in result['rows']} == {s+'!'+a for s, a in before}
    return result


def predict():
    if RUN.exists():
        raise SystemExit('Preserve existing dev11 run')
    index = items()
    sources = sorted((ROOT / 'scripts').glob('*.py'))
    sources += sorted((ROOT / 'tests').glob('*.py'))
    sources += sorted((ROOT / 'baseline/source').rglob('*.py'))
    save(RUN / 'source_lock.json', {'selector': VERSION,
         'files': {str(p.relative_to(ROOT)): sha(p) for p in sources}})
    save(RUN / 'public_index.json', index)
    files, inputs, timings = {}, {}, []
    for item in index:
        for field in ['input', 'upstream', 'parallel_metadata']:
            if field not in item:
                continue
            path = (REPO if item['group'] == 'public' and field == 'input' else ROOT) / item[field]
            digest = sha(path)
            expected = item.get(field+'_sha256')
            if item['group'] == 'public' and field == 'input':
                expected = item['sha256']
            if expected:
                assert digest == expected
            inputs[str(path.relative_to(REPO))] = digest
    for path in [LEGACY / 'public_index.json', LEGACY / 'prediction_lock.json',
                 PUBLIC / 'prediction_lock.json', PUBLIC / 'public_index.json']:
        inputs[str(path.relative_to(REPO))] = sha(path)
    for item in index:
        if item['group'] != 'public':
            path = LEGACY / 'predictions' / item['group'] / (item['id']+'.json.gz')
            inputs[str(path.relative_to(REPO))] = sha(path)
    accesses, active = set(), [True]
    guard_prediction(accesses, active)
    start, cpu = time.perf_counter(), time.process_time()
    for item in index:
        started = time.perf_counter()
        result = predict_case(item)
        path = RUN / 'predictions' / item['group'] / (item['id']+'.json.gz')
        save(path, result)
        files[str(path.relative_to(RUN))] = sha(path)
        timings.append({'id': item['id'], 'group': item['group'],
                        'wall_seconds': time.perf_counter()-started,
                        'formula_rows': len(result['rows']),
                        'blocked': result.get('complete_ast_gate_summary', {}).get('blocked_proposals', 0)})
        print(item['group'], item['id'], 'rows', len(result['rows']),
              'blocked', timings[-1]['blocked'], flush=True)
    active[0] = False
    runtime = {'wall_seconds': time.perf_counter()-start, 'cpu_seconds': time.process_time()-cpu,
               'cases': timings, 'gpu_used': False,
               'process_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               'scope': 'Legacy dev6 replay, workbook reload, AST gate; public upstream SG/FG excluded',
               'python': platform.python_version(), 'platform': platform.platform()}
    save(RUN / 'runtime.json', runtime)
    for name in ['runtime.json', 'public_index.json']:
        files[name] = sha(RUN / name)
    save(RUN / 'prediction_lock.json', {'source_lock_sha256': sha(RUN / 'source_lock.json'),
         'files': files, 'inputs_and_upstream': inputs, 'labels_read': [],
         'accesses': sorted(accesses), 'final_validation_eligible': False,
         'role': 'revealed development; full legacy replay plus unlabelled public gate'})
    print('DEV11 PREDICTIONS LOCKED', len(index), runtime['wall_seconds'], flush=True)


def build_score():
    groups = {}
    for group in GROUPS:
        cases = []
        for item in [i for i in read(RUN / 'public_index.json') if i['group'] == group]:
            truth, observed = truth_and_observed(item)
            old = read(LEGACY / 'predictions' / group / (item['id']+'.json.gz'))
            new = read(RUN / 'predictions' / group / (item['id']+'.json.gz'))
            cases.append({'id': item['id'], 'dev6': metrics(old, truth, observed),
                          'dev11': metrics(new, truth, observed),
                          'blocked': new['complete_ast_gate_summary']['blocked_proposals']})
        totals = {}
        for name in ['dev6', 'dev11']:
            counts = {k: sum(c[name][k] for c in cases) for k in
                      ['proposals', 'correct', 'wrong', 'errors', 'harmful_correct_cells']}
            counts.update(precision=counts['correct']/counts['proposals'] if counts['proposals'] else None,
                          coverage=counts['correct']/counts['errors'] if counts['errors'] else None)
            totals[name] = counts
        groups[group] = {'cases': cases, 'totals': totals}
    public = []
    for item in [i for i in read(RUN / 'public_index.json') if i['group'] == 'public']:
        pred = read(RUN / 'predictions/public' / (item['id']+'.json.gz'))
        public.append({'id': item['id'], 'status': pred.get('status', 'inference_complete_unscored'),
                       'rows': len(pred['rows']), **pred.get('complete_ast_gate_summary', {}),
                       'precision': None, 'coverage': None})
    return {'role': 'revealed development; no final accuracy evidence',
            'prediction_lock_sha256': sha(RUN / 'prediction_lock.json'),
            'groups': groups, 'public': public, 'final_validation_eligible': False}


def score():
    verify()
    target = RUN / 'score.json'
    if target.exists():
        raise SystemExit('Preserve locked score')
    result = build_score()
    save(target, result)
    print(json.dumps({k: v['totals'] for k, v in result['groups'].items()}, indent=2))
    print(json.dumps(result['public'], indent=2))


def replay():
    verify()
    accesses, active = set(), [True]
    guard_prediction(accesses, active)
    index = read(RUN / 'public_index.json')
    start = time.perf_counter()
    for item in index:
        actual = predict_case(item)
        expected = read(RUN / 'predictions' / item['group'] / (item['id']+'.json.gz'))
        assert actual == expected, item['id']
        print('Replayed', item['group'], item['id'], flush=True)
    active[0] = False
    assert build_score() == read(RUN / 'score.json')
    save(ROOT / 'qa/DEV11_REPLAY_20261018.json', {
         'cases': len(index), 'all_predictions_replayed_exactly': True,
         'score_recomputed_after_replay': True, 'wall_seconds': time.perf_counter()-start,
         'labels_read_during_replay': False, 'final_validation_eligible': False,
         'prediction_lock_sha256': sha(RUN / 'prediction_lock.json'),
         'score_sha256': sha(RUN / 'score.json'), 'utc': dt.datetime.now(dt.timezone.utc).isoformat()})
    print('DEV11 REPLAY VERIFIED', len(index))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['predict', 'score', 'verify', 'replay'])
    args = parser.parse_args()
    {'predict': predict, 'score': score, 'verify': verify, 'replay': replay}[args.stage]()
