"""Label-free selected-cell/formula comparison; probability scores may change."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_unit_learning_dev20 import RUN,BASE,case_path,verify
from run_signed_learning_dev19 import RUN as CONTROL
from run_selector_dev5 import read,save,sha
from build_candidates_dev18 import protection
verify();active,accesses=protection();rows=[]
def key(suggestions):return sorted((r['cell'],r['suggested_formula'],r['candidate_id']) for r in suggestions)
for fold in read(BASE/'fold_index.json')['folds']:
    for case in fold['test_cases']:
        old=read(CONTROL/'predictions'/fold['id']/(case_path(case)+'.json.gz'))
        new=read(RUN/'predictions'/fold['id']/(case_path(case)+'.json.gz'))
        assert old['dev11']==new['dev11']
        rows.append({'case':case,'same_unfiltered_choices':key(old['learned_only'])==key(new['learned_unfiltered']),
                     'old_choices':len(old['learned_only']),'new_unfiltered':len(new['learned_unfiltered']),
                     'new_filtered':len(new['learned_only'])})
active[0]=False
p=ROOT/'qa/UNIT_LEARNING_DEV20_SELECTION_COMPARISON_20261018.json';assert not p.exists()
save(p,{'cases':rows,'all_unfiltered_choices_identical':all(r['same_unfiltered_choices'] for r in rows),
        'dev11_all_rows_identical':True,'labels_read':[],'accesses':sorted(accesses),
        'source_sha256':sha(Path(__file__)),'prediction_lock_sha256':sha(RUN/'prediction_lock.json')})
print('same unfiltered choices',all(r['same_unfiltered_choices'] for r in rows))
