"""Post-score miss attribution; reads labels only after frozen dev20 scoring."""
from collections import Counter,defaultdict
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_unit_learning_dev20 import BASE,RUN,DATA,verify,case_path
from build_unit_features_dev20 import load
from candidate_features_dev16 import THRESHOLD,MARGIN
from run_selector_dev5 import read,save,sha

def main():
    verify();assert (RUN/'score.json').exists()
    truth=read(BASE/'heldout_truth.json.gz')['cases'];index={r['case']:r for r in read(BASE/'public_index.json')}
    grouped=defaultdict(Counter);details=[];sample_count=Counter()
    for fold in read(BASE/'fold_index.json')['folds']:
        for case in fold['test_cases']:
            t=truth[case];labels=read(BASE/'case_labels'/(case_path(case)+'.json.gz'))
            payload=read(BASE/'features'/(case_path(case)+'.json.gz'))
            pred=read(RUN/'predictions'/fold['id']/(case_path(case)+'.json.gz'))
            with np.load(RUN/'probabilities'/fold['id']/(case_path(case)+'.npz'),allow_pickle=False) as data:probs=data['probabilities']
            pool=defaultdict(list)
            for c,p in zip(payload['candidates'],probs):pool[c['cell']].append((c,float(p)))
            selected={r['cell']:r for r in pred['keep_base_plus_learned']}
            for cell in t['errors']:
                rows=pool[cell];eligible=sorted([(c,p) for c,p in rows if c['eligible']],key=lambda r:(-r[1],r[0]['formula']))
                good=[(c,p) for c,p in eligible if labels[c['id']]==1];out=selected.get(cell)
                if out and labels.get(out.get('candidate_id'))==1:reason='correct_learned_selected'
                elif out and out in pred['dev11']:reason='base_selected'
                elif not any(labels[c['id']]==1 for c,p in rows):reason='correct_candidate_missing'
                elif not good:reason='correct_candidate_ineligible'
                elif eligible and labels[eligible[0][0]['id']]!=1:reason='wrong_ranked_first'
                elif eligible[0][1]<THRESHOLD:reason='correct_first_below_threshold'
                elif len(eligible)>1 and eligible[0][1]-eligible[1][1]<MARGIN:
                    reason='margin_between_correct' if labels[eligible[1][0]['id']]==1 else 'margin_against_wrong_or_unknown'
                else:reason='other_rejection'
                grouped[t['origin_group']][reason]+=1
                group=(t['origin_group'],reason)
                if t['origin_group']!='authored_development' or sample_count[group]<4:
                    details.append({'case':case,'origin':t['origin_group'],'scenario':t['scenario'],'cell':cell,'reason':reason,
                                    'observed':t['observed_formulas'][cell], 'expected':t['expected_formulas'][cell],
                                    'correct_candidates':len(good),'top':[{ 'formula':c['formula'],'p':p,'label':labels[c['id']]} for c,p in eligible[:3]],
                                    'best_correct_p':max((p for c,p in good),default=None)})
                    sample_count[group]+=1
    p=ROOT/'qa/UNIT_LEARNING_DEV20_MISS_DIAGNOSIS_20261018.json';assert not p.exists()
    save(p,{'by_origin':dict(grouped),'details':details,'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),
            'audit_source_sha256':sha(Path(__file__)),'posthoc_labels_read':True,'final_validation_eligible':False})
    print(dict(grouped))
if __name__=='__main__':main()
