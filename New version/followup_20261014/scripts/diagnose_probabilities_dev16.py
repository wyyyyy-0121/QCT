"""Post-lock probability calibration diagnostic, without changing decisions or thresholds."""
from collections import defaultdict
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from run_candidate_learning_dev16 import RUN,DATA,verify
from run_selector_dev5 import read,save,sha

def main():
    verify(include_label_bodies=True);truth=read(DATA/'heldout_truth.json.gz')
    folds=read(RUN/'fold_index.json')['folds'];groups=defaultdict(list)
    for fold in folds:
        for case in fold['test_cases']:
            pred=read(RUN/'predictions'/fold['id']/(case.replace('/','__')+'.json.gz'))
            payload=read(DATA/'features'/(case.replace('/','__')+'.json.gz'))
            known=[(pred['candidate_probabilities'][c['id']],truth['candidate_labels'][case][c['id']])
                   for c in payload['candidates'] if c['eligible'] and truth['candidate_labels'][case][c['id']] is not None]
            groups[fold['scheme'],truth['cases'][case]['origin_group']].append((case,known))
    result={}
    for (scheme,origin),cases in groups.items():
        pairs=[r for case,rows in cases for r in rows];bins=[]
        for i in range(10):
            selected=[(p,y) for p,y in pairs if min(int(p*10),9)==i]
            bins.append({'lower':i/10,'upper':(i+1)/10,'candidates':len(selected),
                         'mean_probability':sum(p for p,y in selected)/len(selected) if selected else None,
                         'fraction_correct':sum(y for p,y in selected)/len(selected) if selected else None})
        high=[(p,y) for p,y in pairs if p>=.9]
        case_losses=[sum((p-y)**2 for p,y in rows)/len(rows) for case,rows in cases if rows]
        result[scheme+'/'+origin]={'known_eligible_candidates':len(pairs),'reliability_bins':bins,
             'row_pooled_brier':sum((p-y)**2 for p,y in pairs)/len(pairs) if pairs else None,
             'case_mean_brier':sum(case_losses)/len(case_losses) if case_losses else None,
             'probability_at_least_0_9_candidates':len(high),
             'probability_at_least_0_9_actual_fraction_correct':sum(y for p,y in high)/len(high) if high else None}
    out=ROOT/'qa/CANDIDATE_LEARNING_DEV16_CALIBRATION_20261018.json';assert not out.exists()
    save(out,{'groups':result,'predictions_and_threshold_unchanged':True,
              'scope':'post-hoc candidate probability diagnostic, not recalibration or model selection',
              'unknown_candidates_excluded_from_calibration_but_not_repair_precision':True,
              'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),'audit_script_sha256':sha(Path(__file__))})
    for key,r in result.items():print(key,r['probability_at_least_0_9_candidates'],r['probability_at_least_0_9_actual_fraction_correct'])
if __name__=='__main__':main()
