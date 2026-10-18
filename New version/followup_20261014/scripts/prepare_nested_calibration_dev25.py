"""Author preparation of disjoint three-origin folds; no new truth inferred."""
from itertools import combinations
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from build_candidates_dev18 import compact
from build_keep_features_dev21 import BASE,DATA as FEATURES,case_path
from prepare_absolute_labels_dev24 import DATA as OPTIONS
DATA=ROOT/'development/nested_calibration_dev25_data_v1'
UPSTREAM=ROOT/'development/absolute_selection_dev24_v1'


def prepare():
    if DATA.exists():raise SystemExit('Preserve dev25 supervision')
    from run_absolute_selection_dev24 import verify
    verify()
    checkpoint=ROOT/'qa/ABSOLUTE_SELECTION_DEV24_VERIFICATION_20261018.json'
    assert read(checkpoint)['all_checks_passed']
    option_lock=read(OPTIONS/'preparation_lock.json')
    for rel,value in option_lock['files'].items():assert sha(OPTIONS/rel)==value,rel
    old=read(BASE/'fold_index.json');origins=sorted(f['origin'] for f in old['folds'])
    groups=old['case_groups'];cases=[r['case'] for r in read(BASE/'public_index.json')]
    files={};pairs=[];outer=[];wall=time.perf_counter()
    for n,(a,b) in enumerate(combinations(origins,2),1):
        train=[c for c in cases if groups[c]['origin_group'] not in (a,b)]
        test=[c for c in cases if c not in set(train)]
        rows=[]
        for case in train:
            rel='author_case_options/'+case_path(case)+'.json.gz'
            assert sha(OPTIONS/rel)==option_lock['files'][rel]
            rows.extend(read(OPTIONS/rel)['alternatives'])
        name='pair_'+str(n).zfill(2);p=DATA/'training_labels'/(name+'.json.gz')
        compact(p,dict(training_cases=train,heldout_cases=test,alternatives=rows));files[str(p.relative_to(DATA))]=sha(p)
        pairs.append(dict(id=name,excluded_origins=[a,b],train_cases=train,test_cases=test,
            train_label_file=str(p.relative_to(DATA)),train_label_sha256=sha(p)))
        print('prepared nested',name,[a,b],len(rows),flush=True)
        del rows
    for fold in old['folds']:
        path=BASE/fold['train_label_file'];assert sha(path)==fold['train_label_sha256']
        model='models/relative/'+fold['id']+'.joblib.gz'
        assert sha(UPSTREAM/model)==read(UPSTREAM/'prediction_lock.json')['files'][model]
        outer.append(dict(id=fold['id'],origin=fold['origin'],train_cases=fold['train_cases'],test_cases=fold['test_cases'],
            calibration_label_file=str(path.relative_to(ROOT)),calibration_label_sha256=sha(path),
            outer_model_file=str((UPSTREAM/model).relative_to(ROOT)),outer_model_sha256=sha(UPSTREAM/model),
            inner_pairs=[p['id'] for p in pairs if fold['origin'] in p['excluded_origins']]))
    value=dict(pairs=pairs,outer=outer,case_groups=groups,origins=origins)
    save(DATA/'fold_index.json',value);files['fold_index.json']=sha(DATA/'fold_index.json')
    sources=[Path(__file__),ROOT/'scripts/nested_calibration_dev25.py',ROOT/'NESTED_CALIBRATION_DEV25_PREREGISTRATION_20261018.md']
    save(DATA/'source_lock.json',dict(files={str(p.relative_to(ROOT)):sha(p) for p in sources}))
    save(DATA/'preparation_lock.json',dict(files=files,source_lock_sha256=sha(DATA/'source_lock.json'),
        upstream_options_lock_sha256=sha(OPTIONS/'preparation_lock.json'),upstream_fold_index_sha256=sha(BASE/'fold_index.json'),
        upstream_model_lock_sha256=sha(UPSTREAM/'prediction_lock.json'),upstream_checkpoint_sha256=sha(checkpoint),
        feature_lock_sha256=sha(FEATURES/'feature_lock.json'),repair_label_lock_sha256=sha(BASE/'label_preparation_lock.json'),
        wall_seconds=time.perf_counter()-wall,final_validation_eligible=False))
    print('DEV25 NESTED FOLDS LOCKED',flush=True)


if __name__=='__main__':prepare()
