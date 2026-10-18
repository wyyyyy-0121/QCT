"""After-lock error accounting; diagnostics do not change selection parameters."""
from collections import Counter,defaultdict
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from run_absolute_selection_dev24 import RUN,BASE,LABELS,ARMS,verify,case_path,case_data,THRESHOLD,MARGIN,KEEP_MARGIN
from build_candidates_dev16 import uid


def main():
    verify();assert (RUN/'score.json').exists()
    truth=read(BASE/'heldout_truth.json.gz')['cases'];index={r['case']:r for r in read(BASE/'public_index.json')}
    units=read(ROOT/'development/unit_features_dev20_v1/feature_schema.json')['names']
    all_counts={a:Counter() for a in ARMS};sources={a:defaultdict(Counter) for a in ARMS}
    details=[];certificate=ROOT/'development/tristate_states_dev23_v1'
    relation_counts={a:Counter() for a in ARMS}
    for fold in read(LABELS/'fold_index.json')['folds']:
        for case in fold['test_cases']:
            t=truth[case];labels=read(BASE/'case_labels'/(case_path(case)+'.json.gz'))
            payload,x,k,positions=case_data(index[case]);grouped=defaultdict(list)
            for n,c in enumerate(payload['candidates']):grouped[c['cell']].append((n,c))
            states=read(certificate/'author_case_states'/(case_path(case)+'.json.gz'))['alternatives']
            state_index={(r['cell'],r['id']):r['label'] for r in states}
            for arm in ARMS:
                pred=read(RUN/'predictions'/arm/fold['id']/(case_path(case)+'.json.gz'))
                base={r['cell']:r for r in pred['dev11']};learned={r['cell']:r for r in pred['learned_only']}
                with np.load(RUN/'probabilities'/arm/fold['id']/(case_path(case)+'.npz'),allow_pickle=False) as p:
                    scores=p['probabilities'];keep=p['keep_probabilities']
                for row in learned.values():
                    cell=row['cell'];scope='outside' if cell not in t['expected_formulas'] else ('error' if cell in t['errors'] else 'clean')
                    relation_counts[arm][scope+'_candidate_'+str(state_index[cell,row['candidate_id']])]+=1
                    relation_counts[arm][scope+'_keep_'+str(state_index[cell,'__observed_formula__'])]+=1
                for cell in sorted(t['errors']):
                    def correct(row):return row is not None and labels[uid(case,cell,row['suggested_formula'])]==1
                    candidates=grouped.get(cell,[])
                    eligible=sorted([(n,c) for n,c in candidates if c['eligible']],key=lambda pair:(-scores[pair[0]],pair[1]['formula']))
                    if correct(base.get(cell)):reason='dev11_correct'
                    elif cell in base:reason='dev11_output_wrong'
                    elif correct(learned.get(cell)):reason='learned_additional_correct'
                    elif cell in learned:reason='learned_output_wrong_or_unknown'
                    elif not any(labels[c['id']]==1 for n,c in candidates):reason='no_accepted_candidate'
                    elif not any(labels[c['id']]==1 for n,c in eligible):reason='accepted_candidates_ineligible'
                    else:
                        n,c=eligible[0];p=float(scores[n]);runner=float(scores[eligible[1][0]]) if len(eligible)>1 else 0.
                        if labels[c['id']]!=1:reason='top_candidate_wrong_or_unknown'
                        elif p<THRESHOLD:reason='top_correct_below_threshold'
                        elif p-runner<MARGIN:reason='top_correct_candidate_margin'
                        elif arm=='absolute' and p-float(keep[positions[n]])<KEEP_MARGIN:reason='top_correct_keep_margin'
                        elif x[n,-len(units)+units.index('unit_new_incompatible')]:reason='top_correct_unit_gate'
                        else:raise AssertionError(('unexplained abstention',arm,case,cell,p))
                    all_counts[arm][reason]+=1;sources[arm][t['origin_group']][reason]+=1
                    if not reason.endswith('_correct'):details.append(dict(arm=arm,case=case,cell=cell,reason=reason))
    for arm in ARMS:assert sum(all_counts[arm].values())==sum(len(t['errors']) for t in truth.values())==18073
    target=ROOT/'qa/ABSOLUTE_SELECTION_DEV24_DIAGNOSTICS_20261018.json';assert not target.exists()
    save(target,dict(all={a:dict(c) for a,c in all_counts.items()},by_source={a:{s:dict(c) for s,c in v.items()} for a,v in sources.items()},
        author_relation_diagnostics={a:dict(c) for a,c in relation_counts.items()},misses=details,
        prediction_lock_sha256=sha(RUN/'prediction_lock.json'),diagnostic_source_sha256=sha(Path(__file__)),parameters_changed=False,final_validation_eligible=False))
    print('DEV24 DIAGNOSTICS',all_counts,flush=True)


if __name__=='__main__':main()
