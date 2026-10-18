"""Independent reconstruction of all nested origin exclusions, pairs and weights."""
from pathlib import Path
import argparse
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src'),str(ROOT/'qa')]
from run_selector_dev5 import read,save,sha
from audit_absolute_training_dev24 import independent_selection,weight_summary,digest,PAIR_FIELDS
DATA=ROOT/'development/nested_calibration_dev25_data_v1'
OPTIONS=ROOT/'development/absolute_selection_dev24_data_v1'
RUN=ROOT/'development/nested_calibration_dev25_v1'


def main(check_runtime=False):
    lock=read(DATA/'preparation_lock.json');options_lock=read(OPTIONS/'preparation_lock.json')
    for rel,value in lock['files'].items():assert sha(DATA/rel)==value,rel
    assert sha(DATA/'source_lock.json')==lock['source_lock_sha256']
    for rel,value in read(DATA/'source_lock.json')['files'].items():assert sha(ROOT/rel)==value,rel
    index=read(DATA/'fold_index.json');groups=index['case_groups'];case_order=list(groups)
    cases={}
    for case in case_order:
        rel='author_case_options/'+case.replace('/','__')+'.json.gz'
        assert sha(OPTIONS/rel)==options_lock['files'][rel]
        cases[case]=read(OPTIONS/rel)['alternatives']
    runtime={r['pair']:r for r in read(RUN/'inner/runtime.json')['folds']} if check_runtime else {}
    results=[]
    for pair in index['pairs']:
        excluded=set(pair['excluded_origins']);assert len(excluded)==2
        train=[c for c in case_order if groups[c]['origin_group'] not in excluded]
        assert set(train)==set(pair['train_cases'])
        assert set(pair['test_cases'])==set(case_order)-set(train)
        assert len(pair['train_cases'])+len(pair['test_cases'])==213
        expected=[]
        # Writer uses public-index order, which may differ from sorted JSON
        # metadata. Respect the locked declared order and independently verify
        # its exact eligible case set above.
        for c in pair['train_cases']:expected.extend(cases[c])
        payload=read(DATA/pair['train_label_file'])
        assert payload['alternatives']==expected and payload['training_cases']==pair['train_cases'] and payload['heldout_cases']==pair['test_cases']
        assert all(r['source'] not in excluded for r in expected)
        selected,pairs=independent_selection(expected)
        metadata={c:{'source':groups[c]['origin_group'],'family':groups[c]['family']} for c in train}
        pairs=[dict(r,**metadata[r['case']]) for r in pairs]
        summary=dict(pair=pair['id'],excluded_origins=pair['excluded_origins'],rows=len(pairs),positive=sum(r['label'] for r in pairs),
            negative=sum(r['label']==0 for r in pairs),selection_sha256=digest(pairs,PAIR_FIELDS),**weight_summary(pairs))
        if check_runtime:
            old=runtime[pair['id']]
            for k in ['excluded_origins','rows','positive','negative','selection_sha256']:assert old[k]==summary[k],(pair['id'],k)
            for source,value in summary['source_weight_sums'].items():assert abs(value-old['source_weight_sums'][source])<1e-4
            for v in [0,1]:assert abs(summary['class_weight_sums'][v]-old['class_weight_sums'][v])<1e-4
        results.append(summary);print('nested pair independently verified',pair['id'],len(pairs),flush=True)
        del expected,payload,selected,pairs
    for outer in index['outer']:
        a=outer['origin'];train=set(outer['train_cases']);test=set(outer['test_cases'])
        assert train=={c for c in case_order if groups[c]['origin_group']!=a}
        assert test==set(case_order)-train
        expected={p['id'] for p in index['pairs'] if a in p['excluded_origins']}
        assert len(expected)==4 and expected==set(outer['inner_pairs'])
        assert sha(ROOT/outer['calibration_label_file'])==outer['calibration_label_sha256']
        assert sha(ROOT/outer['outer_model_file'])==outer['outer_model_sha256']
    assert len(results)==10
    suffix='_RUNTIME' if check_runtime else ''
    target=ROOT/('qa/NESTED_CALIBRATION_DEV25_TRAINING_AUDIT'+suffix+'_20261018.json');assert not target.exists()
    save(target,dict(pairs=results,all_nested_origin_exclusions_verified=True,all_pairs_and_weights_independently_rebuilt=True,
        runtime_checked=check_runtime,preparation_lock_sha256=sha(DATA/'preparation_lock.json'),auditor_sha256=sha(Path(__file__)),final_validation_eligible=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check-runtime',action='store_true');main(parser.parse_args().check_runtime)
