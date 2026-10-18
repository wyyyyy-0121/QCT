"""Refit all fixed folds and compare all probabilities, without heldout labels."""
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_candidate_learning_dev16 import RUN,DATA,verify,protection,dataset
from train_candidate_dev16 import fit,infer
from run_selector_dev5 import read,save,sha

def main():
    verify();active,allowed,accesses,reads=protection()
    payloads,features=dataset();wall=time.perf_counter();cpu=time.process_time();details=[]
    for fold in read(RUN/'fold_index.json')['folds']:
        allowed[0]=str((DATA/fold['train_label_file']).resolve())
        labels=read(DATA/fold['train_label_file'])
        assert {r['case'] for r in labels['rows']}<=set(fold['train_cases'])
        model,meta=fit(features,labels['rows'])
        candidates=0
        for case in fold['test_cases']:
            new=infer(model,payloads[case])
            old=read(RUN/'predictions'/fold['id']/(case.replace('/','__')+'.json.gz'))
            assert new['candidate_probabilities']==old['candidate_probabilities']
            assert new['learned_only']==old['learned_only']
            assert new['keep_base_plus_learned']==old['keep_base_plus_learned']
            candidates+=len(new['candidate_probabilities'])
        details.append({'fold':fold['id'],'test_cases':len(fold['test_cases']),'probabilities_compared':candidates,
                        'training_label_sha256':sha(DATA/fold['train_label_file']),'all_identical':True})
        allowed[0]=None;print('refit identical',fold['id'],flush=True)
    active[0]=False
    out=ROOT/'qa/CANDIDATE_LEARNING_DEV16_REFIT_20261018.json';assert not out.exists()
    save(out,{'folds':details,'training_labels_read':sorted(reads),'heldout_labels_read':[],
              'probabilities_and_suggestions_identical':True,'wall_seconds':time.perf_counter()-wall,
              'cpu_seconds':time.process_time()-cpu,'accesses':sorted(accesses),
              'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),'audit_script_sha256':sha(Path(__file__)),
              'final_validation_eligible':False})
if __name__=='__main__':main()
