"""Post-score diagnostics only: never changes the locked learner or predictions."""
from collections import Counter,defaultdict
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_candidate_learning_dev18 import verify,DATA,RUN
from candidate_features_dev16 import THRESHOLD,MARGIN
from run_selector_dev5 import read,save,sha

def main():
    verify();assert (RUN/'score.json').exists()
    truth=read(DATA/'heldout_truth.json.gz')['cases'];by_source=defaultdict(Counter);details=[];false=[]
    for fold in read(DATA/'fold_index.json')['folds']:
        for case in fold['test_cases']:
            t=truth[case];errors=set(t['errors']);labels=read(DATA/'case_labels'/(case.replace('/','__')+'.json.gz'))
            payload=read(DATA/'features'/(case.replace('/','__')+'.json.gz'))
            pred=read(RUN/'predictions'/fold['id']/(case.replace('/','__')+'.json.gz'))
            groups=defaultdict(list)
            for c in payload['candidates']:
                groups[c['cell']].append({**c,'probability':pred['candidate_probabilities'][c['id']]})
            selected={r['cell']:r for r in pred['learned_only']}
            for cell in sorted(errors):
                rows=groups[cell];correct=[r for r in rows if labels[r['id']]==1]
                eligible=[r for r in correct if r['eligible']]
                ranked=sorted([r for r in rows if r['eligible']],key=lambda r:(-r['probability'],r['formula']))
                result=selected.get(cell);success=bool(result and labels[result['candidate_id']]==1)
                if success:reason='correct_selected'
                elif not correct:reason='correct_candidate_missing'
                elif not eligible:reason='correct_candidate_ineligible'
                elif max(r['probability'] for r in eligible)<THRESHOLD:reason='correct_probability_below_threshold'
                elif ranked and labels[ranked[0]['id']]!=1:reason='incorrect_candidate_ranked_first'
                elif len(ranked)>1 and ranked[0]['probability']-ranked[1]['probability']<MARGIN:reason='ambiguous_top_margin'
                else:reason='other_rejection'
                by_source[t['origin_group']][reason]+=1
                if t['group'] in ['public_relations','lcoe']:
                    details.append({'case':case,'origin':t['origin_group'],'scenario':t['scenario'],'cell':cell,
                         'reason':reason,'candidate_count':len(rows),'correct_candidates':len(correct),
                         'eligible_correct_candidates':len(eligible),
                         'best_correct_probability':max((r['probability'] for r in eligible),default=None),
                         'top_candidates':[{k:r[k] for k in ['formula','probability','origins']}|{'label':labels[r['id']]} for r in ranked[:2]]})
            for r in pred['learned_only']:
                if labels[r['candidate_id']]==0:
                    false.append({'case':case,'origin':t['origin_group'],'scenario':t['scenario'],'cell':r['cell'],
                         'observed':t['observed_formulas'][r['cell']],'expected':t['expected_formulas'][r['cell']],
                         'proposed':r['suggested_formula'],'probability':r['probability'],
                         'was_correct_before':r['cell'] not in errors})
    path=ROOT/'qa/CANDIDATE_LEARNING_DEV18_DIAGNOSIS_20261018.json';assert not path.exists()
    save(path,{'by_origin':{s:dict(v) for s,v in by_source.items()},'public_error_details':details,
         'false_suggestions':false,'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),
         'post_hoc_labels_read':True,'predictions_unchanged':True,'final_validation_eligible':False})
    print({s:dict(v) for s,v in by_source.items()},flush=True)

if __name__=='__main__':main()
