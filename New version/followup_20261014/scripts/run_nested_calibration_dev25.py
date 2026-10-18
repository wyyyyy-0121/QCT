"""Genuine three-origin inner models, then isolated outer repair calibration."""
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
from build_candidates_dev18 import compact
from build_keep_features_dev21 import BASE,DATA as FEATURES,case_data,case_path
from build_signed_features_dev19 import order_digest
from run_certified_learning_dev22 import verify_features
from run_absolute_selection_dev24 import protect_preflight,protect_training
from run_candidate_learning_dev18 import weights
from run_candidate_learning_dev16 import metrics,totals
from certified_preferences_dev22 import certified_pairs
from certified_matrix_dev22 import build_matrix
from relative_learning_dev21 import preference,PARAMETERS,THRESHOLD,MARGIN
from nested_calibration_dev25 import top_rows,fit_calibrator,select,validate_folds
from prepare_absolute_labels_dev24 import digest
from prepare_nested_calibration_dev25 import DATA as LABELS,UPSTREAM
RUN=ROOT/'development/nested_calibration_dev25_v1'
INNER=RUN/'inner';OUTER=RUN/'outer'
MODES=['dev11','calibrated_only','keep_base_plus_calibrated','raw_only','keep_base_plus_raw']


def verify_preparation(include_label_bodies=False):
    lock=read(LABELS/'preparation_lock.json')
    names=lock['files'] if include_label_bodies else ['fold_index.json']
    for rel in names:assert sha(LABELS/rel)==lock['files'][rel],rel
    assert sha(LABELS/'source_lock.json')==lock['source_lock_sha256']
    for rel,value in read(LABELS/'source_lock.json')['files'].items():assert sha(ROOT/rel)==value,rel
    for path,key in [(FEATURES/'feature_lock.json','feature_lock_sha256'),(BASE/'fold_index.json','upstream_fold_index_sha256'),
            (BASE/'label_preparation_lock.json','repair_label_lock_sha256'),(UPSTREAM/'prediction_lock.json','upstream_model_lock_sha256'),
            (ROOT/'qa/ABSOLUTE_SELECTION_DEV24_VERIFICATION_20261018.json','upstream_checkpoint_sha256'),
            (ROOT/'development/absolute_selection_dev24_data_v1/preparation_lock.json','upstream_options_lock_sha256')]:
        assert sha(path)==lock[key],key
    fold_index=read(LABELS/'fold_index.json');validate_folds(fold_index)
    for f in fold_index['outer']:assert sha(ROOT/f['outer_model_file'])==f['outer_model_sha256']


def protection():
    active,accesses,allowed,reads=protect_training()
    def guard(event,args):
        if active[0] and event=='open' and isinstance(args[0],(str,bytes)):
            name=os.fsdecode(args[0])
            # No old outer predictions/scores may accidentally substitute for
            # genuinely nested scores or affect calibration.
            if str(UPSTREAM) in name and any('/'+part in name for part in ['predictions/','probabilities/','score.json']):
                raise PermissionError('Old outer predictions/answers forbidden in dev25 learner')
    sys.addaudithook(guard)
    for path in [UPSTREAM/'score.json',UPSTREAM/'predictions/test.json',UPSTREAM/'probabilities/test.npz']:
        try:path.read_bytes()
        except PermissionError:pass
        else:raise AssertionError('old outer guard')
    return active,accesses,allowed,reads


def freeze_sources(folder):
    sources=sorted((ROOT/'scripts').glob('*.py'))+sorted((ROOT/'tests').glob('*.py'))
    sources+=[ROOT/'NESTED_CALIBRATION_DEV25_PREREGISTRATION_20261018.md']
    save(folder/'source_lock.json',dict(files={str(p.relative_to(ROOT)):sha(p) for p in sources}))


def fit_inner(fold,index):
    path=LABELS/fold['train_label_file'];assert sha(path)==fold['train_label_sha256']
    labels=read(path);states=labels['alternatives']
    assert labels['training_cases']==fold['train_cases'] and labels['heldout_cases']==fold['test_cases']
    assert not set(fold['train_cases'])&set(fold['test_cases'])
    assert all(r['case'] in fold['train_cases'] and r['source'] not in fold['excluded_origins'] for r in states)
    rows,_=certified_pairs(states);meta={r['case']:{k:r[k] for k in ['source','family']} for r in states}
    rows=[dict(r,**meta[r['case']]) for r in rows];del states,labels,meta
    y=np.asarray([r['label'] for r in rows],dtype=np.int8);w=weights(rows)
    assert np.array_equal(y[::2],np.ones(len(y)//2)) and np.array_equal(y[1::2],np.zeros(len(y)//2))
    assert np.array_equal(w[::2],w[1::2])
    sums={s:float(w[[n for n,r in enumerate(rows) if r['source']==s]].sum()) for s in sorted({r['source'] for r in rows})}
    assert max(sums.values())-min(sums.values())<1e-5
    width=read(FEATURES/'feature_schema.json')['base_width']
    summary=dict(rows=len(rows),positive=int(y.sum()),negative=int((y==0).sum()),features=2*width,
        source_weight_sums=sums,class_weight_sums=[float(w[y==v].sum()) for v in [0,1]],
        selection_sha256=digest(rows,['case','cell','left_id','right_id','label']))
    (ROOT/'tmp').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='dev25_',dir=ROOT/'tmp') as tmp:
        print('building nested',fold['id'],len(rows),flush=True)
        x,matrix_sha=build_matrix(Path(tmp)/'training.npy',rows,width,index,case_data)
        del rows;gc.collect();print('fitting nested',fold['id'],x.shape,x.nbytes,flush=True)
        model=HistGradientBoostingClassifier(**PARAMETERS);model.fit(x,y,sample_weight=w);del x
    return model,dict(summary,training_matrix_sha256=matrix_sha)


def case_predictions(model,item):
    payload,x,k,positions=case_data(item);scores=preference(model,x,k[positions])
    units=read(ROOT/'development/unit_features_dev20_v1/feature_schema.json')['names']
    return payload,scores,top_rows(payload,scores,x,units)


def environment(wall,cpu,**more):
    return dict(wall_seconds=time.perf_counter()-wall,cpu_seconds=time.process_time()-cpu,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,gpu_used=False,python=platform.python_version(),
        packages={'numpy':np.__version__,'sklearn':sklearn.__version__,'joblib':joblib.__version__},
        thread_environment={k:os.getenv(k) for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS']},**more)


def inner():
    if INNER.exists():raise SystemExit('Preserve dev25 inner run')
    preflight=protect_preflight();verify_features();verify_preparation();freeze_sources(INNER)
    index={r['case']:r for r in read(BASE/'public_index.json')};folds=read(LABELS/'fold_index.json')['pairs']
    preflight[0]=False;active,accesses,allowed,reads=protection()
    files={};runtimes=[];wall,cpu=time.perf_counter(),time.process_time()
    for fold in folds:
        t,c=time.perf_counter(),time.process_time();allowed[0]=str((LABELS/fold['train_label_file']).resolve())
        model,summary=fit_inner(fold,index);allowed[0]=None
        path=INNER/'models'/(fold['id']+'.joblib.gz');path.parent.mkdir(parents=True,exist_ok=True)
        joblib.dump(model,path,compress=('gzip',3));files[str(path.relative_to(INNER))]=sha(path)
        for case in fold['test_cases']:
            payload,scores,top=case_predictions(model,index[case])
            p=INNER/'probabilities'/fold['id']/(case_path(case)+'.npz');p.parent.mkdir(parents=True,exist_ok=True)
            np.savez_compressed(p,probabilities=scores,order_digest=np.asarray(order_digest(payload['candidates'])))
            files[str(p.relative_to(INNER))]=sha(p)
            p=INNER/'top'/fold['id']/(case_path(case)+'.json.gz')
            compact(p,dict(case=case,rows=top));files[str(p.relative_to(INNER))]=sha(p)
        runtimes.append(dict(pair=fold['id'],excluded_origins=fold['excluded_origins'],**summary,
            prediction_cases=len(fold['test_cases']),wall_seconds=time.perf_counter()-t,cpu_seconds=time.process_time()-c))
        print('nested trained',fold['id'],summary,flush=True);del model;gc.collect()
    active[0]=False
    save(INNER/'runtime.json',environment(wall,cpu,folds=runtimes,parameters=PARAMETERS,scope='10 nested three-origin fits and 852 heldout case predictions'))
    files['runtime.json']=sha(INNER/'runtime.json')
    save(INNER/'prediction_lock.json',dict(files=files,source_lock_sha256=sha(INNER/'source_lock.json'),
        preparation_lock_sha256=sha(LABELS/'preparation_lock.json'),training_labels_read=sorted(reads),
        heldout_labels_read=[],old_outer_predictions_read=[],accesses=sorted(accesses),final_validation_eligible=False))
    print('DEV25 ALL INNER PREDICTIONS LOCKED',flush=True)


def verify_inner():
    verify_features();verify_preparation();lock=read(INNER/'prediction_lock.json')
    assert sha(INNER/'source_lock.json')==lock['source_lock_sha256']
    for rel,value in read(INNER/'source_lock.json')['files'].items():assert sha(ROOT/rel)==value,rel
    for rel,value in lock['files'].items():assert sha(INNER/rel)==value,rel
    assert sha(LABELS/'preparation_lock.json')==lock['preparation_lock_sha256']
    assert lock['heldout_labels_read']==lock['old_outer_predictions_read']==[]
    expected=sorted(str((LABELS/f['train_label_file']).resolve()) for f in read(LABELS/'fold_index.json')['pairs'])
    assert lock['training_labels_read']==expected


def calibration_rows(fold,fold_index):
    path=ROOT/fold['calibration_label_file'];assert sha(path)==fold['calibration_label_sha256']
    labels=read(path)
    assert labels['training_cases']==fold['train_cases'] and labels['heldout_cases']==fold['test_cases']
    assert all(r['case'] in fold['train_cases'] and r['source']!=fold['origin'] for r in labels['rows'])
    by_id={r['id']:r for r in labels['rows']};assert len(by_id)==len(labels['rows'])
    pairs={p['id']:p for p in fold_index['pairs']};rows=[];counts=Counter();seen=[]
    for pair_id in fold['inner_pairs']:
        pair=pairs[pair_id];assert fold['origin'] in pair['excluded_origins']
        other=next(o for o in pair['excluded_origins'] if o!=fold['origin'])
        for case in pair['test_cases']:
            meta=fold_index['case_groups'][case]
            if meta['origin_group']!=other:continue
            assert case in fold['train_cases'] and case not in pair['train_cases'];seen.append(case)
            top=read(INNER/'top'/pair_id/(case_path(case)+'.json.gz'))
            assert top['case']==case
            for r in top['rows']:
                counts['top_candidates']+=1
                if r['gate_reason'] is not None:counts[r['gate_reason']]+=1;continue
                label=by_id.get(r['candidate_id'])
                if label is None:counts['unknown_excluded']+=1;continue
                assert label['case']==case and label['source']==other and label['label'] in (0,1)
                rows.append(dict(r,case=case,label=label['label'],source=label['source'],family=label['family']))
                counts['known']+=1
    assert len(seen)==len(set(seen)) and set(seen)==set(fold['train_cases'])
    del labels,by_id
    return rows,dict(counts)


def infer_outer(model,calibrator,item):
    payload,scores,top=case_predictions(model,item);selected,diagnostics=select(top,calibrator)
    raw=[dict(cell=r['cell'],suggested_formula=r['suggested_formula'],probability=r['raw_probability'],
        runner_up_probability=r['raw_runner_up_probability'],candidate_id=r['candidate_id'],status='propose')
        for r in top if r['gate_reason'] is None and r['raw_probability']>=THRESHOLD]
    old={r['cell'] for r in payload['baseline']}
    pred=dict(dev11=payload['baseline'],calibrated_only=selected,raw_only=raw,
        keep_base_plus_calibrated=payload['baseline']+[r for r in selected if r['cell'] not in old],
        keep_base_plus_raw=payload['baseline']+[r for r in raw if r['cell'] not in old])
    return payload,scores,pred,diagnostics


def outer():
    if OUTER.exists():raise SystemExit('Preserve dev25 outer run')
    preflight=protect_preflight();verify_inner();freeze_sources(OUTER)
    index={r['case']:r for r in read(BASE/'public_index.json')};fold_index=read(LABELS/'fold_index.json')
    preflight[0]=False;active,accesses,allowed,reads=protection()
    files={};runtime=[];wall,cpu=time.perf_counter(),time.process_time()
    for fold in fold_index['outer']:
        t,c=time.perf_counter(),time.process_time();allowed[0]=str((ROOT/fold['calibration_label_file']).resolve())
        rows,counts=calibration_rows(fold,fold_index);allowed[0]=None
        calibrator,summary=fit_calibrator(rows)
        summary['selection_sha256']=digest(rows,['case','cell','candidate_id','raw_probability','label'])
        del rows;gc.collect()
        p=OUTER/'calibrators'/(fold['id']+'.joblib.gz');p.parent.mkdir(parents=True,exist_ok=True)
        joblib.dump(calibrator,p,compress=('gzip',3));files[str(p.relative_to(OUTER))]=sha(p)
        model=joblib.load(ROOT/fold['outer_model_file']);suggestions=Counter()
        for case in fold['test_cases']:
            payload,scores,pred,top=infer_outer(model,calibrator,index[case])
            p=OUTER/'predictions'/fold['id']/(case_path(case)+'.json.gz')
            compact(p,dict(case=case,fold=fold['id'],**pred));files[str(p.relative_to(OUTER))]=sha(p)
            p=OUTER/'top'/fold['id']/(case_path(case)+'.json.gz')
            compact(p,dict(case=case,rows=top));files[str(p.relative_to(OUTER))]=sha(p)
            p=OUTER/'probabilities'/fold['id']/(case_path(case)+'.npz');p.parent.mkdir(parents=True,exist_ok=True)
            np.savez_compressed(p,probabilities=scores,order_digest=np.asarray(order_digest(payload['candidates'])))
            files[str(p.relative_to(OUTER))]=sha(p);suggestions.update({m:len(pred[m]) for m in MODES})
        runtime.append(dict(fold=fold['id'],counts=counts,**summary,suggestions=dict(suggestions),wall_seconds=time.perf_counter()-t,cpu_seconds=time.process_time()-c))
        print('outer calibrated',fold['id'],summary,dict(suggestions),flush=True);del model,calibrator;gc.collect()
    active[0]=False
    save(OUTER/'runtime.json',environment(wall,cpu,folds=runtime,threshold=THRESHOLD,raw_margin=MARGIN,
        calibration='weighted increasing isotonic, no out-of-support extrapolation',scope='5 calibrators and 213 outer predictions using frozen dev24 rankers'))
    files['runtime.json']=sha(OUTER/'runtime.json')
    save(OUTER/'prediction_lock.json',dict(files=files,source_lock_sha256=sha(OUTER/'source_lock.json'),
        inner_prediction_lock_sha256=sha(INNER/'prediction_lock.json'),preparation_lock_sha256=sha(LABELS/'preparation_lock.json'),
        calibration_labels_read=sorted(reads),heldout_labels_read=[],old_outer_predictions_read=[],accesses=sorted(accesses),final_validation_eligible=False))
    print('DEV25 OUTER PREDICTIONS LOCKED',flush=True)


def verify():
    verify_inner();lock=read(OUTER/'prediction_lock.json')
    for path,key in [(OUTER/'source_lock.json','source_lock_sha256'),(INNER/'prediction_lock.json','inner_prediction_lock_sha256'),(LABELS/'preparation_lock.json','preparation_lock_sha256')]:assert sha(path)==lock[key]
    for rel,value in read(OUTER/'source_lock.json')['files'].items():assert sha(ROOT/rel)==value,rel
    for rel,value in lock['files'].items():assert sha(OUTER/rel)==value,rel
    assert lock['heldout_labels_read']==lock['old_outer_predictions_read']==[]
    expected=sorted(str((ROOT/f['calibration_label_file']).resolve()) for f in read(LABELS/'fold_index.json')['outer'])
    assert lock['calibration_labels_read']==expected


def score():
    verify();assert not (RUN/'score.json').exists()
    for rel,value in read(BASE/'label_preparation_lock.json')['files'].items():assert sha(BASE/rel)==value,rel
    truth=read(BASE/'heldout_truth.json.gz')['cases'];cases=[]
    for fold in read(LABELS/'fold_index.json')['outer']:
        for case in fold['test_cases']:
            t=truth[case];labels=read(BASE/'case_labels'/(case_path(case)+'.json.gz'))
            pred=read(OUTER/'predictions'/fold['id']/(case_path(case)+'.json.gz'))
            control=read(UPSTREAM/'predictions/relative'/fold['id']/(case_path(case)+'.json.gz'))
            assert pred['dev11']==control['dev11'] and pred['raw_only']==control['learned_only']
            assert pred['keep_base_plus_raw']==control['keep_base_plus_learned']
            row={'case':case,**{k:t[k] for k in ['origin_group','family','group','scenario']}}
            for mode in MODES:row[mode]=metrics(pred[mode],case,dict(cases={case:t},candidate_labels={case:labels}))
            cases.append(row)
    assert len(cases)==213
    report=dict(cases=cases,all={m:totals(cases,m) for m in MODES},prediction_lock_sha256=sha(OUTER/'prediction_lock.json'),
        original_dev24_predictions_identical=True,main_candidate_adopted=False,final_validation_eligible=False,accepted_final_sources=0,accepted_final_families=0)
    for key in ['origin_group','family','group','scenario']:
        report[key]={str(v):{m:totals([r for r in cases if r[key]==v],m) for m in MODES} for v in sorted({r[key] for r in cases},key=str)}
    save(RUN/'score.json',report);print('DEV25 SCORED',report['all'],flush=True)


def replay(stage):
    verify_inner() if stage=='inner' else verify()
    active,accesses,allowed,reads=protection();index={r['case']:r for r in read(BASE/'public_index.json')};count=0
    fold_index=read(LABELS/'fold_index.json');folder=INNER if stage=='inner' else OUTER
    for fold in fold_index['pairs' if stage=='inner' else 'outer']:
        model=joblib.load(INNER/'models'/(fold['id']+'.joblib.gz')) if stage=='inner' else joblib.load(ROOT/fold['outer_model_file'])
        calibrator=None if stage=='inner' else joblib.load(OUTER/'calibrators'/(fold['id']+'.joblib.gz'))
        for case in fold['test_cases']:
            if stage=='inner':payload,scores,top=case_predictions(model,index[case])
            else:
                payload,scores,pred,top=infer_outer(model,calibrator,index[case])
                saved=read(OUTER/'predictions'/fold['id']/(case_path(case)+'.json.gz'))
                for key,value in pred.items():assert value==saved[key],(case,key)
            assert top==read(folder/'top'/fold['id']/(case_path(case)+'.json.gz'))['rows']
            with np.load(folder/'probabilities'/fold['id']/(case_path(case)+'.npz'),allow_pickle=False) as p:
                assert np.array_equal(scores,p['probabilities']) and str(p['order_digest'])==order_digest(payload['candidates'])
            count+=1
        print('replayed dev25',stage,fold['id'],flush=True)
    active[0]=False;assert not reads
    p=ROOT/('qa/NESTED_CALIBRATION_DEV25_'+stage.upper()+'_REPLAY_20261018.json');assert not p.exists()
    save(p,dict(cases=count,all_probabilities_top_and_suggestions_identical=True,labels_read=[],accesses=sorted(accesses),prediction_lock_sha256=sha(folder/'prediction_lock.json')))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['inner','outer','verify','score','replay_inner','replay_outer'])
    actions=dict(inner=inner,outer=outer,verify=verify,score=score,replay_inner=lambda:replay('inner'),replay_outer=lambda:replay('outer'))
    actions[parser.parse_args().mode]()
