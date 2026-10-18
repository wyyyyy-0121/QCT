"""Freeze a reference-consensus hypothesis on revealed development inputs."""
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
REPO = ROOT.parents[1]
RUN = ROOT/'development/bidirectional_reference_dev13_v1'
OLD = ROOT/'development/selector_dev12_reconciliation_v1'
PUBLIC = ROOT/'development/public_candidate_pipeline_dev10'
STATIC = ROOT/'development/static_ooxml_view_dev2'
sys.path.insert(0, str(ROOT/'scripts'))
sys.path.insert(0, str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
from bidirectional_reference_dev13 import candidates, merge, supported_ast, VERSION, PARAMETERS
from run_selector_dev5 import read, save, sha, metrics, total
from run_selector_dev8 import guard_prediction, truth_and_observed
from run_selector_dev12 import verify as verify_old
from run_static_view_dev2 import verify as verify_static

VARIANTS = ['both', 'row_only', 'column_only']


def items():
    index = []
    for item in read(OLD/'public_index.json'):
        upstream = OLD/'predictions'/item['group']/(item['id']+'.json.gz')
        index.append({**item, 'input_scope': 'root',
                      'upstream_prediction': str(upstream.relative_to(ROOT)),
                      'upstream_prediction_sha256': sha(upstream)})
    for item in read(PUBLIC/'public_index.json'):
        static = STATIC/'predictions'/(item['id']+'.json.gz')
        upstream = static if static.exists() else PUBLIC/'predictions'/(item['id']+'.json.gz')
        prior = ROOT/'development/selector_dev11_complete_ast_v1/predictions/public'/(item['id']+'.json.gz')
        index.append({**item, 'group': 'public', 'input_scope': 'repo',
                      'input': item['relative_path'], 'input_sha256': item['sha256'],
                      'observation_from_static': static.exists(),
                      'upstream_prediction': str(upstream.relative_to(ROOT)),
                      'upstream_prediction_sha256': sha(upstream),
                      'prior': str(prior.relative_to(ROOT)), 'prior_sha256': sha(prior)})
    assert len(index) == 178
    return index


def load_case(item):
    upstream = read(ROOT/item['upstream_prediction'])
    if item['group'] != 'public':
        observed, prior = upstream['observed_formulas'], upstream['dev11']
    elif item['observation_from_static']:
        if upstream['status'] == 'input_rejected':
            return None, None
        observed, prior = upstream['observed_formulas'], upstream['dev11']
    else:
        if upstream['status'] != 'inference_complete_unscored':
            raise AssertionError('Unexpected previously failed input retained: '+item['id'])
        model = WorkbookModel.from_xlsx(REPO/item['input'])
        observed = {s+'!'+a:v for (s,a),v in model.formulas.items()}
        prior = read(ROOT/item['prior'])
    assert len(prior['rows']) == len(observed)
    assert {r['cell'] for r in prior['rows']} == set(observed)
    return observed, prior


def prediction(item):
    observed, prior = load_case(item)
    if observed is None:
        return {'id': item['id'], 'status': 'input_rejected',
                'reason': 'protected_manifest_rejection_retained', 'formula_bodies_read': False,
                'variants': {v:{} for v in VARIANTS}}
    formulas = {tuple(label.rsplit('!',1)): text for label,text in observed.items()}
    before = dict(formulas)
    result = candidates(formulas)
    assert formulas == before
    assert all(set(c) <= set(observed) for c in result.values())
    old_proposals = {r['cell'] for r in prior['rows'] if r.get('status') == 'propose'}
    return {'id': item['id'], 'status': 'candidate_analysis_complete',
            'formula_cells': len(formulas),
            'supported_formula_cells': sum(supported_ast(f) is not None for f in formulas.values()),
            'variants': result,
            'additional_to_dev11': {v: len(set(result[v])-old_proposals) for v in VARIANTS},
            'labels_read': [], 'business_correctness_proven': False,
            'automatic_edit_applied': False, 'final_validation_eligible': False}


def target(item):
    return RUN/'predictions'/item['group']/(item['id']+'.json.gz')


def verify():
    lock = read(RUN/'prediction_lock.json')
    assert sha(RUN/'source_lock.json') == lock['source_lock_sha256']
    for rel, expected in read(RUN/'source_lock.json')['files'].items():
        assert sha(ROOT/rel) == expected, rel
    for rel, expected in lock['inputs_and_upstream'].items():
        assert sha(REPO/rel) == expected, rel
    for rel, expected in lock['files'].items():
        assert sha(RUN/rel) == expected, rel
    assert lock['labels_read'] == [] and not lock['final_validation_eligible']
    return lock


def predict():
    if RUN.exists():
        raise SystemExit('Preserve prior run; use a new experiment version')
    verify_old(); verify_static()
    index = items()
    sources = sorted((ROOT/'scripts').glob('*.py'))
    sources += sorted((ROOT/'tests').glob('*.py'))
    sources += sorted((ROOT/'baseline/source').rglob('*.py'))
    sources.append(ROOT/'BIDIRECTIONAL_DEV13_PLAN_20261018.md')
    save(RUN/'source_lock.json', {'version': VERSION, 'parameters': PARAMETERS,
         'files': {str(p.relative_to(ROOT)):sha(p) for p in sources}})
    save(RUN/'public_index.json', index)
    inputs = {}
    for item in index:
        path = (ROOT if item['input_scope']=='root' else REPO)/item['input']
        assert sha(path) == item['input_sha256'], item['id']
        inputs[str(path.relative_to(REPO))] = item['input_sha256']
        for key in ['upstream_prediction','prior']:
            if key in item:
                path = ROOT/item[key]
                assert sha(path) == item[key+'_sha256']
                inputs[str(path.relative_to(REPO))] = sha(path)
    for path in [OLD/'prediction_lock.json', OLD/'public_index.json',
                 STATIC/'prediction_lock.json', PUBLIC/'prediction_lock.json']:
        inputs[str(path.relative_to(REPO))] = sha(path)
    accesses, active = set(), [True]
    guard_prediction(accesses, active)
    start, cpu = time.perf_counter(), time.process_time()
    files, timings = {}, []
    for item in index:
        t = time.perf_counter()
        result = prediction(item)
        save(target(item), result)
        files[str(target(item).relative_to(RUN))] = sha(target(item))
        timings.append({'group': item['group'], 'id': item['id'],
                        'wall_seconds': time.perf_counter()-t,
                        'status': result['status']})
        print(item['group'], item['id'], result['status'],
              result.get('additional_to_dev11'), flush=True)
    active[0] = False
    runtime = {'wall_seconds': time.perf_counter()-start, 'cpu_seconds': time.process_time()-cpu,
               'process_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               'gpu_used': False, 'python': platform.python_version(), 'cases': timings,
               'scope': 'frozen upstream observation read, public formula load where necessary, new candidate rule only; SG/FG/dev11 costs excluded'}
    save(RUN/'runtime.json', runtime)
    for name in ['runtime.json','public_index.json']:
        files[name] = sha(RUN/name)
    save(RUN/'prediction_lock.json', {'source_lock_sha256': sha(RUN/'source_lock.json'),
         'inputs_and_upstream': inputs, 'files': files, 'labels_read': [],
         'accesses': sorted(accesses), 'final_validation_eligible': False,
         'role': 'revealed development ablation; no business scores on public sources'})
    print('DEV13 PREDICTIONS LOCKED', len(index), runtime['wall_seconds'], flush=True)


def build_score():
    controlled = {c['id']:c for c in read(ROOT/'development/reconciliation_dev12_inputs_v1/truth.json')['cases']}
    groups, public = {}, []
    for item in read(RUN/'public_index.json'):
        new = read(target(item))
        if item['group'] == 'public':
            public.append({'id':item['id'], 'status':new['status'],
                           'formula_cells':new.get('formula_cells',0),
                           'additional_to_dev11':new.get('additional_to_dev11'),
                           'precision':None, 'coverage':None})
            continue
        observed, prior = load_case(item)
        if item['group'] == 'controlled_reconciliation':
            truth = controlled[item['id']]
            assert truth['observed_formulas'] == observed
        else:
            truth, independently_recorded = truth_and_observed(item)
            assert observed == independently_recorded
        row = {'id':item['id'], 'dev11':metrics(prior,truth,observed)}
        for variant in VARIANTS:
            row[variant] = metrics(merge(prior,new['variants'][variant]),truth,observed)
        groups.setdefault(item['group'],[]).append(row)
    return {'role':'revealed development ablation; no unseen performance estimate',
            'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),
            'groups':{g:{'cases':rows,'totals':{v:total(rows,v) for v in ['dev11']+VARIANTS}}
                      for g,rows in groups.items()},
            'public':public,'main_candidate_adopted':False,'final_validation_eligible':False}


def score():
    verify()
    if (RUN/'score.json').exists():
        raise SystemExit('Preserve score; replay to verify')
    result = build_score(); save(RUN/'score.json',result)
    print(json.dumps({g:d['totals'] for g,d in result['groups'].items()},indent=2))
    print(json.dumps(result['public'],indent=2))


def replay():
    verify()
    accesses, active = set(), [True]
    guard_prediction(accesses, active)
    index = read(RUN/'public_index.json')
    start, cpu = time.perf_counter(), time.process_time()
    for item in index:
        assert prediction(item) == read(target(item)), item['id']
        print('REPLAY',item['group'],item['id'],flush=True)
    active[0] = False
    assert build_score() == read(RUN/'score.json')
    save(ROOT/'qa/BIDIRECTIONAL_DEV13_REPLAY_20261018.json',{
         'cases':len(index),'all_predictions_replayed_exactly':True,
         'score_recomputed_after_replay':True,'labels_read_during_prediction':False,
         'wall_seconds':time.perf_counter()-start,'cpu_seconds':time.process_time()-cpu,
         'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),
         'score_sha256':sha(RUN/'score.json'),'final_validation_eligible':False,
         'utc':datetime.datetime.now(datetime.timezone.utc).isoformat()})
    print('DEV13 REPLAY VERIFIED',len(index),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage',choices=['predict','score','verify','replay'])
    stage = parser.parse_args().stage
    {'predict':predict,'score':score,'verify':verify,'replay':replay}[stage]()
