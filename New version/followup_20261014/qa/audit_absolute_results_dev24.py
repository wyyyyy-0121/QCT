"""Independent integer recount, all strata and every non-correct suggestion."""
from collections import Counter,defaultdict
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from run_absolute_selection_dev24 import RUN,BASE,LABELS,ARMS,MODES,verify,case_path
from build_candidates_dev16 import uid


def main():
    verify();truth=read(BASE/'heldout_truth.json.gz')['cases'];score=read(RUN/'score.json')
    checks=0;failures=[];comparison={}
    keys=['suggestions','correct','correct_errors','wrong','wrong_clean_cells','unknown','errors']
    for arm in ARMS:
        cases={r['case']:r for r in score['arms'][arm]['cases']}
        aggregate={m:Counter() for m in MODES}
        strata={key:defaultdict(lambda:{m:Counter() for m in MODES}) for key in ['origin_group','family','group','scenario']}
        additions=[];clean_changes=0
        for fold in read(LABELS/'fold_index.json')['folds']:
            for case in fold['test_cases']:
                t=truth[case];errors=set(t['errors']);expected=t['expected_formulas']
                labels=read(BASE/'case_labels'/(case_path(case)+'.json.gz'))
                pred=read(RUN/'predictions'/arm/fold['id']/(case_path(case)+'.json.gz'))
                base_cells={r['cell'] for r in pred['dev11']}
                for row in pred['learned_only']:
                    if row['cell'] not in base_cells:
                        additions.append(dict(case=case,**row,label=labels[uid(case,row['cell'],row['suggested_formula'])]))
                for mode in MODES:
                    rows=pred[mode];assert len(rows)==len({r['cell'] for r in rows})
                    counts=Counter(suggestions=len(rows),errors=len(errors))
                    for row in rows:
                        cell=row['cell'];y=labels[uid(case,cell,row['suggested_formula'])]
                        if cell not in expected:outcome='unknown';counts['unknown']+=1
                        elif y==1 and cell in errors:
                            outcome='correct';counts['correct']+=1;counts['correct_errors']+=1
                        else:
                            outcome='wrong';counts['wrong']+=1;counts['wrong_clean_cells']+=cell not in errors
                        if outcome!='correct':failures.append(dict(arm=arm,case=case,mode=mode,outcome=outcome,**row))
                    for key in keys:
                        assert counts[key]==cases[case][mode][key],(arm,case,mode,key)
                        aggregate[mode][key]+=counts[key];checks+=1
                        for group,values in strata.items():values[str(t[group])][mode][key]+=counts[key]
                    assert counts['suggestions']==counts['correct']+counts['wrong']+counts['unknown']
                    assert (counts['correct']/counts['suggestions'] if counts['suggestions'] else None)==cases[case][mode]['precision_confirmed_lower_bound']
                    assert (counts['correct_errors']/counts['errors'] if counts['errors'] else None)==cases[case][mode]['coverage']
        report=score['arms'][arm]
        for mode in MODES:
            for key,value in aggregate[mode].items():assert value==report['all'][mode][key]
        for group,values in strata.items():
            for value,modes in values.items():
                for mode,counts in modes.items():
                    for key,n in counts.items():assert n==report[group][value][mode][key]
        comparison[arm]=dict(new_suggestions_beyond_dev11=additions,counts={m:dict(c) for m,c in aggregate.items()})
    target=ROOT/'qa/ABSOLUTE_SELECTION_DEV24_INDEPENDENT_COUNTS_20261018.json';assert not target.exists()
    save(target,dict(integer_count_checks=checks,all_counts_and_strata_identical=True,all_zero_suggestion_NA_verified=True,
        arms=comparison,all_wrong_and_unknown_suggestions=failures,auditor_sha256=sha(Path(__file__)),
        prediction_lock_sha256=sha(RUN/'prediction_lock.json'),score_sha256=sha(RUN/'score.json'),final_validation_eligible=False))
    print('DEV24 INDEPENDENT COUNT CHECKS',checks,flush=True)


if __name__=='__main__':main()
