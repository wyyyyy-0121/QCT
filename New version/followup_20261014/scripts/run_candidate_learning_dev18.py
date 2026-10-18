"""Memory bounded whole-origin training/inference; score in a separate process."""
from collections import Counter, defaultdict
from pathlib import Path
import argparse
import gc
import os
import platform
import resource
import sys
import time
import joblib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read, save, sha
from build_candidates_dev18 import DATA, compact, protection
from candidate_features_dev16 import PARAMETERS, THRESHOLD, MARGIN
from train_candidate_dev16 import infer
from run_candidate_learning_dev16 import metrics, totals

RUN = ROOT/'development/candidate_learning_dev18_v1'
MODES = ['dev11', 'learned_only', 'keep_base_plus_learned']

def verify_features():
    lock = read(DATA/'feature_lock.json')
    for rel,v in lock['files'].items(): assert sha(DATA/rel)==v, rel
    for rel,v in lock['inputs'].items(): assert sha(ROOT/rel)==v, rel
    for rel,v in lock['sources'].items(): assert sha(ROOT/rel)==v, rel
    assert lock['labels_read']==[]

def weights(rows):
    counts = Counter(r['case'] for r in rows)
    families = defaultdict(set); sources = defaultdict(set)
    for r in rows:
        families[r['source'],r['family']].add(r['case'])
        sources[r['source']].add(r['family'])
    w = np.asarray([1/(len(sources[r['source']])*len(families[r['source'],r['family']])*counts[r['case']]) for r in rows])
    return w*len(w)/w.sum()

def fit_fold(fold):
    path = DATA/fold['train_label_file']; assert sha(path)==fold['train_label_sha256']
    labels = read(path); rows = labels['rows']
    assert labels['training_cases']==fold['train_cases'] and labels['heldout_cases']==fold['test_cases']
    assert not set(fold['train_cases']) & set(fold['test_cases'])
    assert all(r['case'] in fold['train_cases'] and r['source'] != fold['origin'] for r in rows)
    names = read(DATA/'feature_schema.json')['names']
    x = np.empty((len(rows),len(names)),dtype=np.float32)
    y = np.asarray([r['label'] for r in rows],dtype=np.int8)
    by_case = defaultdict(dict)
    for n,r in enumerate(rows): by_case[r['case']][r['id']] = n
    assert sum(map(len,by_case.values())) == len(rows)
    for case, ids in by_case.items():
        payload = read(DATA/'features'/(case.replace('/', '__')+'.json.gz'))
        found = 0
        for c in payload['candidates']:
            if c['id'] in ids: x[ids[c['id']]] = c['features']; found += 1
        assert found == len(ids)
    w = weights(rows); counts = Counter(r['source'] for r in rows)
    sums = {s:float(sum(w[n] for n,r in enumerate(rows) if r['source']==s)) for s in counts}
    assert max(sums.values())-min(sums.values()) < 1e-5
    model = HistGradientBoostingClassifier(**PARAMETERS)
    model.fit(x,y,sample_weight=w)
    return model, {'rows':len(rows),'positive':int(y.sum()), 'negative':int((y==0).sum()),
                   'source_row_counts':dict(counts),'source_weight_sums':sums, 'features':len(names)}

def training_protection():
    # Permit only the current training label file; deny all heldout and case labels.
    active, accesses, allowed, reads = [True], set(), [None], set()
    from run_selector_dev8 import guard_prediction
    guard_prediction(accesses, active)
    def guard(event,args):
        if active[0] and event=='open' and isinstance(args[0],(str,bytes)):
            name=args[0].decode() if isinstance(args[0],bytes) else args[0]
            if any(k in name for k in ['prepare_candidate','prepare_multisource','product_sum_oracle','/heldout_truth','/case_labels/']):
                raise PermissionError('Heldout labels/oracle forbidden')
            if '/training_labels/' in name:
                p=str(Path(name).resolve())
                if p != allowed[0]: raise PermissionError('Wrong fold training labels')
                reads.add(p)
    sys.addaudithook(guard)
    for p in [DATA/'heldout_truth.json.gz', DATA/'case_labels/test.json.gz', DATA/'training_labels/test.json.gz']:
        try: p.read_bytes()
        except PermissionError: pass
        else: raise AssertionError('training guard')
    return active, accesses, allowed, reads

def predict():
    if RUN.exists(): raise SystemExit('Preserve run')
    verify_features()
    sources = sorted((ROOT/'scripts').glob('*.py'))+sorted((ROOT/'tests').glob('*.py'))
    sources += [ROOT/'CANDIDATE_EXPANSION_DEV18_PLAN_20261018.md']
    save(RUN/'source_lock.json', {'files':{str(p.relative_to(ROOT)):sha(p) for p in sources}})
    active, accesses, allowed, reads = training_protection()
    files = {}; runtime = []; wall,cpu = time.perf_counter(),time.process_time()
    for fold in read(DATA/'fold_index.json')['folds']:
        allowed[0] = str((DATA/fold['train_label_file']).resolve())
        t,c = time.perf_counter(),time.process_time()
        learner, summary = fit_fold(fold)
        allowed[0] = None
        path = RUN/'models'/(fold['id']+'.joblib.gz'); path.parent.mkdir(parents=True,exist_ok=True)
        joblib.dump(learner,path,compress=('gzip',3)); files[str(path.relative_to(RUN))]=sha(path)
        counts=Counter()
        for case in fold['test_cases']:
            payload=read(DATA/'features'/(case.replace('/', '__')+'.json.gz'))
            # Float32 is a preregistered storage representation, used at fit and inference.
            for row in payload['candidates']: row['features']=[float(v) for v in np.asarray(row['features'],dtype=np.float32)]
            pred={'case':case,'fold':fold['id'],'dev11':payload['baseline'],**infer(learner,payload)}
            p=RUN/'predictions'/fold['id']/(case.replace('/', '__')+'.json.gz')
            compact(p,pred);files[str(p.relative_to(RUN))]=sha(p)
            counts.update({m:len(pred[m]) for m in MODES})
        runtime.append({'fold':fold['id'],**summary,'suggestions':dict(counts),
                        'wall_seconds':time.perf_counter()-t,'cpu_seconds':time.process_time()-c})
        print('trained',fold['id'],summary,'suggestions',dict(counts),flush=True)
        del learner; gc.collect()
    active[0]=False
    save(RUN/'runtime.json',{'folds':runtime,'wall_seconds':time.perf_counter()-wall,'cpu_seconds':time.process_time()-cpu,
         'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'gpu_used':False,'parameters':PARAMETERS,
         'threshold':THRESHOLD,'margin':MARGIN,'python':platform.python_version(),'sklearn':sklearn.__version__,
         'feature_storage':'float32 at fitting and inference','thread_environment':{k:os.getenv(k) for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS']},
         'scope':'feature loading, source weighting, five fits and heldout inference; upstream/feature generation excluded'})
    files['runtime.json']=sha(RUN/'runtime.json')
    save(RUN/'prediction_lock.json',{'source_lock_sha256':sha(RUN/'source_lock.json'),'files':files,
         'feature_lock_sha256':sha(DATA/'feature_lock.json'),'label_preparation_lock_sha256':sha(DATA/'label_preparation_lock.json'),
         'fold_index_sha256':sha(DATA/'fold_index.json'),'training_labels_read':sorted(reads),'heldout_labels_read':[],
         'accesses':sorted(accesses),'oracle_guard_exercised':True,'final_validation_eligible':False})
    print('DEV18 MODELS AND PREDICTIONS LOCKED',flush=True)

def verify():
    verify_features();lock=read(RUN/'prediction_lock.json')
    assert sha(RUN/'source_lock.json')==lock['source_lock_sha256']
    for rel,v in read(RUN/'source_lock.json')['files'].items(): assert sha(ROOT/rel)==v,rel
    for rel,v in lock['files'].items(): assert sha(RUN/rel)==v,rel
    for n in ['feature_lock','label_preparation_lock','fold_index']: assert sha(DATA/(n+'.json'))==lock[n+'_sha256']
    for rel,v in read(DATA/'label_preparation_lock.json')['upstream_labels'].items(): assert sha(ROOT/rel)==v,rel
    assert lock['heldout_labels_read']==[]

def score():
    verify();assert not (RUN/'score.json').exists()
    for rel,v in read(DATA/'label_preparation_lock.json')['files'].items(): assert sha(DATA/rel)==v,rel
    truth=read(DATA/'heldout_truth.json.gz');cases=[]
    for fold in read(DATA/'fold_index.json')['folds']:
        for case in fold['test_cases']:
            t=truth['cases'][case]
            labels=read(DATA/'case_labels'/(case.replace('/', '__')+'.json.gz'))
            small_truth={'cases':{case:t},'candidate_labels':{case:labels}}
            pred=read(RUN/'predictions'/fold['id']/(case.replace('/', '__')+'.json.gz'))
            row={'case':case,'fold':fold['id'],**{k:t[k] for k in ['origin_group','family','group','scenario']}}
            for mode in MODES: row[mode]=metrics(pred[mode],case,small_truth)
            payload=read(DATA/'features'/(case.replace('/', '__')+'.json.gz'))
            covered={c['cell'] for c in payload['candidates'] if c['eligible'] and labels[c['id']]==1}
            row['candidate_pool_correct_error_ceiling']=len(covered)
            row['missing_correct_candidate_cells']=sorted(set(t['errors'])-covered)
            cases.append(row)
    assert len(cases)==213 and len({r['case'] for r in cases})==213
    report={'cases':cases,'all':{m:totals(cases,m) for m in MODES},
            'candidate_pool_correct_error_ceiling':sum(r['candidate_pool_correct_error_ceiling'] for r in cases),
            'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),'final_validation_eligible':False,
            'accepted_final_sources':0,'accepted_final_families':0,'main_candidate_adopted':False,
            'unknown_outputs_kept_in_denominator':True,'role':'revealed development whole-origin cross-fitting, not final validation'}
    for key in ['origin_group','family','group','scenario']:
        report[key]={str(v):{'metrics':{m:totals([r for r in cases if r[key]==v],m) for m in MODES},
                            'candidate_pool_correct_error_ceiling':sum(r['candidate_pool_correct_error_ceiling'] for r in cases if r[key]==v)}
                     for v in sorted({r[key] for r in cases},key=str)}
    save(RUN/'score.json',report)
    print(report['all'],flush=True)
    for s,r in report['origin_group'].items(): print(s,r,flush=True)

def replay():
    verify();active,accesses=protection();count=0;wall=time.perf_counter()
    for fold in read(DATA/'fold_index.json')['folds']:
        learner=joblib.load(RUN/'models'/(fold['id']+'.joblib.gz'))
        for case in fold['test_cases']:
            payload=read(DATA/'features'/(case.replace('/', '__')+'.json.gz'))
            for row in payload['candidates']: row['features']=[float(v) for v in np.asarray(row['features'],dtype=np.float32)]
            old=read(RUN/'predictions'/fold['id']/(case.replace('/', '__')+'.json.gz'))
            new=infer(learner,payload)
            for k,v in new.items(): assert v==old[k],(case,k)
            count+=1
        print('replayed',fold['id'],flush=True)
    active[0]=False
    p=ROOT/'qa/CANDIDATE_LEARNING_DEV18_REPLAY_20261018.json';assert not p.exists()
    save(p,{'cases':count,'all_probabilities_and_suggestions_identical':True,'labels_read':[],
            'accesses':sorted(accesses),'wall_seconds':time.perf_counter()-wall,'prediction_lock_sha256':sha(RUN/'prediction_lock.json')})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['predict','score','replay','verify'])
    args=p.parse_args();{'predict':predict,'score':score,'replay':replay,'verify':verify}[args.mode]()
