"""Independent label/count checks plus deterministic source-fold refits."""
from collections import Counter
from pathlib import Path
import argparse
import sys
import time
import joblib
import numpy as np
from openpyxl import load_workbook
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_candidate_learning_dev18 import DATA,RUN,MODES,verify,fit_fold,training_protection
from run_selector_dev5 import read,save,sha
from train_candidate_dev16 import infer
from audit_multisource_dev17 import equals
from build_candidates_dev16 import uid

class SymbolicWorkbook:
    """LCOE oracle treats every referenced cell as an independent symbol."""
    def __getitem__(self,key): return self
    @property
    def value(self): return 1

def recount():
    verify();truth=read(DATA/'heldout_truth.json.gz')['cases'];score=read(RUN/'score.json')
    scored={r['case']:r for r in score['cases']};index={r['case']:r for r in read(DATA/'public_index.json')}
    checks=label_checks=0;wall=time.perf_counter();aggregate={m:Counter() for m in MODES}
    for fold in read(DATA/'fold_index.json')['folds']:
        for case in fold['test_cases']:
            item=index[case];t=truth[case];errors=set(t['errors']);expected=t['expected_formulas']
            labels=read(DATA/'case_labels'/(case.replace('/','__')+'.json.gz'))
            payload=read(DATA/'features'/(case.replace('/','__')+'.json.gz'))
            pred=read(RUN/'predictions'/fold['id']/(case.replace('/','__')+'.json.gz'))
            w=load_workbook(ROOT/item['input']) if item['group']=='public_relations' else SymbolicWorkbook()
            def correct_formula(formula,cell):
                if cell not in expected or cell not in errors:return False
                if item['group'] in ['public_relations','lcoe']:return equals(formula,expected[cell],cell.rsplit('!',1)[0],w)
                return formula==expected[cell]
            # All known candidate labels re-derived without either preparation oracle.
            ceiling=set()
            for c in payload['candidates']:
                y=None if c['cell'] not in expected else int(correct_formula(c['formula'],c['cell']))
                assert y==labels[c['id']],(case,c['cell'],c['formula'],y,labels[c['id']])
                label_checks+=1
                if y==1 and c['eligible']:ceiling.add(c['cell'])
            assert len(ceiling)==scored[case]['candidate_pool_correct_error_ceiling']
            for mode in MODES:
                rows=pred[mode];assert len(rows)==len({r['cell'] for r in rows})
                counts=Counter(suggestions=len(rows),errors=len(errors))
                for r in rows:
                    cell=r['cell']
                    if cell not in expected:counts['unknown']+=1
                    elif correct_formula(r['suggested_formula'],cell):counts['correct']+=1;counts['correct_errors']+=1
                    else:counts['wrong']+=1;counts['wrong_clean_cells']+=cell not in errors
                for k in ['suggestions','errors','correct','correct_errors','unknown','wrong','wrong_clean_cells']:
                    assert counts[k]==scored[case][mode][k],(case,mode,k)
                    aggregate[mode][k]+=counts[k];checks+=1
            if item['group']=='public_relations':w.close()
        print('audited',fold['id'],flush=True)
    for m in MODES:
        for k,v in aggregate[m].items():assert v==score['all'][m][k]
    path=ROOT/'qa/CANDIDATE_LEARNING_DEV18_INDEPENDENT_AUDIT_20261018.json';assert not path.exists()
    save(path,{'case_method_integer_count_checks':checks,'candidate_labels_independently_checked':label_checks,
         'all_candidate_ceilings_checked':True,'all_aggregate_counts_identical':True,
         'wall_seconds':time.perf_counter()-wall,'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),
         'oracle':'separate FormulaGuard AST plus exact SymPy, strict text for legacy authored labels',
         'final_validation_eligible':False})

def refit():
    verify();active,accesses,allowed,reads=training_protection();count=0;wall=time.perf_counter()
    for fold in read(DATA/'fold_index.json')['folds']:
        allowed[0]=str((DATA/fold['train_label_file']).resolve());model,_=fit_fold(fold);allowed[0]=None
        for case in fold['test_cases']:
            payload=read(DATA/'features'/(case.replace('/','__')+'.json.gz'))
            for row in payload['candidates']:row['features']=[float(v) for v in np.asarray(row['features'],dtype=np.float32)]
            old=read(RUN/'predictions'/fold['id']/(case.replace('/','__')+'.json.gz'))
            for k,v in infer(model,payload).items():assert v==old[k],(case,k)
            count+=1
        print('refit',fold['id'],flush=True)
    active[0]=False
    path=ROOT/'qa/CANDIDATE_LEARNING_DEV18_REFIT_20261018.json';assert not path.exists()
    save(path,{'folds':5,'case_predictions':count,'all_probabilities_and_suggestions_identical':True,
         'heldout_labels_read':[],'training_labels_read':sorted(reads),'accesses':sorted(accesses),
         'wall_seconds':time.perf_counter()-wall,'prediction_lock_sha256':sha(RUN/'prediction_lock.json')})

def feature_replay():
    from build_candidates_dev18 import case_features,OLD,protection
    verify();active,accesses=protection();names=read(OLD/'feature_schema.json')['names']
    wall=time.perf_counter();count=candidates=0
    for item in read(DATA/'public_index.json'):
        payload,schema=case_features(item,names)
        assert schema==read(DATA/'feature_schema.json')['names']
        assert payload==read(DATA/'features'/(item['case'].replace('/','__')+'.json.gz')),item['case']
        count+=1;candidates+=len(payload['candidates'])
        print('feature replay',item['case'],flush=True)
    active[0]=False
    path=ROOT/'qa/CANDIDATE_LEARNING_DEV18_FEATURE_REPLAY_20261018.json';assert not path.exists()
    save(path,{'cases':count,'candidates':candidates,'all_features_candidates_and_baselines_identical':True,
         'labels_read':[],'accesses':sorted(accesses),'wall_seconds':time.perf_counter()-wall,
         'feature_lock_sha256':sha(DATA/'feature_lock.json')})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['recount','refit','feature_replay']);a=p.parse_args()
    {'recount':recount,'refit':refit,'feature_replay':feature_replay}[a.mode]()
