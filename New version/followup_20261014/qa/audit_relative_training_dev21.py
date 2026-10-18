"""Independent deterministic training selection/count audit on locked old fold labels."""
from pathlib import Path
from collections import defaultdict,Counter
import hashlib
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from build_keep_features_dev21 import BASE,case_path
from relative_learning_dev21 import selected_rows
from run_candidate_learning_dev18 import weights
from run_relative_learning_dev21 import RUN,verify

verify()
runtime={r['fold']:r for r in read(RUN/'runtime.json')['folds']}
rows=[]
for fold in read(BASE/'fold_index.json')['folds']:
    path=BASE/fold['train_label_file'];assert sha(path)==fold['train_label_sha256']
    labels=read(path)['rows'];cases=defaultdict(dict)
    for r in labels:cases[r['case']][r['id']]=r
    assert not set(cases)&set(fold['test_cases'])
    groups=defaultdict(list);enriched=[]
    for case,lookup in cases.items():
        payload=read(BASE/'features'/(case_path(case)+'.json.gz'))
        for c in payload['candidates']:
            if c['id'] not in lookup:continue
            r={**lookup[c['id']],'cell':c['cell']};groups[case,c['cell']].append(r);enriched.append(r)
    # Independent grouping/prefix count; no call to production selection here.
    expected=[]
    for key in sorted(groups):
        values=groups[key];p=[r for r in values if r['label']==1];n=[r for r in values if r['label']==0]
        expected+=sorted(p,key=lambda r:r['id'])+sorted(n,key=lambda r:r['id'])[:32]
    actual=selected_rows(enriched)
    assert expected==actual
    assert sum(r['label'] for r in expected)==sum(r['label'] for r in labels)
    weights_out=weights(actual)
    # Verify hierarchical weight directly from independent counts.
    family_cases=defaultdict(set);source_families=defaultdict(set);case_counts=Counter(r['case'] for r in actual)
    for r in actual:family_cases[r['source'],r['family']].add(r['case']);source_families[r['source']].add(r['family'])
    raw=[1/(len(source_families[r['source']])*len(family_cases[r['source'],r['family']])*case_counts[r['case']]) for r in actual]
    denom=sum(raw);sums=defaultdict(float)
    for r,w0,w1 in zip(actual,raw,weights_out):
        assert abs(w1-w0*len(raw)/denom)<1e-8;sums[r['source']]+=w1
    assert max(sums.values())-min(sums.values())<1e-5
    ids='\n'.join(r['case']+'\t'+r['id']+'\t'+str(r['label']) for r in actual)
    rows.append({'fold':fold['id'],'original_rows':len(labels),'selected_rows':len(actual),
                 'positive_original':sum(r['label'] for r in actual),'mirrored_positive':len(actual),
                 'mirrored_negative':len(actual),'source_weight_sums':dict(sums),
                 'selection_sha256':hashlib.sha256(ids.encode()).hexdigest()})
    logged=runtime[fold['id']]
    assert logged['selection_sha256']==rows[-1]['selection_sha256']
    assert logged['selected_original_rows']==len(actual)
    assert logged['mirrored_rows']==2*len(actual)
    assert logged['positive']==logged['negative']==len(actual)
    assert logged['features']==712
    assert all(abs(v-len(actual))<1e-5 for v in logged['class_weight_sums'])
    print(rows[-1],flush=True)
out=ROOT/'qa/RELATIVE_LEARNING_DEV21_TRAINING_AUDIT_20261018.json';assert not out.exists()
save(out,{'folds':rows,'all_positive_candidates_preserved':True,'all_unknown_candidates_excluded':True,
          'all_source_weight_checks_passed':True,'audit_source_sha256':sha(Path(__file__)),'final_validation_eligible':False})
