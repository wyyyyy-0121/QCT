"""Apply unit rejection to frozen dev19 suggestions without retraining or labels."""
from pathlib import Path
from collections import Counter
import argparse
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from build_unit_features_dev20 import BASE,DATA,load
from run_unit_learning_dev20 import unit_filter,case_path,verify_features
from run_signed_learning_dev19 import RUN as CONTROL
from build_candidates_dev18 import protection,compact
from run_selector_dev5 import read,save,sha
from run_candidate_learning_dev16 import metrics,totals
RUN=ROOT/'development/unit_gate_dev20_v1'
MODES=['dev19_original','dev19_unit_filtered']

def predict():
    if RUN.exists():raise SystemExit('Preserve diagnostic')
    verify_features();active,accesses=protection();files={};index={r['case']:r for r in read(BASE/'public_index.json')}
    names=read(DATA/'feature_schema.json')['names'];counts=Counter()
    for fold in read(BASE/'fold_index.json')['folds']:
        for case in fold['test_cases']:
            payload=read(BASE/'features'/(case_path(case)+'.json.gz'));x=load(index[case],payload)
            old=read(CONTROL/'predictions'/fold['id']/(case_path(case)+'.json.gz'))['learned_only']
            filtered=unit_filter(old,payload['candidates'],x,names)
            path=RUN/'predictions'/(case_path(case)+'.json.gz')
            compact(path,{'case':case,'dev19_original':old,'dev19_unit_filtered':filtered})
            files[str(path.relative_to(RUN))]=sha(path)
            counts.update(before=len(old),after=len(filtered),rejected=len(old)-len(filtered))
    active[0]=False
    save(RUN/'prediction_lock.json',{'files':files,'feature_lock_sha256':sha(DATA/'feature_lock.json'),
         'control_prediction_lock_sha256':sha(CONTROL/'prediction_lock.json'),
         'source_sha256':sha(Path(__file__)),'gate_source_sha256':sha(ROOT/'scripts/run_unit_learning_dev20.py'),
         'labels_read':[],'accesses':sorted(accesses),'counts':dict(counts),'final_validation_eligible':False})
    print(dict(counts),flush=True)

def verify():
    verify_features();lock=read(RUN/'prediction_lock.json')
    for rel,v in lock['files'].items():assert sha(RUN/rel)==v
    assert sha(DATA/'feature_lock.json')==lock['feature_lock_sha256']
    assert sha(CONTROL/'prediction_lock.json')==lock['control_prediction_lock_sha256']
    assert sha(Path(__file__))==lock['source_sha256']
    assert sha(ROOT/'scripts/run_unit_learning_dev20.py')==lock['gate_source_sha256']
    assert not lock['labels_read']

def score():
    verify();assert not (RUN/'score.json').exists();truth=read(BASE/'heldout_truth.json.gz');cases=[]
    for item in read(BASE/'public_index.json'):
        case=item['case'];t=truth['cases'][case];labels=read(BASE/'case_labels'/(case_path(case)+'.json.gz'))
        pred=read(RUN/'predictions'/(case_path(case)+'.json.gz'))
        row={'case':case,'origin_group':t['origin_group']}
        for m in MODES:row[m]=metrics(pred[m],case,{'cases':{case:t},'candidate_labels':{case:labels}})
        cases.append(row)
    report={'cases':cases,'all':{m:totals(cases,m) for m in MODES},
            'origin_group':{s:{m:totals([r for r in cases if r['origin_group']==s],m) for m in MODES}
                            for s in sorted({r['origin_group'] for r in cases})},
            'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),'unchanged_frozen_labels':True,'final_validation_eligible':False}
    save(RUN/'score.json',report);print(report['all'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['predict','verify','score']);a=p.parse_args()
    {'predict':predict,'verify':verify,'score':score}[a.mode]()
