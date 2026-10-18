"""Independent cell-level outcome counts and calibration versus raw additions."""
from collections import Counter,defaultdict
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from run_nested_calibration_dev25 import RUN,OUTER,LABELS,BASE,MODES,verify,case_path
from build_candidates_dev16 import uid


def main():
    verify();truth=read(BASE/'heldout_truth.json.gz')['cases'];score=read(RUN/'score.json')
    cases={r['case']:r for r in score['cases']};aggregate={m:Counter() for m in MODES}
    strata={k:defaultdict(lambda:{m:Counter() for m in MODES}) for k in ['origin_group','family','group','scenario']}
    checks=0;failures=[];calibrated=set();raw=set();outcomes={}
    for fold in read(LABELS/'fold_index.json')['outer']:
        for case in fold['test_cases']:
            t=truth[case];errors=set(t['errors']);expected=t['expected_formulas']
            labels=read(BASE/'case_labels'/(case_path(case)+'.json.gz'))
            pred=read(OUTER/'predictions'/fold['id']/(case_path(case)+'.json.gz'))
            for mode in MODES:
                rows=pred[mode];assert len(rows)==len({r['cell'] for r in rows})
                counts=Counter(suggestions=len(rows),errors=len(errors))
                for r in rows:
                    cell=r['cell'];y=labels[uid(case,cell,r['suggested_formula'])]
                    if cell not in expected:outcome='unknown';counts['unknown']+=1
                    elif y==1 and cell in errors:outcome='correct';counts['correct']+=1;counts['correct_errors']+=1
                    else:outcome='wrong';counts['wrong']+=1;counts['wrong_clean_cells']+=cell not in errors
                    key=(case,cell,r['suggested_formula']);outcomes[key]=outcome
                    if mode=='calibrated_only':calibrated.add(key)
                    if mode=='raw_only':raw.add(key)
                    if outcome!='correct':failures.append(dict(case=case,mode=mode,outcome=outcome,**r))
                for key in ['suggestions','correct','correct_errors','wrong','wrong_clean_cells','unknown','errors']:
                    assert counts[key]==cases[case][mode][key],(case,mode,key);checks+=1;aggregate[mode][key]+=counts[key]
                    for group,values in strata.items():values[str(t[group])][mode][key]+=counts[key]
                assert (counts['correct']/counts['suggestions'] if counts['suggestions'] else None)==cases[case][mode]['precision_confirmed_lower_bound']
                assert (counts['correct_errors']/counts['errors'] if counts['errors'] else None)==cases[case][mode]['coverage']
                assert counts['suggestions']==counts['correct']+counts['wrong']+counts['unknown']
    for mode,counts in aggregate.items():
        for key,value in counts.items():assert value==score['all'][mode][key]
    for group,values in strata.items():
        for value,modes in values.items():
            for mode,counts in modes.items():
                for key,n in counts.items():assert n==score[group][value][mode][key]
    changes={}
    for name,items in [('shared',calibrated&raw),('added',calibrated-raw),('removed',raw-calibrated)]:
        changes[name]=dict(count=len(items),outcomes=dict(Counter(outcomes[k] for k in items)),
            suggestions=[dict(case=c,cell=cell,formula=f,outcome=outcomes[c,cell,f]) for c,cell,f in sorted(items)])
    target=ROOT/'qa/NESTED_CALIBRATION_DEV25_INDEPENDENT_COUNTS_20261018.json';assert not target.exists()
    save(target,dict(integer_count_checks=checks,all_counts_strata_ratios_and_NA_identical=True,
        changes_vs_raw=changes,all_wrong_and_unknown_suggestions=failures,prediction_lock_sha256=sha(OUTER/'prediction_lock.json'),
        score_sha256=sha(RUN/'score.json'),auditor_sha256=sha(Path(__file__)),final_validation_eligible=False))
    print('DEV25 independent counts',checks,{k:{x:y for x,y in v.items() if x!='suggestions'} for k,v in changes.items()},flush=True)


if __name__=='__main__':main()
