"""Author-only labels and blocked folds, after label-free feature lock exists."""
from collections import Counter,defaultdict
from pathlib import Path
import hashlib
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from run_selector_dev5 import read,save,sha
from run_selector_dev8 import truth_and_observed
from build_candidates_dev16 import DATA,OLD,NOTE,upstream
from prepare_annotation_dev14 import equivalent
from formulaguard.workbook import WorkbookModel
from semantic_fingerprint_dev16 import fingerprint

def load_truth(item,controlled,notes):
    if item['group']=='lcoe':return notes[item['id']]
    if item['group']=='controlled_reconciliation':return controlled[item['id']]
    t,_=truth_and_observed(item);return t

def prepare():
    if (DATA/'label_preparation_lock.json').exists():raise SystemExit('Preserve prepared labels')
    lock=read(DATA/'feature_lock.json')
    for rel,v in lock['files'].items():assert sha(DATA/rel)==v
    controlled={x['id']:x for x in read(ROOT/'development/reconciliation_dev12_inputs_v1/truth.json')['cases']}
    notes={x['id']:x for x in read(ROOT/'development/annotation_dev14_inputs_v1/truth.json')['cases']}
    index=read(DATA/'public_index.json'); cases={};labels={};semantic=defaultdict(list)
    for item in index:
        t=load_truth(item,controlled,notes);payload=read(DATA/'features'/(item['case'].replace('/','__')+'.json.gz'))
        _,observed=upstream(item)
        if item['group']=='lcoe':family='lcoe'
        elif item['group'] in ['regression','stress','tradeoff']:family='profit'
        else:family=t['family']
        expected=t['expected_formulas']; errors=set(t['errors'])
        if item['group']=='lcoe':assert errors=={c for c,f in expected.items() if not equivalent(f,observed[c])}
        else:assert errors=={c for c,f in expected.items() if f!=observed[c]}
        candidate_labels={}
        for c in payload['candidates']:
            y=None if c['cell'] not in expected else int(
                equivalent(c['formula'],expected[c['cell']]) if item['group']=='lcoe'
                else c['formula']==expected[c['cell']])
            candidate_labels[c['id']]=y
        model=WorkbookModel.from_xlsx(ROOT/item['input'])
        semantic[fingerprint(model,item['parallel_sheets'])].append(item['case'])
        cases[item['case']]={'family':family,'origin_group':item['origin_group'],
                            'group':item['group'],'scenario':t.get('scenario'),
                            'expected_formulas':expected,'errors':sorted(errors),
                            'observed_formulas':observed}
        labels[item['case']]=candidate_labels
    families=sorted({v['family'] for v in cases.values()},key=lambda s:hashlib.sha256(s.encode()).hexdigest())
    family_folds={f:n%5 for n,f in enumerate(families)}
    # Exact semantic duplicates with different registered families are an audit
    # failure, not a reason to permit leakage or silently drop the cases.
    for digest,members in semantic.items():
        assert len({family_folds[cases[m]['family']] for m in members})==1,(digest,members)
        assert len({cases[m]['origin_group'] for m in members})==1
    folds=[]
    for scheme,keys in [('family',range(5)),('source',sorted({v['origin_group'] for v in cases.values()}))]:
        for key in keys:
            test=[case for case,t in cases.items()
                  if (family_folds[t['family']]==key if scheme=='family' else t['origin_group']==key)]
            train=[case for case in cases if case not in set(test)]
            name=scheme+'__'+str(key)
            train_path=DATA/'training_labels'/(name+'.json.gz')
            rows=[]
            for case in train:
                for cid,y in labels[case].items():
                    if y is not None:rows.append({'case':case,'family':cases[case]['family'],'id':cid,'label':y})
            assert train and test and rows
            save(train_path,{'fold':name,'rows':rows,'training_cases':train,'heldout_cases':test})
            folds.append({'id':name,'scheme':scheme,'train_cases':train,'test_cases':test,
                          'train_label_file':str(train_path.relative_to(DATA)),
                          'train_label_sha256':sha(train_path),
                          'train_family_counts':dict(Counter(cases[c]['family'] for c in train)),
                          'heldout_families':sorted({cases[c]['family'] for c in test}),
                          'heldout_origins':sorted({cases[c]['origin_group'] for c in test})})
    save(DATA/'fold_index.json',{'folds':folds,'family_assignment':family_folds,
                                'case_groups':{c:{k:t[k] for k in ['family','origin_group','group']} for c,t in cases.items()},
                                'semantic_duplicate_groups':[m for m in semantic.values() if len(m)>1],
                                'same_semantic_input_never_crosses_folds':True})
    save(DATA/'heldout_truth.json.gz',{'cases':cases,'candidate_labels':labels,
                                      'feature_lock_sha256':sha(DATA/'feature_lock.json'),
                                      'role':'revealed development labels; forbidden in training/prediction',
                                      'final_validation_eligible':False})
    paths=[DATA/'fold_index.json',DATA/'heldout_truth.json.gz']+sorted((DATA/'training_labels').glob('*.gz'))
    save(DATA/'label_preparation_lock.json',{'files':{str(p.relative_to(DATA)):sha(p) for p in paths},
          'author_script_sha256':sha(Path(__file__)),'feature_lock_sha256':sha(DATA/'feature_lock.json')})
    print('prepared',len(cases),'cases',len(folds),'folds','families',len(families),'semantic duplicate groups',
          sum(len(m)>1 for m in semantic.values()),flush=True)
if __name__=='__main__':prepare()
