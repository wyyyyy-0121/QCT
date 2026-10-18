"""Train blocked folds on their allowed labels; lock before separate overall scoring."""
from pathlib import Path
from collections import defaultdict
import argparse
import hashlib
import os
import platform
import resource
import sys
import time
import joblib
import numpy as np
import scipy
import sklearn
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from run_selector_dev8 import guard_prediction
from build_candidates_dev16 import DATA,uid
from candidate_features_dev16 import VERSION,PARAMETERS,THRESHOLD,MARGIN
from train_candidate_dev16 import fit,infer
RUN=ROOT/'development/candidate_learning_dev16_v1'
MODES=['dev11','learned_only','keep_base_plus_learned']

def verify_features():
    lock=read(DATA/'feature_lock.json')
    for rel,v in lock['files'].items():assert sha(DATA/rel)==v,rel
    for rel,v in lock['inputs'].items():assert sha(ROOT/rel)==v,rel
    for rel,v in lock['sources'].items():assert sha(ROOT/rel)==v,rel
    assert lock['labels_read']==[]
    return lock

def protection():
    accesses,active=set(),[True];allowed=[None];train_reads=set()
    guard_prediction(accesses,active)
    def guard(event,args):
        if active[0] and event=='open' and isinstance(args[0],(str,bytes)):
            name=args[0].decode() if isinstance(args[0],bytes) else args[0]
            if 'prepare_candidate_learning_dev16' in name or '/heldout_truth' in name:
                raise PermissionError('Training/inference cannot read heldout oracle')
            if '/training_labels/' in name:
                path=str(Path(name).resolve())
                if path!=allowed[0]:raise PermissionError('Wrong fold training labels')
                train_reads.add(path)
    sys.addaudithook(guard)
    for forbidden in [DATA/'heldout_truth.json.gz',DATA/'training_labels/family__0.json.gz',
                      ROOT/'scripts/prepare_candidate_learning_dev16.py']:
        try:forbidden.read_bytes()
        except PermissionError:pass
        else:raise AssertionError('Oracle isolation guard failed')
    return active,allowed,accesses,train_reads

def dataset():
    index=read(DATA/'public_index.json');payloads={};features={}
    for item in index:
        payload=read(DATA/'features'/(item['case'].replace('/','__')+'.json.gz'))
        payloads[item['case']]=payload
        for row in payload['candidates']:
            assert row['id'] not in features
            features[row['id']]={**row,'case':item['case']}
    return payloads,features

def train_predict():
    if RUN.exists():raise SystemExit('Preserve run; use a new version')
    verify_features()
    sources=sorted((ROOT/'scripts').glob('*.py'))+sorted((ROOT/'tests').glob('*.py'))
    sources+=[ROOT/'CANDIDATE_LEARNING_DEV16_PLAN_20261018.md']
    save(RUN/'source_lock.json',{'version':VERSION,'files':{str(p.relative_to(ROOT)):sha(p) for p in sources}})
    folds=read(DATA/'fold_index.json')['folds']; save(RUN/'fold_index.json',read(DATA/'fold_index.json'))
    active,allowed,accesses,train_reads=protection()
    payloads,features=dataset();files={};runtime=[];wall,cpu=time.perf_counter(),time.process_time()
    for fold in folds:
        allowed[0]=str((DATA/fold['train_label_file']).resolve())
        assert sha(DATA/fold['train_label_file'])==fold['train_label_sha256']
        labels=read(DATA/fold['train_label_file'])
        assert labels['training_cases']==fold['train_cases']
        train_cases=set(fold['train_cases']);test_cases=set(fold['test_cases'])
        assert not train_cases&test_cases
        for r in labels['rows']:
            assert r['case'] in train_cases and r['case'] not in test_cases
            assert features[r['id']]['case']==r['case'] and r['label'] in [0,1]
        t,c=time.perf_counter(),time.process_time()
        learner,training=fit(features,labels['rows'])
        model_path=RUN/'models'/(fold['id']+'.joblib.gz');model_path.parent.mkdir(parents=True,exist_ok=True)
        joblib.dump(learner,model_path,compress=('gzip',3))
        files[str(model_path.relative_to(RUN))]=sha(model_path)
        counts={name:0 for name in MODES}
        for case in fold['test_cases']:
            pred={'case':case,'fold':fold['id'],'dev11':payloads[case]['baseline'],**infer(learner,payloads[case])}
            path=RUN/'predictions'/fold['id']/(case.replace('/','__')+'.json.gz')
            save(path,pred);files[str(path.relative_to(RUN))]=sha(path)
            for mode in MODES:counts[mode]+=len(pred[mode])
        runtime.append({'fold':fold['id'],'scheme':fold['scheme'],**training,
                        'train_cases':len(train_cases),'test_cases':len(test_cases),
                        'training_label_sha256':fold['train_label_sha256'],
                        'wall_seconds':time.perf_counter()-t,'cpu_seconds':time.process_time()-c,
                        'suggestions':counts})
        allowed[0]=None
        print(fold['id'],'train',training['rows'],'heldout',len(test_cases),'suggestions',counts,flush=True)
    active[0]=False
    save(RUN/'runtime.json',{'folds':runtime,'wall_seconds':time.perf_counter()-wall,'cpu_seconds':time.process_time()-cpu,
        'process_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'gpu_used':False,'python':platform.python_version(),'platform':platform.platform(),
        'packages':{'numpy':np.__version__,'scipy':scipy.__version__,'sklearn':sklearn.__version__,'joblib':joblib.__version__},
        'thread_environment':{k:os.environ.get(k) for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']},
        'parameters':PARAMETERS,'threshold':THRESHOLD,'margin':MARGIN,
        'scope':'training and inference from frozen feature/candidate pool; feature extraction and original SG/FG costs excluded'})
    for name in ['runtime.json','fold_index.json']:files[name]=sha(RUN/name)
    save(RUN/'prediction_lock.json',{'source_lock_sha256':sha(RUN/'source_lock.json'),'files':files,
         'feature_lock_sha256':sha(DATA/'feature_lock.json'),
         'label_preparation_lock_sha256':sha(DATA/'label_preparation_lock.json'),
         'fold_index_sha256':sha(DATA/'fold_index.json'),
         'training_labels_read':sorted(train_reads),'heldout_labels_read':[],
         'oracle_guard_exercised':True,'accesses':sorted(accesses),'final_validation_eligible':False})
    print('DEV16 PREDICTIONS AND MODELS LOCKED',flush=True)

def verify(include_label_bodies=False):
    verify_features();lock=read(RUN/'prediction_lock.json')
    assert sha(RUN/'source_lock.json')==lock['source_lock_sha256']
    for rel,v in read(RUN/'source_lock.json')['files'].items():assert sha(ROOT/rel)==v,rel
    for rel,v in lock['files'].items():assert sha(RUN/rel)==v,rel
    assert sha(DATA/'feature_lock.json')==lock['feature_lock_sha256']
    assert sha(DATA/'label_preparation_lock.json')==lock['label_preparation_lock_sha256']
    assert sha(DATA/'fold_index.json')==lock['fold_index_sha256']
    if include_label_bodies:
        for rel,v in read(DATA/'label_preparation_lock.json')['files'].items():
            assert sha(DATA/rel)==v
    assert lock['heldout_labels_read']==[] and not lock['final_validation_eligible']

def metrics(rows,case,truth):
    errors=set(truth['cases'][case]['errors']);expected=truth['cases'][case]['expected_formulas']
    labels=truth['candidate_labels'][case]
    assert len(rows)==len({r['cell'] for r in rows})
    correct=set();wrong=unknown=unnecessary=0
    for r in rows:
        cell=r['cell'];y=labels.get(uid(case,cell,r['suggested_formula']))
        assert cell not in expected or y is not None
        if cell not in expected:unknown+=1
        elif y==1 and cell in errors:correct.add(cell)
        else:wrong+=1;unnecessary+=cell not in errors
    result={'suggestions':len(rows),'correct':len(correct),'wrong':wrong,'unknown':unknown,
            'errors':len(errors),'correct_errors':len(correct),'wrong_clean_cells':unnecessary}
    result['precision_confirmed_lower_bound']=len(correct)/len(rows) if rows else None
    result['coverage']=len(correct)/len(errors) if errors else None
    assert len(rows)==len(correct)+wrong+unknown
    return result

def totals(rows,name):
    keys=['suggestions','correct','wrong','unknown','errors','correct_errors','wrong_clean_cells']
    m={k:sum(r[name][k] for r in rows) for k in keys}
    m['precision_confirmed_lower_bound']=m['correct']/m['suggestions'] if m['suggestions'] else None
    m['coverage']=m['correct_errors']/m['errors'] if m['errors'] else None
    return m

def score():
    verify(include_label_bodies=True)
    path=RUN/'score.json'
    if path.exists():raise SystemExit('Preserve score')
    truth=read(DATA/'heldout_truth.json.gz');payloads,features=dataset();schemes={}
    for fold in read(RUN/'fold_index.json')['folds']:
        rows=schemes.setdefault(fold['scheme'],[])
        for case in fold['test_cases']:
            t=truth['cases'][case]
            pred=read(RUN/'predictions'/fold['id']/(case.replace('/','__')+'.json.gz'))
            row={'case':case,'fold':fold['id'],'family':t['family'],'origin_group':t['origin_group'],'group':t['group']}
            for mode in MODES:row[mode]=metrics(pred[mode],case,truth)
            labels=truth['candidate_labels'][case];errors=set(t['errors'])
            for c in payloads[case]['candidates']:
                if labels[c['id']]==1:assert c['cell'] in errors,'unnecessary equivalent edits must not be labelled repair'
            coverable={c['cell'] for c in payloads[case]['candidates']
                       if labels[c['id']]==1 and c['eligible'] and c['cell'] in errors}
            row['candidate_pool_coverable_errors']=len(coverable);rows.append(row)
    report={}
    for scheme,rows in schemes.items():
        assert len(rows)==183 and len({r['case'] for r in rows})==183
        report[scheme]={'cases':rows,'all':{m:totals(rows,m) for m in MODES},
                       'candidate_pool_correct_error_ceiling':sum(r['candidate_pool_coverable_errors'] for r in rows)}
        for key in ['family','origin_group','group','fold']:
            report[scheme][key]={v:{m:totals([r for r in rows if r[key]==v],m) for m in MODES}
                                for v in sorted({r[key] for r in rows})}
    save(path,{'schemes':report,'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),
               'main_candidate_adopted':False,'source_groups':2,'final_validation_eligible':False,
               'accepted_final_sources':0,'accepted_final_families':0,
               'scope':'previously revealed development cross-fitting; all authored sources grouped together for source holdout',
               'unknown_predictions_kept_in_denominator':True,'no_threshold_selection_on_heldout':True})
    print({s:r['all'] for s,r in report.items()},flush=True)

def replay():
    verify();active,allowed,accesses,reads=protection();payloads,features=dataset()
    counts=0;maximum=0.;wall=time.perf_counter()
    for fold in read(RUN/'fold_index.json')['folds']:
        learner=joblib.load(RUN/'models'/(fold['id']+'.joblib.gz'))
        for case in fold['test_cases']:
            got=infer(learner,payloads[case]);old=read(RUN/'predictions'/fold['id']/(case.replace('/','__')+'.json.gz'))
            assert got['learned_only']==old['learned_only']
            assert got['keep_base_plus_learned']==old['keep_base_plus_learned']
            assert got['candidate_probabilities']==old['candidate_probabilities']
            counts+=1
        print('replayed',fold['id'],flush=True)
    active[0]=False;assert not reads
    out=ROOT/'qa/CANDIDATE_LEARNING_DEV16_REPLAY_20261018.json';assert not out.exists()
    save(out,{'case_predictions':counts,'candidate_probabilities_identical':True,
              'all_suggestions_identical':True,'training_labels_read':[],'heldout_labels_read':[],
              'wall_seconds':time.perf_counter()-wall,'accesses':sorted(accesses),
              'scope':'reload locked fitted models and replay inference; training refit not repeated',
              'prediction_lock_sha256':sha(RUN/'prediction_lock.json')})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['predict','score','replay','verify'])
    args=p.parse_args();{'predict':train_predict,'score':score,'replay':replay,'verify':verify}[args.mode]()
