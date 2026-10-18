"""Independently adjudicate candidates and recount predictions without scorer helpers."""
from collections import Counter,defaultdict
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_candidate_learning_dev16 import RUN,DATA,verify
from run_selector_dev5 import read,save,sha
from audit_annotation_dev14_v2 import equals
from semantic_fingerprint_dev16 import fingerprint
from formulaguard.workbook import WorkbookModel

KEYS=['suggestions','correct','wrong','unknown','errors','correct_errors','wrong_clean_cells']
MODES=['dev11','learned_only','keep_base_plus_learned']

def main():
    verify(include_label_bodies=True)
    truth=read(DATA/'heldout_truth.json.gz');folds=read(RUN/'fold_index.json')
    score=read(RUN/'score.json');labels={};id_labels={};positive=unknown=0
    index=read(DATA/'public_index.json')
    # Recheck prepared labels directly against frozen formula truth, using a
    # different token parser for public product expressions.
    features={}
    baseline={}
    for item in index:
        case=item['case'];t=truth['cases'][case]
        payload=read(DATA/'features'/(case.replace('/','__')+'.json.gz'))
        features[case]=payload['candidates'];baseline[case]=payload['baseline']
        labels[case]={}
        for c in payload['candidates']:
            cell=c['cell'];expected=t['expected_formulas'].get(cell)
            y=None if expected is None else int(
                equals(c['formula'],expected) if t['group']=='lcoe' else c['formula']==expected)
            assert y==truth['candidate_labels'][case][c['id']]
            labels[case][c['cell'],c['formula']]=y
            id_labels[c['id']]=y
            positive+=y==1;unknown+=y is None
            if y==1:assert cell in set(t['errors'])
    counted=defaultdict(lambda:{m:Counter() for m in MODES});audited=0
    group_checks=[]
    semantic=defaultdict(list)
    for item in index:
        m=WorkbookModel.from_xlsx(ROOT/item['input'])
        semantic[fingerprint(m,item['parallel_sheets'])].append(item['case'])
    for fold in folds['folds']:
        train=set(fold['train_cases']);test=set(fold['test_cases']);assert not train&test
        training=read(DATA/fold['train_label_file'])
        assert {r['case'] for r in training['rows']}<=train
        assert all(id_labels[r['id']]==r['label'] for r in training['rows'])
        for members in semantic.values():
            assert not (set(members)&train and set(members)&test)
        if fold['scheme']=='source':
            assert {truth['cases'][c]['origin_group'] for c in train}.isdisjoint(
                   {truth['cases'][c]['origin_group'] for c in test})
        else:
            assert {truth['cases'][c]['family'] for c in train}.isdisjoint(
                   {truth['cases'][c]['family'] for c in test})
        group_checks.append({'fold':fold['id'],'train_cases':len(train),'test_cases':len(test),
                             'semantic_overlap':False,'group_overlap':False})
        rows={r['case']:r for r in score['schemes'][fold['scheme']]['cases']}
        for case in fold['test_cases']:
            t=truth['cases'][case];pred=read(RUN/'predictions'/fold['id']/(case.replace('/','__')+'.json.gz'))
            assert pred['dev11']==baseline[case]
            for mode in MODES:
                out=pred[mode];assert len(out)==len({r['cell'] for r in out})
                c=Counter(suggestions=len(out),errors=len(t['errors']))
                for r in out:
                    cell=r['cell'];y=labels[case][cell,r['suggested_formula']]
                    if y is None:c['unknown']+=1
                    elif y==1 and cell in t['errors']:c['correct']+=1;c['correct_errors']+=1
                    else:c['wrong']+=1;c['wrong_clean_cells']+=cell not in t['errors']
                for key in KEYS:
                    assert c[key]==rows[case][mode][key],(fold['id'],case,mode,key)
                    counted[fold['scheme']][mode][key]+=c[key]
                audited+=1
    for scheme,methods in counted.items():
        for mode,c in methods.items():
            old=score['schemes'][scheme]['all'][mode]
            for key in KEYS:assert c[key]==old[key]
            assert old['precision_confirmed_lower_bound']==(c['correct']/c['suggestions'] if c['suggestions'] else None)
            assert old['coverage']==(c['correct_errors']/c['errors'] if c['errors'] else None)
    out=ROOT/'qa/CANDIDATE_LEARNING_DEV16_INDEPENDENT_AUDIT_20261018.json';assert not out.exists()
    save(out,{'candidate_labels_independently_checked':sum(len(v) for v in features.values()),
              'known_correct_candidate_records':positive,'unknown_candidates':unknown,
              'fold_group_checks':group_checks,'semantic_duplicate_groups':sum(len(v)>1 for v in semantic.values()),
              'case_method_count_checks':audited,'all_count_checks_passed':True,
              'aggregate_counts':counted,'feature_answer_isolation_verified':read(DATA/'feature_lock.json')['labels_read']==[],
              'audit_script_sha256':sha(Path(__file__)),'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),
              'main_candidate_adopted':False,'final_validation_eligible':False})
    print('independent candidate labels and blocked metrics verified',audited,flush=True)
if __name__=='__main__':main()
