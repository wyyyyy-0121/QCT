"""Author-only correctness data and explicit source-fold pairing; no prediction."""
from collections import Counter,defaultdict
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from run_relative_learning_dev21 import verify as verify21
from build_keep_features_dev21 import BASE,DATA as FEATURES,case_path
from build_candidates_dev18 import compact
from certified_preferences_dev22 import certified_pairs

DATA=ROOT/'development/certified_preferences_dev22_data_v1'
KEEP='__observed_formula__'


def case_alternatives(payload,t,labels):
    case=payload['case']
    targets=sorted({c['cell'] for c in payload['candidates']})
    expected=t['expected_formulas']; errors=set(t['errors']); alternatives=[]
    for cell in targets:
        # Keep state comes from the certified scope and error ledger, not the
        # presence/absence of positive repair candidates. Out-of-scope is unknown.
        y=None if cell not in expected else int(cell not in errors)
        alternatives.append(dict(id=KEEP,cell=cell,case=case,kind='keep',label=y))
    for c in payload['candidates']:
        assert c['id']!=KEEP
        # On annotated errors, inherit the accepted-repair labels certified in
        # dev18 (legacy authored cases use exact expected formula matching).
        # A zero on a clean cell only means "unnecessary repair", so it cannot
        # certify an incorrect formula. Keep such candidates unknown unless
        # they literally match the certified expected formula.
        if c['cell'] not in expected:y=None
        elif c['cell'] in errors:y=labels[c['id']]
        elif c['formula']==expected[c['cell']]:y=1
        else:y=None
        alternatives.append(dict(id=c['id'],cell=c['cell'],case=case,kind='candidate',label=y))
    return alternatives


def prepare():
    if DATA.exists():raise SystemExit('Preserve dev22 labels')
    verify21();wall=time.perf_counter()
    for rel,v in read(BASE/'label_preparation_lock.json')['files'].items():assert sha(BASE/rel)==v,rel
    truth=read(BASE/'heldout_truth.json.gz')['cases'];files={};summaries=[]
    # This process is allowed to see revealed development truth. The learner
    # will only see prebuilt files for the current training fold.
    for item in read(BASE/'public_index.json'):
        case=item['case'];t=truth[case]
        payload=read(BASE/'features'/(case_path(case)+'.json.gz'))
        labels=read(BASE/'case_labels'/(case_path(case)+'.json.gz'))
        alternatives=case_alternatives(payload,t,labels)
        p=DATA/'author_case_states'/(case_path(case)+'.json.gz')
        compact(p,{'case':case,'alternatives':alternatives});files[str(p.relative_to(DATA))]=sha(p)
        pairs,stats=certified_pairs(alternatives)
        p=DATA/'author_case_pairs'/(case_path(case)+'.json.gz')
        compact(p,{'case':case,'pairs':pairs,'stats':stats});files[str(p.relative_to(DATA))]=sha(p)
        counter=Counter(('unknown' if r['label'] is None else str(r['label']))+'_'+r['kind'] for r in alternatives)
        summaries.append(dict(case=case,source=t['origin_group'],family=t['family'],states=dict(counter),**stats))
        print('prepared certified',case,dict(counter),stats['directed_pairs'],flush=True)
    folds=[]
    for fold in read(BASE/'fold_index.json')['folds']:
        rows=[];states=[]
        for case in fold['train_cases']:
            t=truth[case];assert t['origin_group']!=fold['origin']
            metadata=dict(family=t['family'],source=t['origin_group'])
            rows.extend(dict(r,**metadata) for r in read(DATA/'author_case_pairs'/(case_path(case)+'.json.gz'))['pairs'])
            # Include the full states for independent training-pair verification.
            states.extend(read(DATA/'author_case_states'/(case_path(case)+'.json.gz'))['alternatives'])
        p=DATA/'training_labels'/(fold['id']+'.json.gz')
        compact(p,{'training_cases':fold['train_cases'],'heldout_cases':fold['test_cases'],'rows':rows,'alternatives':states})
        files[str(p.relative_to(DATA))]=sha(p)
        folds.append({**fold,'train_label_file':str(p.relative_to(DATA)),'train_label_sha256':sha(p)})
        print('prepared fold',fold['id'],len(rows),'directed pairs',flush=True)
    for name,value in [('fold_index.json',{'folds':folds}),('state_counts.json',summaries)]:
        save(DATA/name,value);files[name]=sha(DATA/name)
    save(DATA/'preparation_lock.json',{'files':files,'sources':{str(p.relative_to(ROOT)):sha(p) for p in
         [Path(__file__),ROOT/'scripts/certified_preferences_dev22.py',
          ROOT/'CERTIFIED_PREFERENCES_DEV22_PLAN_20261018.md']},
         'upstream_label_lock_sha256':sha(BASE/'label_preparation_lock.json'),
         'upstream_fold_index_sha256':sha(BASE/'fold_index.json'),
         'feature_lock_sha256':sha(FEATURES/'feature_lock.json'),
         'wall_seconds':time.perf_counter()-wall,
         'candidate_state_source':'audited dev18 labels on error cells; clean-cell zero labels are unknown',
         'legacy_authored_acceptance':'exact expected formula, as in the frozen scorer',
         'candidate_correctness_is_not_repair_success':True,'final_validation_eligible':False})
    print('DEV22 CERTIFIED LABELS AND PAIRS LOCKED',flush=True)


if __name__=='__main__':prepare()
