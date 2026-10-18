"""Recount fixed-label suggestions and rebuild new features independently of training."""
from collections import Counter
from pathlib import Path
import argparse
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_unit_learning_dev20 import RUN,BASE,DATA,MODES,verify,case_path
from build_unit_features_dev20 import matrix,load
from build_candidates_dev18 import protection
from run_selector_dev5 import read,save,sha

def recount():
    verify();truth=read(BASE/'heldout_truth.json.gz')['cases'];scored=read(RUN/'score.json');cases={r['case']:r for r in scored['cases']}
    count=0;aggregate={m:Counter() for m in MODES}
    for fold in read(BASE/'fold_index.json')['folds']:
        for case in fold['test_cases']:
            labels=read(BASE/'case_labels'/(case_path(case)+'.json.gz'));t=truth[case];errors=set(t['errors'])
            pred=read(RUN/'predictions'/fold['id']/(case_path(case)+'.json.gz'))
            for mode in MODES:
                rows=pred[mode];assert len(rows)==len({r['cell'] for r in rows});c=Counter(suggestions=len(rows),errors=len(errors))
                for r in rows:
                    from build_candidates_dev16 import uid
                    y=labels[uid(case,r['cell'],r['suggested_formula'])]
                    if y is None:c['unknown']+=1
                    elif y==1 and r['cell'] in errors:c['correct']+=1;c['correct_errors']+=1
                    else:c['wrong']+=1;c['wrong_clean_cells']+=r['cell'] not in errors
                for k in ['suggestions','correct','correct_errors','wrong','wrong_clean_cells','unknown','errors']:
                    assert c[k]==cases[case][mode][k],(case,mode,k);aggregate[mode][k]+=c[k];count+=1
    for m in MODES:
        for k,v in aggregate[m].items():assert v==scored['all'][m][k]
    p=ROOT/'qa/UNIT_LEARNING_DEV20_INDEPENDENT_COUNTS_20261018.json';assert not p.exists()
    save(p,{'integer_count_checks':count,'all_counts_identical':True,'fixed_candidate_labels_already_independently_verified_in_dev18':True,
         'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),'final_validation_eligible':False})

def feature_replay():
    verify();active,accesses=protection();count=0
    schema=read(DATA/'feature_schema.json')['names']
    for item in read(BASE/'public_index.json'):
        x,names,digest=matrix(item,schema)
        payload=read(BASE/'features'/(case_path(item['case'])+'.json.gz'))
        assert np.array_equal(x,load(item,payload))
        count+=1;print('units feature replay',item['case'],flush=True)
    active[0]=False
    p=ROOT/'qa/UNIT_LEARNING_DEV20_FEATURE_REPLAY_20261018.json';assert not p.exists()
    save(p,{'cases':count,'all_unit_features_identical':True,'labels_read':[],'accesses':sorted(accesses),
         'feature_lock_sha256':sha(DATA/'feature_lock.json')})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['recount','feature_replay']);a=p.parse_args()
    {'recount':recount,'feature_replay':feature_replay}[a.mode]()
