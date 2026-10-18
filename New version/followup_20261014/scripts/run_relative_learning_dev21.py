"""Fit source-heldout candidate-versus-observed relative preferences."""
from collections import Counter,defaultdict
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
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from build_candidates_dev18 import compact,protection
from build_keep_features_dev21 import DATA,BASE,case_data,verify as verify_features,case_path
from build_signed_features_dev19 import order_digest
from run_candidate_learning_dev18 import training_protection,weights
from run_candidate_learning_dev16 import metrics,totals
from relative_learning_dev21 import PARAMETERS,THRESHOLD,MARGIN,MAX_NEGATIVES_PER_CELL,selected_rows,representation,infer as relative_infer
RUN=ROOT/'development/relative_learning_dev21_v1'
MODES=['dev11','learned_only','keep_base_plus_learned','learned_unfiltered']

def infer(model,payload,x,k,positions):
    names=read(ROOT/'development/unit_features_dev20_v1/feature_schema.json')['names']
    return relative_infer(model,payload,x,k,positions,names)

def fit(fold,index):
    path=BASE/fold['train_label_file'];assert sha(path)==fold['train_label_sha256']
    labels=read(path);original=labels['rows'];train=set(fold['train_cases'])
    assert labels['training_cases']==fold['train_cases'] and labels['heldout_cases']==fold['test_cases']
    assert not train & set(fold['test_cases'])
    assert all(r['case'] in train and r['source']!=fold['origin'] for r in original)
    # Candidate labels do not carry cell IDs. Attach the observable cell before
    # deterministic cell-wise negative sampling, using only this fold's rows.
    by_case=defaultdict(dict)
    for r in original:by_case[r['case']][r['id']]=r
    enriched=[]
    for case,ids in by_case.items():
        payload=read(BASE/'features'/(case_path(case)+'.json.gz'))
        for c in payload['candidates']:
            if c['id'] in ids:enriched.append({**ids[c['id']],'cell':c['cell']})
    assert len(enriched)==len(original)
    rows=selected_rows(enriched);del labels,original,enriched,by_case
    width=read(DATA/'feature_schema.json')['base_width'];count=len(rows)
    x=np.empty((2*count,2*width),dtype=np.float32)
    labels=np.asarray([r['label'] for r in rows],dtype=np.int8);y=np.concatenate([labels,1-labels])
    positions=defaultdict(dict)
    for n,r in enumerate(rows):positions[r['case']][r['id']]=n
    for case,ids in positions.items():
        payload,values,k,offsets=case_data(index[case]);found=0
        for n,c in enumerate(payload['candidates']):
            if c['id'] not in ids:continue
            out=ids[c['id']];keep=k[offsets[n]];delta=values[n]-keep
            x[out,:width]=keep;x[out,width:]=delta
            x[out+count,:width]=keep;x[out+count,width:]=-delta;found+=1
        assert found==len(ids)
    w0=weights(rows);w=np.concatenate([w0,w0])
    assert abs(w[y==1].sum()-w[y==0].sum())<1e-5
    model=HistGradientBoostingClassifier(**PARAMETERS);model.fit(x,y,sample_weight=w)
    return model,{'selected_original_rows':count,'mirrored_rows':len(y),'positive':int(y.sum()),'negative':int((y==0).sum()),
                  'features':2*width,'class_weight_sums':[float(w[y==v].sum()) for v in [0,1]],'max_negatives_per_cell':MAX_NEGATIVES_PER_CELL}

def predict():
    if RUN.exists():raise SystemExit('Preserve dev21')
    verify_features();sources=sorted((ROOT/'scripts').glob('*.py'))+sorted((ROOT/'tests').glob('*.py'))
    sources+=[ROOT/'RELATIVE_LEARNING_DEV21_PLAN_20261018.md']
    save(RUN/'source_lock.json',{'files':{str(p.relative_to(ROOT)):sha(p) for p in sources}})
    index={i['case']:i for i in read(BASE/'public_index.json')}
    active,accesses,allowed,reads=training_protection();files={};runtime=[];wall,cpu=time.perf_counter(),time.process_time()
    for fold in read(BASE/'fold_index.json')['folds']:
        t,c=time.perf_counter(),time.process_time()
        allowed[0]=str((BASE/fold['train_label_file']).resolve());model,training=fit(fold,index);allowed[0]=None
        p=RUN/'models'/(fold['id']+'.joblib.gz');p.parent.mkdir(parents=True,exist_ok=True)
        joblib.dump(model,p,compress=('gzip',3));files[str(p.relative_to(RUN))]=sha(p);counts=Counter()
        for case in fold['test_cases']:
            payload,x,k,positions=case_data(index[case]);probs,pred=infer(model,payload,x,k,positions)
            p=RUN/'predictions'/fold['id']/(case_path(case)+'.json.gz');compact(p,{'case':case,'fold':fold['id'],**pred});files[str(p.relative_to(RUN))]=sha(p)
            p=RUN/'probabilities'/fold['id']/(case_path(case)+'.npz');p.parent.mkdir(parents=True,exist_ok=True)
            np.savez_compressed(p,probabilities=probs,order_digest=np.asarray(order_digest(payload['candidates'])))
            files[str(p.relative_to(RUN))]=sha(p);counts.update({m:len(pred[m]) for m in MODES})
        runtime.append({'fold':fold['id'],**training,'suggestions':dict(counts),
                        'wall_seconds':time.perf_counter()-t,'cpu_seconds':time.process_time()-c})
        print('trained relative',fold['id'],training,dict(counts),flush=True)
        del model;gc.collect()
    active[0]=False
    save(RUN/'runtime.json',{'folds':runtime,'wall_seconds':time.perf_counter()-wall,'cpu_seconds':time.process_time()-cpu,
         'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'parameters':PARAMETERS,'threshold':THRESHOLD,
         'margin':MARGIN,'gpu_used':False,'python':platform.python_version(),
         'packages':{'numpy':np.__version__,'sklearn':sklearn.__version__,'joblib':joblib.__version__},
         'thread_environment':{k:os.getenv(k) for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS']},
         'scope':'relative preference experiment fits/inference; feature extraction and paper pipeline excluded'})
    files['runtime.json']=sha(RUN/'runtime.json')
    save(RUN/'prediction_lock.json',{'files':files,'source_lock_sha256':sha(RUN/'source_lock.json'),
         'feature_lock_sha256':sha(DATA/'feature_lock.json'),'base_prediction_lock_sha256':sha(ROOT/'development/unit_learning_dev20_v1/prediction_lock.json'),
         'training_labels_read':sorted(reads),'heldout_labels_read':[],'accesses':sorted(accesses),'final_validation_eligible':False})
    print('DEV21 PREDICTIONS LOCKED',flush=True)

def verify():
    verify_features();lock=read(RUN/'prediction_lock.json')
    assert sha(RUN/'source_lock.json')==lock['source_lock_sha256']
    for rel,v in read(RUN/'source_lock.json')['files'].items():assert sha(ROOT/rel)==v,rel
    for rel,v in lock['files'].items():assert sha(RUN/rel)==v,rel
    assert sha(DATA/'feature_lock.json')==lock['feature_lock_sha256']
    assert sha(ROOT/'development/unit_learning_dev20_v1/prediction_lock.json')==lock['base_prediction_lock_sha256']
    assert lock['heldout_labels_read']==[]

def score():
    verify();assert not (RUN/'score.json').exists()
    for rel,v in read(BASE/'label_preparation_lock.json')['files'].items():assert sha(BASE/rel)==v,rel
    truth=read(BASE/'heldout_truth.json.gz');cases=[]
    control=read(ROOT/'development/unit_learning_dev20_v1/score.json')
    for fold in read(BASE/'fold_index.json')['folds']:
        for case in fold['test_cases']:
            t=truth['cases'][case];labels=read(BASE/'case_labels'/(case_path(case)+'.json.gz'))
            pred=read(RUN/'predictions'/fold['id']/(case_path(case)+'.json.gz'))
            row={'case':case,**{k:t[k] for k in ['origin_group','family','group','scenario']}}
            for m in MODES:row[m]=metrics(pred[m],case,{'cases':{case:t},'candidate_labels':{case:labels}})
            cases.append(row)
    assert len(cases)==213
    report={'cases':cases,'all':{m:totals(cases,m) for m in MODES},'control_dev20_all':control['all'],
         'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),'candidate_pool_unchanged':True,
         'candidate_pool_correct_error_ceiling':control['candidate_pool_correct_error_ceiling'],
         'final_validation_eligible':False,'main_candidate_adopted':False,'accepted_final_sources':0,'accepted_final_families':0}
    for key in ['origin_group','family','group','scenario']:
        report[key]={str(v):{m:totals([r for r in cases if r[key]==v],m) for m in MODES} for v in sorted({r[key] for r in cases},key=str)}
    save(RUN/'score.json',report);print(report['all'],flush=True)
    for s,r in report['origin_group'].items():print(s,r,flush=True)

def replay():
    verify();active,accesses=protection();index={i['case']:i for i in read(BASE/'public_index.json')};count=0
    for fold in read(BASE/'fold_index.json')['folds']:
        model=joblib.load(RUN/'models'/(fold['id']+'.joblib.gz'))
        for case in fold['test_cases']:
            payload,x,k,positions=case_data(index[case]);probs,pred=infer(model,payload,x,k,positions)
            old=read(RUN/'predictions'/fold['id']/(case_path(case)+'.json.gz'))
            for k,v in pred.items():assert v==old[k],(case,k)
            with np.load(RUN/'probabilities'/fold['id']/(case_path(case)+'.npz'),allow_pickle=False) as data:
                assert np.array_equal(probs,data['probabilities'])
                assert str(data['order_digest'])==order_digest(payload['candidates'])
            count+=1
        print('replayed relative',fold['id'],flush=True)
    active[0]=False
    p=ROOT/'qa/RELATIVE_LEARNING_DEV21_REPLAY_20261018.json';assert not p.exists()
    save(p,{'cases':count,'all_probabilities_and_suggestions_identical':True,'labels_read':[],
            'accesses':sorted(accesses),'prediction_lock_sha256':sha(RUN/'prediction_lock.json')})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['predict','score','verify','replay']);a=p.parse_args()
    {'predict':predict,'score':score,'verify':verify,'replay':replay}[a.mode]()
