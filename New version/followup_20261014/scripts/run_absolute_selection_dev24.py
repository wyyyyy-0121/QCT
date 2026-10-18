"""Two locked source-heldout experiments; scoring and replay run separately."""
from collections import Counter
from pathlib import Path
import argparse
import gc
import os
import platform
import resource
import sys
import tempfile
import time
import joblib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from build_candidates_dev18 import compact,protection
from build_keep_features_dev21 import BASE,DATA as FEATURES,case_data,case_path
from build_signed_features_dev19 import order_digest
from run_certified_learning_dev22 import verify_features,protect_preflight as inherited_preflight
from run_candidate_learning_dev18 import training_protection,weights
from run_candidate_learning_dev16 import metrics,totals
from absolute_selection_dev24 import options,infer as absolute_infer,KEEP_MARGIN,PARAMETERS,THRESHOLD,MARGIN
from certified_preferences_dev22 import certified_pairs
from absolute_matrix_dev24 import build_matrix as absolute_matrix
from certified_matrix_dev22 import build_matrix as relative_matrix
from relative_learning_dev21 import infer as relative_infer
from prepare_absolute_labels_dev24 import DATA as LABELS,digest
RUN=ROOT/'development/absolute_selection_dev24_v1'
ARMS=['absolute','relative']
MODES=['dev11','learned_only','keep_base_plus_learned','learned_unfiltered']


def protect_preflight():
    active=inherited_preflight()
    def guard(event,args):
        if active[0] and event=='open' and isinstance(args[0],(str,bytes)) and '/author_case_options/' in os.fsdecode(args[0]):
            raise PermissionError('No author option bodies in preflight')
    sys.addaudithook(guard)
    return active


def verify_preparation(include_label_bodies=False):
    lock=read(LABELS/'preparation_lock.json')
    for rel in (lock['files'] if include_label_bodies else ['fold_index.json','state_counts.json']):
        assert sha(LABELS/rel)==lock['files'][rel],rel
    assert sha(LABELS/'source_lock.json')==lock['source_lock_sha256']
    for rel,value in read(LABELS/'source_lock.json')['files'].items(): assert sha(ROOT/rel)==value,rel
    assert sha(FEATURES/'feature_lock.json')==lock['feature_lock_sha256']
    assert sha(BASE/'fold_index.json')==lock['upstream_fold_index_sha256']
    assert sha(ROOT/'development/tristate_states_dev23_v1/preparation_lock.json')==lock['upstream_state_lock_sha256']
    assert sha(ROOT/'qa/TRISTATE_RELATIONS_DEV23_VERIFICATION_20261018.json')==lock['independent_certificate_verification_sha256']


def protect_training():
    active,accesses,allowed,reads=training_protection()
    def guard(event,args):
        if active[0] and event=='open' and isinstance(args[0],(str,bytes)):
            name=os.fsdecode(args[0])
            if any(part in name for part in ['/author_case_states/','/author_case_pairs/','/author_case_options/']):
                raise PermissionError('Author-only states/options forbidden in learner')
    sys.addaudithook(guard)
    for name in ['author_case_states','author_case_pairs','author_case_options']:
        try:(LABELS/name/'test.json.gz').read_bytes()
        except PermissionError:pass
        else:raise AssertionError('author guard')
    return active,accesses,allowed,reads


def fit(fold,index,arm):
    path=LABELS/fold['train_label_file'];assert sha(path)==fold['train_label_sha256']
    labels=read(path);states=labels['alternatives']
    assert labels['training_cases']==fold['train_cases'] and labels['heldout_cases']==fold['test_cases']
    assert not set(fold['train_cases'])&set(fold['test_cases'])
    assert all(r['case'] in fold['train_cases'] and r['source']!=fold['origin'] for r in states)
    if arm=='absolute':
        rows=options(states);matrix_builder=absolute_matrix;fields=['case','cell','id','kind','label'];width_factor=1
    else:
        rows,_=certified_pairs(states)
        metadata={r['case']:{k:r[k] for k in ['source','family']} for r in states}
        rows=[dict(r,**metadata[r['case']]) for r in rows]
        matrix_builder=relative_matrix;fields=['case','cell','left_id','right_id','label'];width_factor=2
    del states,labels
    y=np.asarray([r['label'] for r in rows],dtype=np.int8);w=weights(rows)
    if arm=='relative':
        assert np.array_equal(y[::2],np.ones(len(y)//2)) and np.array_equal(y[1::2],np.zeros(len(y)//2))
        assert np.array_equal(w[::2],w[1::2])
    source_sums={source:float(w[[n for n,r in enumerate(rows) if r['source']==source]].sum()) for source in sorted({r['source'] for r in rows})}
    assert max(source_sums.values())-min(source_sums.values())<1e-5
    width=read(FEATURES/'feature_schema.json')['base_width']
    summary=dict(arm=arm,rows=len(rows),positive=int(y.sum()),negative=int((y==0).sum()),
        source_weight_sums=source_sums,class_weight_sums=[float(w[y==v].sum()) for v in [0,1]],
        selection_sha256=digest(rows,fields),features=width_factor*width)
    (ROOT/'tmp').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='dev24_'+arm+'_',dir=ROOT/'tmp') as tmp:
        print('building dev24',fold['id'],arm,len(rows),flush=True)
        matrix,matrix_sha=matrix_builder(Path(tmp)/'training.npy',rows,width,index,case_data)
        del rows;gc.collect()
        print('fitting dev24',fold['id'],arm,matrix.shape,matrix.nbytes,flush=True)
        model=HistGradientBoostingClassifier(**PARAMETERS);model.fit(matrix,y,sample_weight=w)
        del matrix
    return model,dict(summary,training_matrix_sha256=matrix_sha,storage='float64 mmap from frozen float32 features')


def infer(arm,model,payload,x,k,positions):
    names=read(ROOT/'development/unit_features_dev20_v1/feature_schema.json')['names']
    if arm=='absolute':return absolute_infer(model,payload,x,k,positions,names)
    scores,pred=relative_infer(model,payload,x,k,positions,names)
    return scores,np.empty(0,dtype=np.float64),pred


def predict():
    if RUN.exists():raise SystemExit('Preserve dev24')
    preflight=protect_preflight()
    verify_features();verify_preparation()
    sources=sorted((ROOT/'scripts').glob('*.py'))+sorted((ROOT/'tests').glob('*.py'))
    sources+=[ROOT/'ABSOLUTE_SELECTION_DEV24_PREREGISTRATION_20261018.md']
    save(RUN/'source_lock.json',dict(files={str(p.relative_to(ROOT)):sha(p) for p in sources}))
    index={item['case']:item for item in read(BASE/'public_index.json')}
    folds=read(LABELS/'fold_index.json')['folds'];preflight[0]=False
    active,accesses,allowed,reads=protect_training();files={};runtime=[];wall,cpu=time.perf_counter(),time.process_time()
    for fold in folds:
        for arm in ARMS:
            t,c=time.perf_counter(),time.process_time();allowed[0]=str((LABELS/fold['train_label_file']).resolve())
            model,summary=fit(fold,index,arm);allowed[0]=None
            p=RUN/'models'/arm/(fold['id']+'.joblib.gz');p.parent.mkdir(parents=True,exist_ok=True)
            joblib.dump(model,p,compress=('gzip',3));files[str(p.relative_to(RUN))]=sha(p);counts=Counter()
            for case in fold['test_cases']:
                payload,x,k,positions=case_data(index[case]);scores,keep,pred=infer(arm,model,payload,x,k,positions)
                p=RUN/'predictions'/arm/fold['id']/(case_path(case)+'.json.gz')
                compact(p,dict(case=case,fold=fold['id'],arm=arm,**pred));files[str(p.relative_to(RUN))]=sha(p)
                p=RUN/'probabilities'/arm/fold['id']/(case_path(case)+'.npz');p.parent.mkdir(parents=True,exist_ok=True)
                np.savez_compressed(p,probabilities=scores,keep_probabilities=keep,order_digest=np.asarray(order_digest(payload['candidates'])))
                files[str(p.relative_to(RUN))]=sha(p);counts.update({m:len(pred[m]) for m in MODES})
            runtime.append(dict(fold=fold['id'],**summary,suggestions=dict(counts),wall_seconds=time.perf_counter()-t,cpu_seconds=time.process_time()-c))
            print('trained dev24',fold['id'],arm,summary,dict(counts),flush=True)
            del model;gc.collect()
    active[0]=False
    save(RUN/'runtime.json',dict(folds=runtime,wall_seconds=time.perf_counter()-wall,cpu_seconds=time.process_time()-cpu,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,parameters=PARAMETERS,threshold=THRESHOLD,margin=MARGIN,
        keep_margin=KEEP_MARGIN,gpu_used=False,python=platform.python_version(),packages={'numpy':np.__version__,'sklearn':sklearn.__version__,'joblib':joblib.__version__},
        thread_environment={k:os.getenv(k) for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS']},scope='10 fits and full heldout inference; features/certification excluded'))
    files['runtime.json']=sha(RUN/'runtime.json')
    save(RUN/'prediction_lock.json',dict(files=files,source_lock_sha256=sha(RUN/'source_lock.json'),
        feature_lock_sha256=sha(FEATURES/'feature_lock.json'),preparation_lock_sha256=sha(LABELS/'preparation_lock.json'),
        fold_index_sha256=sha(LABELS/'fold_index.json'),training_labels_read=sorted(reads),heldout_labels_read=[],author_states_read=[],
        accesses=sorted(accesses),oracle_guard_exercised=True,final_validation_eligible=False))
    print('DEV24 ALL PREDICTIONS LOCKED',flush=True)


def verify():
    verify_features();verify_preparation();lock=read(RUN/'prediction_lock.json')
    assert sha(RUN/'source_lock.json')==lock['source_lock_sha256']
    for rel,value in read(RUN/'source_lock.json')['files'].items():assert sha(ROOT/rel)==value,rel
    for rel,value in lock['files'].items():assert sha(RUN/rel)==value,rel
    assert sha(FEATURES/'feature_lock.json')==lock['feature_lock_sha256']
    for name in ['preparation_lock','fold_index']:assert sha(LABELS/(name+'.json'))==lock[name+'_sha256']
    assert lock['heldout_labels_read']==lock['author_states_read']==[]
    expected=sorted(str((LABELS/f['train_label_file']).resolve()) for f in read(LABELS/'fold_index.json')['folds'])
    assert lock['training_labels_read']==expected


def score():
    verify();assert not (RUN/'score.json').exists()
    for rel,value in read(BASE/'label_preparation_lock.json')['files'].items():assert sha(BASE/rel)==value,rel
    truth=read(BASE/'heldout_truth.json.gz')['cases'];reports={}
    for arm in ARMS:
        cases=[]
        for fold in read(LABELS/'fold_index.json')['folds']:
            for case in fold['test_cases']:
                t=truth[case];labels=read(BASE/'case_labels'/(case_path(case)+'.json.gz'))
                pred=read(RUN/'predictions'/arm/fold['id']/(case_path(case)+'.json.gz'))
                row={'case':case,**{k:t[k] for k in ['origin_group','family','group','scenario']}}
                for mode in MODES:row[mode]=metrics(pred[mode],case,dict(cases={case:t},candidate_labels={case:labels}))
                cases.append(row)
        assert len(cases)==213
        report=dict(cases=cases,all={m:totals(cases,m) for m in MODES})
        for key in ['origin_group','family','group','scenario']:
            report[key]={str(v):{m:totals([r for r in cases if r[key]==v],m) for m in MODES} for v in sorted({r[key] for r in cases},key=str)}
        reports[arm]=report;print(arm,report['all'],flush=True)
    save(RUN/'score.json',dict(arms=reports,prediction_lock_sha256=sha(RUN/'prediction_lock.json'),
        control_dev20_all=read(ROOT/'development/unit_learning_dev20_v1/score.json')['all'],
        candidate_pool_unchanged=True,final_validation_eligible=False,main_candidate_adopted=False,accepted_final_sources=0,accepted_final_families=0))


def replay():
    verify();active,accesses=protection();index={i['case']:i for i in read(BASE/'public_index.json')};counts=Counter()
    for fold in read(LABELS/'fold_index.json')['folds']:
        for arm in ARMS:
            model=joblib.load(RUN/'models'/arm/(fold['id']+'.joblib.gz'))
            for case in fold['test_cases']:
                payload,x,k,positions=case_data(index[case]);scores,keep,pred=infer(arm,model,payload,x,k,positions)
                old=read(RUN/'predictions'/arm/fold['id']/(case_path(case)+'.json.gz'))
                for key,value in pred.items():assert value==old[key],(arm,case,key)
                with np.load(RUN/'probabilities'/arm/fold['id']/(case_path(case)+'.npz'),allow_pickle=False) as data:
                    assert np.array_equal(scores,data['probabilities']) and np.array_equal(keep,data['keep_probabilities'])
                    assert str(data['order_digest'])==order_digest(payload['candidates'])
                counts[arm]+=1
            print('replayed dev24',fold['id'],arm,flush=True)
    active[0]=False
    p=ROOT/'qa/ABSOLUTE_SELECTION_DEV24_REPLAY_20261018.json';assert not p.exists()
    save(p,dict(cases_by_arm=dict(counts),all_probabilities_and_suggestions_identical=True,labels_read=[],
        accesses=sorted(accesses),prediction_lock_sha256=sha(RUN/'prediction_lock.json')))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['predict','verify','score','replay'])
    {'predict':predict,'verify':verify,'score':score,'replay':replay}[parser.parse_args().mode]()
