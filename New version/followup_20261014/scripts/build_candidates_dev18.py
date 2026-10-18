"""Construct expanded features before label preparation, with enforced read isolation."""
from collections import defaultdict
from pathlib import Path
import gzip
import json
import resource
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read, save, sha
from run_selector_dev8 import guard_prediction
from build_candidates_dev16 import items as old_items, upstream, uid
from candidate_features_dev16 import Context
from candidate_expansion_dev18 import extend, extra_features, VERSION
from formulaguard.workbook import WorkbookModel

DATA = ROOT/'development/candidate_expansion_dev18_data_v1'
OLD = ROOT/'development/candidate_learning_dev16_data_v1'
PUBLIC = ROOT/'development/multisource_dev17_v1'

def compact(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    with gzip.GzipFile(filename=str(path), mode='wb', compresslevel=3, mtime=0) as f:
        f.write(payload)

def index():
    result = old_items()
    for item in read(PUBLIC/'public_index.json'):
        result.append({**item, 'case':'multisource/'+item['id'], 'group':'public_relations',
                       'origin_group':item['origin'],
                       'upstream':{'public_pack':str((PUBLIC/'predictions'/(item['id']+'.json.gz')).relative_to(ROOT))}})
    assert len(result) == 213
    return result

def upstream_data(item):
    if item['group'] == 'public_relations':
        p = read(ROOT/item['upstream']['public_pack'])
        return p['candidate_pool'], p['dev11']['rows'], p['observed_formulas']
    payload = read(OLD/'features'/(item['case'].replace('/', '__')+'.json.gz'))
    models, observed = upstream(item)
    return payload['candidates'], models['dev11']['rows'], observed

def protection():
    active, accesses = [True], set()
    guard_prediction(accesses, active)
    def guard(event, args):
        if active[0] and event == 'open' and isinstance(args[0], (str, bytes)):
            name = str(args[0])
            if any(s in name for s in ['prepare_candidate', 'prepare_multisource', 'prepare_annotation',
                                       'product_sum_oracle', '/heldout_truth', '/training_labels/']):
                raise PermissionError('No author, oracle or label access during features/prediction')
    sys.addaudithook(guard)
    for p in [DATA/'heldout_truth.json.gz', ROOT/'scripts/product_sum_oracle_dev17.py']:
        try: p.read_bytes()
        except PermissionError: pass
        else: raise AssertionError('label guard failed')
    return active, accesses

def case_features(item, old_names):
    old, base_rows, observed = upstream_data(item)
    model = WorkbookModel.from_xlsx(ROOT/item['input'])
    assert {s+'!'+a:f for (s,a),f in model.formulas.items()} == observed
    base = {r['cell']:r for r in base_rows}
    context = Context(model, item['parallel_sheets'])
    pools = defaultdict(dict); previous = {}
    for c in old:
        pools[c['cell']].setdefault(c['formula'], set()).update(c['origins'])
        previous[c['cell'],c['formula']] = dict(zip(old_names, c['features']))
    first_sheet, first_address = next(iter(model.formulas))
    first_formula = model.formulas[first_sheet, first_address]
    names = sorted(old_names + list(extra_features(model, first_sheet, first_address,
                                                   first_formula, first_formula, set())))
    records = []; metadata = {}
    for cell, pool in sorted(pools.items()):
        sheet, address = cell.rsplit('!', 1)
        expanded, meta = extend(observed[cell], pool); metadata[cell] = meta
        for formula, origins in sorted(expanded.items()):
            f = previous.get((cell, formula))
            if f is None:
                f = context.features(sheet, address, formula, origins, base[cell])
            f = {**f, **extra_features(model, sheet, address, observed[cell], formula, origins)}
            if names is None: names = sorted(f)
            assert sorted(f) == names
            records.append({'id':uid(item['case'], cell, formula), 'cell':cell, 'formula':formula,
                            'origins':sorted(origins), 'eligible':bool(f['complete_ast_pair'] and f['target_visible']),
                            'features':[f[k] for k in names]})
    baseline = [{'cell':r['cell'], 'suggested_formula':r['suggested_formula'], 'status':'propose'}
                for r in base_rows if r.get('status') == 'propose' and r.get('suggested_formula')
                and r['suggested_formula'] != observed[r['cell']]]
    payload = {'case':item['case'], 'candidates':records, 'baseline':baseline,
               'formula_count':len(model.formulas), 'expansion':metadata,
               'unflagged_formula_cells':len(model.formulas)-len(pools)}
    return payload, names

def build():
    if DATA.exists(): raise SystemExit('Preserve dataset; choose a new version')
    from run_candidate_learning_dev16 import verify as verify16
    from run_multisource_dev17 import verify as verify17
    verify16(); verify17()
    cases = index(); save(DATA/'public_index.json', cases)
    old_names = read(OLD/'feature_schema.json')['names']
    active, accesses = protection()
    files = {}; inputs = {}; timings = []; names = None
    wall, cpu = time.perf_counter(), time.process_time()
    for item in cases:
        assert sha(ROOT/item['input']) == item['input_sha256']
        inputs[item['input']] = item['input_sha256']
        for rel in item['upstream'].values(): inputs[rel] = sha(ROOT/rel)
        if item['group'] != 'public_relations':
            p = OLD/'features'/(item['case'].replace('/', '__')+'.json.gz')
            inputs[str(p.relative_to(ROOT))] = sha(p)
        t = time.perf_counter()
        payload, schema = case_features(item, old_names)
        if names is None: names = schema
        assert schema == names
        path = DATA/'features'/(item['case'].replace('/', '__')+'.json.gz')
        compact(path, payload); files[str(path.relative_to(DATA))] = sha(path)
        timings.append({'case':item['case'], 'formulas':payload['formula_count'],
                        'targets':len(payload['expansion']), 'candidates':len(payload['candidates']),
                        'truncated_targets':sum(r['search_truncated'] for r in payload['expansion'].values()),
                        'wall_seconds':time.perf_counter()-t})
        print(item['case'], 'candidates', len(payload['candidates']), flush=True)
    active[0] = False
    inputs[str((OLD/'feature_schema.json').relative_to(ROOT))] = sha(OLD/'feature_schema.json')
    save(DATA/'feature_schema.json', {'version':VERSION, 'names':names, 'feature_count':len(names), 'labels_read':[]})
    save(DATA/'runtime.json', {'cases':timings, 'wall_seconds':time.perf_counter()-wall,
         'cpu_seconds':time.process_time()-cpu, 'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
         'scope':'expanded features; cached original paper/dev11 upstream computation excluded', 'gpu_used':False})
    for n in ['public_index.json', 'feature_schema.json', 'runtime.json']: files[n] = sha(DATA/n)
    sources = [Path(__file__), ROOT/'scripts/candidate_expansion_dev18.py', ROOT/'scripts/formula_candidates_dev1.py',
               ROOT/'scripts/candidate_features_dev16.py', ROOT/'CANDIDATE_EXPANSION_DEV18_PLAN_20261018.md']
    sources += sorted((ROOT/'tests').glob('*dev18*.py'))
    save(DATA/'feature_lock.json', {'files':files, 'inputs':inputs,
         'sources':{str(p.relative_to(ROOT)):sha(p) for p in sources},
         'labels_read':[], 'accesses':sorted(accesses), 'oracle_guard_exercised':True, 'final_validation_eligible':False})
    print('DEV18 FEATURES LOCKED', len(cases), sum(r['candidates'] for r in timings), flush=True)

if __name__ == '__main__': build()
