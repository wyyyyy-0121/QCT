"""Time and lock dev5 over 83 revealed inputs; score in a separate process.

Only dev5 augmentation is timed here: SG/FG/dev4 costs are in prior runs. This
experiment does not estimate unseen-source performance or run GPU training.
"""
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
BASE = ROOT / 'baseline'
RUN = ROOT / 'development/selector_dev5'
DEV4 = ROOT / 'development/selector_dev4'
CROSS = ROOT / 'development/crossdomain_dev1'
sys.path.insert(0, str(BASE / 'source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
from selector_dev5 import augment, VERSION


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode() + b'\n'
    if path.suffix == '.gz':
        with gzip.GzipFile(filename=str(path), mode='wb', mtime=0) as handle:
            handle.write(payload)
    else:
        path.write_bytes(payload)


def verify_files(root, files):
    for relative, expected in files.items():
        assert sha(root / relative) == expected, relative


def verify_prior():
    for name in ['source_lock.json', 'prediction_lock.json']:
        verify_files(BASE, read(BASE / 'protocol' / name)['files'])
    for run in [DEV4, CROSS]:
        lock = read(run / 'prediction_lock.json')
        assert sha(run / 'source_lock.json') == lock['source_lock_sha256']
        verify_files(ROOT, read(run / 'source_lock.json')['files'])
        verify_files(run, lock['files'])
        verify_files(ROOT, lock.get('inputs_and_upstream', {}))
        if (run / 'public_index.json').exists():
            assert sha(run / 'public_index.json') == lock['public_index_sha256']
            for item in read(run / 'public_index.json'):
                assert sha(run / item['input']) == item['sha256']
        assert lock['labels_read'] == []


def input_index():
    items = []
    for entry in read(BASE / 'protocol/public_index.json'):
        case = entry['id']
        items.append({'id': case, 'group': 'regression',
            'input': str((BASE / 'data' / case / 'input.xlsx').relative_to(ROOT)),
            'upstream': str((DEV4 / 'predictions/regression' / (case+'.json.gz')).relative_to(ROOT)),
            'parallel_sheets': ['A','B','C','D','E']})
    for group, folder in [('stress','semantic_stress_dev1'),('tradeoff','policy_tradeoff_dev1'),
                          ('crossdomain','crossdomain_dev1')]:
        challenge = ROOT / 'development' / folder
        for entry in read(challenge / 'public_index.json'):
            case = entry['id']
            upstream = (CROSS / 'predictions' / (case+'.json.gz') if group == 'crossdomain' else
                        DEV4 / 'predictions' / group / (case+'.json.gz'))
            items.append({'id':case, 'group':group,
                'input':str((challenge / entry['input']).relative_to(ROOT)),
                'upstream':str(upstream.relative_to(ROOT)),
                'parallel_sheets':entry.get('parallel_sheets',['A','B','C','D','E'])})
    assert len(items) == 83
    for item in items:
        item['input_sha256'] = sha(ROOT / item['input'])
        item['upstream_sha256'] = sha(ROOT / item['upstream'])
    return items


def predict():
    if RUN.exists():
        raise SystemExit('Preserve existing dev5 evidence; use another run for a new model')
    verify_prior()
    sources = [Path(__file__), ROOT / 'scripts/selector_dev5.py',
               ROOT / 'scripts/selector_dev3.py', ROOT / 'scripts/selector_dev2.py']
    sources += sorted((BASE / 'source').rglob('*.py'))
    sources += sorted((ROOT / 'tests').glob('*.py'))
    save(RUN / 'source_lock.json', {'version':VERSION,
         'files':{str(p.relative_to(ROOT)):sha(p) for p in sources}})
    items = input_index(); save(RUN / 'public_index.json', items)
    accesses = set()
    def guard(event, args):
        if event == 'open' and isinstance(args[0], (str, bytes)):
            name = str(args[0])
            if any(word in name.casefold() for word in ['truth.json','registration.json',
                    'data_manifest.json','/score','/results/','failure_audit','input_oracle','mutation_log']):
                raise PermissionError('Prediction may not access scoring evidence: '+name)
            if str(ROOT) in name: accesses.add(name)
    sys.addaudithook(guard)
    files = {}; inputs = {}; timings = []
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    for item in items:
        path, upstream = ROOT / item['input'], ROOT / item['upstream']
        assert sha(path) == item['input_sha256']
        assert sha(upstream) == item['upstream_sha256']
        t, c = time.perf_counter(), time.process_time()
        model = WorkbookModel.from_xlsx(path)
        prior = read(upstream)
        if item['group'] == 'crossdomain': prior = prior['dev4']
        before = dict(model.formulas)
        prior_hash = hashlib.sha256(json.dumps(prior, sort_keys=True).encode()).hexdigest()
        result = augment(model, prior, item['parallel_sheets'])
        assert model.formulas == before
        assert hashlib.sha256(json.dumps(prior, sort_keys=True).encode()).hexdigest() == prior_hash
        timing = {'id':item['id'], 'group':item['group'],
            'wall_seconds':time.perf_counter()-t, 'cpu_seconds':time.process_time()-c,
            'process_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'rss_interpretation':'cumulative process high-water mark on Linux',
            'formula_cells':len(before)}
        target = RUN / 'predictions' / item['group'] / (item['id']+'.json.gz')
        save(target, result); files[str(target.relative_to(RUN))] = sha(target)
        inputs[item['input']] = item['input_sha256']; inputs[item['upstream']] = item['upstream_sha256']
        timings.append(timing)
        print(item['group'],item['id'],'proposals',sum(r['status']=='propose' for r in result['rows']),
              'wall_s',round(timing['wall_seconds'],4),'cpu_s',round(timing['cpu_seconds'],4),flush=True)
    runtime = {'command':[sys.executable,*sys.argv], 'cwd':str(Path.cwd()),
        'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'python':platform.python_version(),
        'platform':platform.platform(), 'cases':timings,
        'wall_seconds':time.perf_counter()-start_wall, 'cpu_seconds':time.process_time()-start_cpu,
        'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'scope':'input loading and dev5 augmentation only; prior SG/FG/dev4 execution excluded',
        'gpu_used':False}
    save(RUN / 'runtime.json',runtime); files['runtime.json'] = sha(RUN / 'runtime.json')
    save(RUN / 'prediction_lock.json', {'files':files, 'inputs_and_upstream':inputs,
        'source_lock_sha256':sha(RUN / 'source_lock.json'),
        'public_index_sha256':sha(RUN / 'public_index.json'), 'labels_read':[],
        'accesses':sorted(accesses), 'role':'revealed development only; not final validation'})
    print('Locked',len(items),'cases;',runtime['wall_seconds'],'seconds',flush=True)


def verify_run():
    lock = read(RUN / 'prediction_lock.json')
    assert sha(RUN / 'source_lock.json') == lock['source_lock_sha256']
    assert sha(RUN / 'public_index.json') == lock['public_index_sha256']
    verify_files(ROOT, read(RUN / 'source_lock.json')['files'])
    verify_files(RUN, lock['files'])
    verify_files(ROOT, lock['inputs_and_upstream'])
    assert lock['labels_read'] == []


def metrics(pred, truth, observed):
    rows = pred['rows']; expected = truth['expected_formulas']; errors = set(truth['errors'])
    assert len(rows) == len({r['cell'] for r in rows}) == len(expected) == len(observed)
    assert {r['cell'] for r in rows} == set(expected) == set(observed)
    assert errors == {cell for cell in expected if expected[cell] != observed[cell]}
    proposals = {r['cell']:r['suggested_formula'] for r in rows if r['status']=='propose'
                 and r.get('suggested_formula') and r['suggested_formula'] != observed[r['cell']]}
    correct = sum(formula == expected[cell] for cell, formula in proposals.items())
    return {'proposals':len(proposals),'correct':correct,'wrong':len(proposals)-correct,
        'errors':len(errors), 'precision':correct/len(proposals) if proposals else None,
        'coverage':correct/len(errors) if errors else None,
        'harmful_correct_cells':sum(cell not in errors for cell in proposals),
        'statuses':dict(Counter(r['status'] for r in rows)),
        'reason_counts':dict(Counter(r.get('reason','unspecified') for r in rows)),
        'wrong_examples':[{'cell':cell,'observed':observed[cell], 'proposed':formula,
                           'expected':expected[cell]} for cell, formula in proposals.items()
                          if formula != expected[cell]][:10]}


def total(cases, name):
    counts = {key:sum(c[name][key] for c in cases)
              for key in ['proposals','correct','wrong','errors','harmful_correct_cells']}
    return {**counts,'precision':counts['correct']/counts['proposals'] if counts['proposals'] else None,
        'coverage':counts['correct']/counts['errors'] if counts['errors'] else None}


def score():
    if (RUN / 'score.json').exists(): raise SystemExit('Preserve existing scores')
    verify_run(); reports = {}
    for group, folder in [('regression',None),('stress','semantic_stress_dev1'),
                          ('tradeoff','policy_tradeoff_dev1'),('crossdomain','crossdomain_dev1')]:
        challenge = ROOT / 'development' / folder if folder else BASE
        entries = read(BASE / 'protocol/data_manifest.json') if folder is None else read(challenge / 'truth.json')['cases']
        cases = []
        for entry in entries:
            case = entry['id']
            truth = read(BASE / 'data' / case / 'truth.json') if folder is None else entry
            if group == 'regression':
                observed = read(BASE / 'predictions' / case / 'input_formulas.json.gz')
            else:
                old = read(challenge / 'predictions' / (case+('.json.gz' if group=='crossdomain' else '.json')))
                observed = old['observed_formulas']
            upstream = read(CROSS / 'predictions' / (case+'.json.gz'))['dev4'] if group=='crossdomain' else read(DEV4 / 'predictions' / group / (case+'.json.gz'))
            prediction = read(RUN / 'predictions' / group / (case+'.json.gz'))
            result = {'id':case,'family':entry.get('family',entry.get('scenario')),
                      'scenario':entry.get('scenario'), 'dev4':metrics(upstream,truth,observed),
                      'dev5':metrics(prediction,truth,observed)}
            cases.append(result)
            print(group,case,'dev5',result['dev5']['correct'],result['dev5']['wrong'],flush=True)
        reports[group] = {'cases':cases}
        if group in ['regression','crossdomain']:
            reports[group]['totals'] = {name:total(cases,name) for name in ['dev4','dev5']}
        else:
            reports[group]['pooled_acceptance_metric'] = False
        if group == 'crossdomain':
            reports[group]['families'] = {family:{name:total([c for c in cases if c['family']==family],name)
                for name in ['dev4','dev5']} for family in sorted({c['family'] for c in cases})}
    save(RUN / 'score.json', {'role':'revealed development only; no final validation claim',
        **reports, 'prediction_lock_sha256':sha(RUN / 'prediction_lock.json')})
    print(json.dumps({k:v['totals'] for k,v in reports.items() if 'totals' in v},indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('stage',choices=['predict','score','verify'])
    args = parser.parse_args(); {'predict':predict,'score':score,'verify':verify_run}[args.stage]()
