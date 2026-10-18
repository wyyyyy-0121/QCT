"""Independent selected-option/pair reconstruction and source-weight audit."""
from collections import Counter,defaultdict
from pathlib import Path
import argparse
import hashlib
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from build_keep_features_dev21 import BASE,case_path
DATA=ROOT/'development/absolute_selection_dev24_data_v1'
STATES=ROOT/'development/tristate_states_dev23_v1'
RUN=ROOT/'development/absolute_selection_dev24_v1'
OPTION_FIELDS=['case','cell','id','kind','label']
PAIR_FIELDS=['case','cell','left_id','right_id','label']


def digest(rows,fields):
    result=hashlib.sha256();first=True
    for row in rows:
        if not first:result.update(b'\n')
        result.update('\t'.join(str(row[k]) for k in fields).encode());first=False
    return result.hexdigest()


def independent_selection(states):
    grouped=defaultdict(list)
    for row in states:grouped[row['case'],row['cell']].append(row)
    selected=[];pairs=[]
    for (case,cell),values in sorted(grouped.items()):
        assert len(values)==len({r['id'] for r in values})
        assert sum(r['kind']=='keep' for r in values)==1
        pos=sorted([r for r in values if r['label']==1],key=lambda r:r['id'])
        neg=sorted([r for r in values if r['label']==0 and r['kind']=='candidate'],key=lambda r:r['id'])[:32]
        neg += [r for r in values if r['kind']=='keep' and r['label']==0]
        selected.extend(pos+neg)
        for left in pos:
            for right in neg:
                pairs.append(dict(case=case,cell=cell,left_id=left['id'],right_id=right['id'],label=1))
                pairs.append(dict(case=case,cell=cell,left_id=right['id'],right_id=left['id'],label=0))
    return selected,pairs


def weight_summary(rows):
    counts=Counter(r['case'] for r in rows);families=defaultdict(set);sources=defaultdict(set)
    for r in rows:
        families[r['source'],r['family']].add(r['case']);sources[r['source']].add(r['family'])
    raw=[1/(len(sources[r['source']])*len(families[r['source'],r['family']])*counts[r['case']]) for r in rows]
    scale=len(raw)/sum(raw);source_sums=defaultdict(float);classes=Counter()
    for r,w in zip(rows,raw):source_sums[r['source']]+=w*scale;classes[r['label']]+=w*scale
    assert max(source_sums.values())-min(source_sums.values())<1e-4
    return dict(source_weight_sums=dict(source_sums),class_weight_sums=[classes[0],classes[1]])


def main(check_runtime=False):
    lock=read(DATA/'preparation_lock.json');state_lock=read(STATES/'preparation_lock.json')
    for folder,record in [(DATA,lock),(STATES,state_lock)]:
        for rel,value in record['files'].items():assert sha(folder/rel)==value,rel
        assert sha(folder/'source_lock.json')==record['source_lock_sha256']
        for rel,value in read(folder/'source_lock.json')['files'].items():assert sha(ROOT/rel)==value,rel
    assert sha(STATES/'preparation_lock.json')==lock['upstream_state_lock_sha256']
    summaries={r['case']:r for r in read(DATA/'state_counts.json')};case_rows={};results=[]
    runtime={(r['fold'],r['arm']):r for r in read(RUN/'runtime.json')['folds']} if check_runtime else {}
    for item in read(BASE/'public_index.json'):
        case=item['case'];meta=summaries[case]
        states=read(STATES/'author_case_states'/(case_path(case)+'.json.gz'))['alternatives']
        selected,pairs=independent_selection(states)
        assert len(selected)==meta['options'] and digest(selected,OPTION_FIELDS)==meta['option_sha256']
        assert len(pairs)==meta['directed_pairs'] and digest(pairs,PAIR_FIELDS)==meta['pair_sha256']
        fields=OPTION_FIELDS+['source','family']
        def enrich(r):return {**{k:r[k] for k in OPTION_FIELDS},'source':meta['source'],'family':meta['family']}
        expected=[enrich(r) for r in selected];present={(r['cell'],r['id']) for r in selected}
        expected += [enrich(r) for r in states if r['kind']=='keep' and (r['cell'],r['id']) not in present]
        saved=read(DATA/'author_case_options'/(case_path(case)+'.json.gz'))['alternatives']
        assert saved==expected,case
        case_rows[case]=saved
    for fold in read(DATA/'fold_index.json')['folds']:
        assert not set(fold['train_cases'])&set(fold['test_cases'])
        assert len(fold['train_cases'])+len(fold['test_cases'])==213
        rows=[]
        for case in fold['train_cases']:
            assert summaries[case]['source']!=fold['origin'];rows.extend(case_rows[case])
        assert all(summaries[case]['source']==fold['origin'] for case in fold['test_cases'])
        saved=read(DATA/fold['train_label_file'])
        assert saved['alternatives']==rows and saved['training_cases']==fold['train_cases'] and saved['heldout_cases']==fold['test_cases']
        selected,pairs=independent_selection(rows)
        metadata={r['case']:{k:r[k] for k in ['source','family']} for r in rows}
        pairs=[dict(r,**metadata[r['case']]) for r in pairs]
        for arm,training,fields in [('absolute',selected,OPTION_FIELDS),('relative',pairs,PAIR_FIELDS)]:
            summary=dict(fold=fold['id'],arm=arm,rows=len(training),positive=sum(r['label'] for r in training),
                negative=sum(r['label']==0 for r in training),selection_sha256=digest(training,fields),**weight_summary(training))
            if check_runtime:
                old=runtime[fold['id'],arm]
                for key in ['rows','positive','negative','selection_sha256']:assert old[key]==summary[key],(fold['id'],arm,key)
                for source,value in summary['source_weight_sums'].items():assert abs(old['source_weight_sums'][source]-value)<1e-4
                for v in [0,1]:assert abs(old['class_weight_sums'][v]-summary['class_weight_sums'][v])<1e-4
            results.append(summary)
        print('independent dev24 training verified',fold['id'],len(selected),len(pairs),flush=True)
        del rows,saved,selected,pairs,training
    suffix='_RUNTIME' if check_runtime else ''
    target=ROOT/('qa/ABSOLUTE_SELECTION_DEV24_TRAINING_AUDIT'+suffix+'_20261018.json');assert not target.exists()
    save(target,dict(cases=213,folds=results,all_options_and_pairs_independently_rebuilt=True,all_weights_verified=True,
        runtime_checked=check_runtime,preparation_lock_sha256=sha(DATA/'preparation_lock.json'),
        auditor_sha256=sha(Path(__file__)),final_validation_eligible=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check-runtime',action='store_true')
    main(parser.parse_args().check_runtime)
