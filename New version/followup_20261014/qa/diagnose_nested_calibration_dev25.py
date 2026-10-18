"""Post-lock full error ledger; no threshold or calibrator search."""
from collections import Counter,defaultdict
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from run_nested_calibration_dev25 import RUN,OUTER,LABELS,BASE,verify,case_path
from build_candidates_dev16 import uid


def main():
    verify();assert (RUN/'score.json').exists();truth=read(BASE/'heldout_truth.json.gz')['cases']
    counts=Counter();sources=defaultdict(Counter);rejections=defaultdict(Counter);failures=[]
    for fold in read(LABELS/'fold_index.json')['outer']:
        for case in fold['test_cases']:
            t=truth[case];labels=read(BASE/'case_labels'/(case_path(case)+'.json.gz'))
            pred=read(OUTER/'predictions'/fold['id']/(case_path(case)+'.json.gz'))
            top=read(OUTER/'top'/fold['id']/(case_path(case)+'.json.gz'))['rows'];tops={r['cell']:r for r in top}
            base={r['cell']:r for r in pred['dev11']};learned={r['cell']:r for r in pred['calibrated_only']}
            for r in top:rejections[t['origin_group']][r['rejection_reason'] or 'selected']+=1
            for cell in t['errors']:
                def correct(row):return row is not None and labels[uid(case,cell,row['suggested_formula'])]==1
                if correct(base.get(cell)):reason='dev11_correct'
                elif cell in base:reason='dev11_wrong'
                elif correct(learned.get(cell)):reason='calibrated_additional_correct'
                elif cell in learned:reason='calibrated_wrong_or_unknown'
                elif cell not in tops:reason='no_eligible_candidate'
                elif labels[tops[cell]['candidate_id']]!=1:reason='top_wrong_or_unknown'
                else:
                    reason=tops[cell]['rejection_reason'];assert reason is not None,(case,cell)
                    reason='top_correct_'+reason
                counts[reason]+=1;sources[t['origin_group']][reason]+=1
                if not reason.endswith('_correct'):failures.append(dict(case=case,cell=cell,reason=reason))
    assert sum(counts.values())==18073
    target=ROOT/'qa/NESTED_CALIBRATION_DEV25_DIAGNOSTICS_20261018.json';assert not target.exists()
    save(target,dict(all=dict(counts),by_source={s:dict(c) for s,c in sources.items()},all_top_rejection_reasons={s:dict(c) for s,c in rejections.items()},
        misses=failures,prediction_lock_sha256=sha(OUTER/'prediction_lock.json'),parameters_changed=False,diagnostic_source_sha256=sha(Path(__file__)),final_validation_eligible=False))
    print('DEV25 diagnostics',counts,flush=True)


if __name__=='__main__':main()
