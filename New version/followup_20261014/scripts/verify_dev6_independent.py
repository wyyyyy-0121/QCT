"""Independently recount dev6, including failures, scope and historical locks.

Does not import either experiment scorer. Optional replay reads inputs/upstream
only, denies answer files, and compares all 107 outputs to immutable predictions.
"""
from collections import Counter
from pathlib import Path
import argparse
import datetime
import gzip
import hashlib
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
sys.path.insert(0, str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    data=path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix=='.gz' else data)


def verify_lock(run):
    lock=read(run/'prediction_lock.json')
    assert sha(run/'source_lock.json')==lock['source_lock_sha256']
    assert sha(run/'public_index.json')==lock['public_index_sha256']
    assert lock['labels_read']==[]
    sources=read(run/'source_lock.json')['files']; recovered=[]
    for rel,expected in sources.items():
        path=ROOT/rel
        if sha(path)!=expected:
            path=ROOT/'qa/dev6_source_recovery_20261015'/rel
            assert path.exists() and sha(path)==expected, rel
            recovered.append(rel)
    for rel,expected in lock['files'].items(): assert sha(run/rel)==expected,rel
    for rel,expected in lock['inputs_and_upstream'].items(): assert sha(ROOT/rel)==expected,rel
    index=read(run/'public_index.json')
    assert len(index)==len({(v['group'],v['id']) for v in index})==107
    for v in index:
        assert sha(ROOT/v['input'])==v['input_sha256']
        assert sha(ROOT/v['upstream'])==v['upstream_sha256']
    return index,{'files':len(lock['files']),'source_files':len(sources),
                  'recovered_exact_hash_sources':recovered,
                  'prediction_lock_sha256':sha(run/'prediction_lock.json')}


def counts(pred,truth,observed):
    expected=truth['expected_formulas']; errors=set(truth['errors'])
    rows=pred['rows']; labels=[r['cell'] for r in rows]
    assert len(rows)==len(set(labels))==len(expected)==len(observed)
    assert set(labels)==set(expected)==set(observed)
    assert errors=={k for k,v in observed.items() if v!=expected[k]}
    out=Counter(proposals=0,correct=0,wrong=0,errors=len(errors),harmful_correct_cells=0)
    for row in rows:
        assert row['status'] in ('propose','abstain','review')
        if row['status']!='propose' or not row.get('suggested_formula') or row['suggested_formula']==observed[row['cell']]:continue
        out['proposals']+=1
        if row['suggested_formula']==expected[row['cell']]:out['correct']+=1
        else:out['wrong']+=1
        if row['cell'] not in errors:out['harmful_correct_cells']+=1
    return dict(out)


def totals(items):
    keys=('proposals','correct','wrong','errors','harmful_correct_cells')
    out={k:sum(v[k] for v in items) for k in keys}
    return {**out,'precision':out['correct']/out['proposals'] if out['proposals'] else None,
            'coverage':out['correct']/out['errors'] if out['errors'] else None}


def audit():
    runs={name:ROOT/'development'/name for name in ('selector_dev6_contract','selector_dev6_contract_v2')}
    evidence={}; comparisons=[]
    for name,run in runs.items():
        index,lock_report=verify_lock(run); score=read(run/'score.json')
        assert score['prediction_lock_sha256']==sha(run/'prediction_lock.json')
        groups={}; variants={}; source_truth={}
        for item in index:
            group,case=item['group'],item['id']
            if group=='regression':truth=read(ROOT/'baseline/data'/case/'truth.json')
            else:
                folder={'stress':'semantic_stress_dev1','tradeoff':'policy_tradeoff_dev1',
                        'crossdomain':'crossdomain_dev1','adversarial':'dev5_adversarial1'}[group]
                if folder not in source_truth:
                    source_truth[folder]={v['id']:v for v in read(ROOT/'development'/folder/'truth.json')['cases']}
                truth=source_truth[folder][case]
            model=WorkbookModel.from_xlsx(ROOT/item['input'])
            observed={s+'!'+a:v for (s,a),v in model.formulas.items()}
            result=counts(read(run/'predictions'/group/(case+'.json.gz')),truth,observed)
            recorded=next(v['dev6'] for v in score[group]['cases'] if v['id']==case)
            assert all(recorded[k]==v for k,v in result.items()),(name,case)
            groups.setdefault(group,[]).append(result)
            if group=='adversarial':variants.setdefault(truth['scenario'],[]).append(result)
        group_totals={g:totals(items) for g,items in groups.items()}
        for g,v in group_totals.items():assert v==score[g]['totals'],(g,v,score[g]['totals'])
        evidence[name]={'lock':lock_report,'group_diagnostic_totals':group_totals,
                        'adversarial_by_variant':{k:totals(v) for k,v in variants.items()},
                        'pooled_adversarial_acceptance_metric':False,
                        'score_sha256':sha(run/'score.json')}
    previous=read(ROOT/'development/dev5_adversarial1/score.json')
    original=totals([v['dev5'] for v in previous['cases']])
    assert original['correct']==8 and original['wrong']==4 and original['errors']==584
    result={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'role':'independent revealed-development audit; no final acceptance',
            'runs':evidence,'dev5_actual_adversarial_diagnostic':original,
            'reported_comparison_corrected':True,
            'corrected_comparison':'dev5 8/584; dev6 initial 368/584; dev6 v2 463/584',
            'final_validation_passed':False}
    target=ROOT/'qa/DEV6_INDEPENDENT_AUDIT_20261015.json'
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(result['corrected_comparison'])
    for name,v in evidence.items():print(name,v['adversarial_by_variant'])


def replay():
    run=ROOT/'development/selector_dev6_contract_v2'; index,verified=verify_lock(run)
    from selector_dev6 import augment
    def guard(event,args):
        if event=='open' and isinstance(args[0],(str,bytes)):
            name=str(args[0]).casefold()
            if any(word in name for word in ['truth.json','registration.json','/score',
                   'data_manifest.json','input_oracle','mutation_log']):
                raise PermissionError('Replay denies scoring evidence: '+name)
    sys.addaudithook(guard)
    started=time.perf_counter(); outputs=[]
    for item in index:
        model=WorkbookModel.from_xlsx(ROOT/item['input']); source=read(ROOT/item['upstream'])
        prior=source['dev4'] if item['group'] in ('crossdomain','adversarial') else source
        expected=read(run/'predictions'/item['group']/(item['id']+'.json.gz'))
        before=dict(model.formulas)
        output=augment(model,prior,item['parallel_sheets'])
        assert output==expected,(item['group'],item['id'])
        assert before==model.formulas
        outputs.append({'group':item['group'],'id':item['id'],'identical':True})
        print(item['group'],item['id'],'identical',flush=True)
    result={'cases':outputs,'case_count':len(outputs),'labels_read':[],
            'wall_seconds':time.perf_counter()-started,'source_lock_verified':verified,
            'scope':'all 107 dev6 v2 augmentations; excludes original upstream execution'}
    (ROOT/'qa/DEV6_REPLAY_20261015.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Replay complete:',len(outputs),'cases',result['wall_seconds'],'seconds')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['audit','replay'])
    {'audit':audit,'replay':replay}[parser.parse_args().stage]()
