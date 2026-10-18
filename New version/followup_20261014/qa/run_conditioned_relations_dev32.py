"""277 whole-file cases, actual suggestions, predictions locked before scoring."""
from collections import Counter
from pathlib import Path
import argparse
import os
import platform
import resource
import sys
import time

import openpyxl

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'qa'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read,save,sha
from run_visible_relations_dev30 import RUN as PRIOR, OLD, totals
from conditioned_relations_dev32 import predict as infer, VERSION
from dependency_execution_dev31 import load_typed_inputs
from formulaguard.workbook import WorkbookModel
from run_annotation_dev15 import prediction as original_pipeline

RUN=ROOT/'development/conditioned_relations_dev32_v3'
MODES=['dev11','conditioned_only','combined']


def prepare():
    assert not RUN.exists()
    from prepare_conditioned_controls_dev32 import PROFIT,DEBT,create
    RUN.mkdir();index=read(PRIOR/'public_index.json');truths=[]
    for family,kinds in [('profit',PROFIT),('debt',DEBT)]:
        for ordinal,kind in enumerate(kinds):
            book,truth=create(family,kind,ordinal)
            identity=family+'__'+kind;case='conditioned_control/'+identity
            path=RUN/'controls'/(identity+'.xlsx');path.parent.mkdir(exist_ok=True);book.save(path)
            index.append(dict(case=case,id=identity,stratum='conditioned_control',input=str(path.relative_to(ROOT)),
                              input_sha256=sha(path),origin_group='authored_'+family+'_control',family=family,scenario=kind))
            truths.append(dict(case=case,**truth))
    assert len(index)==277 and len(truths)==26
    save(RUN/'public_index.json',index);save(RUN/'control_truth.json',dict(cases=truths,final_validation_eligible=False))
    sources=sorted((ROOT/'scripts').glob('*.py'))+sorted((ROOT/'baseline/source').rglob('*.py'))
    sources += [Path(__file__),ROOT/'qa/prepare_conditioned_controls_dev32.py',
                ROOT/'qa/verify_conditioned_relations_dev32.py',ROOT/'tests/test_conditioned_relations_dev32.py',
                ROOT/'tests/test_relation_algebra_dev32.py',
                ROOT/'qa/hard_reference_string_execution_dev28.py',ROOT/'qa/run_string_execution_dev28.py',
                ROOT/'qa/run_visible_relations_dev30.py',ROOT/'baseline/scripts/predict.py',
                ROOT/'CONDITIONED_RELATIONS_DEV32_PREREGISTRATION_20261018.md']
    old_locks=[ROOT/'development'/p for p in [
        'selector_dev11_complete_ast_v1/prediction_lock.json','nested_calibration_dev25_v1/outer/prediction_lock.json',
        'string_execution_dev28_v2/execution_lock.json','visible_relations_dev30_v1/prediction_lock.json',
        'dependency_execution_dev31_v1/execution_lock.json','dependency_execution_dev31_v2/execution_lock.json']]
    save(RUN/'source_lock.json',dict(version=VERSION,files={str(p.relative_to(ROOT)):sha(p) for p in sources},
         old_locks={str(p.relative_to(ROOT)):sha(p) for p in old_locks},
         reused_prediction_files={str(p.relative_to(ROOT)):sha(p) for p in sorted((PRIOR/'predictions').glob('*.json.gz'))}))
    save(RUN/'preparation_lock.json',dict(source_lock_sha256=sha(RUN/'source_lock.json'),
         index_sha256=sha(RUN/'public_index.json'),control_truth_sha256=sha(RUN/'control_truth.json'),
         inputs={i['input']:i['input_sha256'] for i in index}))
    print('DEV32 prepared 277 inputs, 26 pre-labelled controls',flush=True)


def verify():
    lock=read(RUN/'preparation_lock.json');sources=read(RUN/'source_lock.json')
    assert sha(RUN/'source_lock.json')==lock['source_lock_sha256']
    assert sha(RUN/'public_index.json')==lock['index_sha256']
    for rel,digest in {**sources['files'],**sources['old_locks'],**sources['reused_prediction_files'],**lock['inputs']}.items():
        assert sha(ROOT/rel)==digest,rel


def selection(result,observed,paper=False):
    return [dict(cell=r['cell'],status='propose',suggested_formula=r['suggested_formula']) for r in result['rows']
            if r.get('suggested_formula') and r['suggested_formula']!=observed[r['cell']]
            and (paper or r.get('status')=='propose')]


def prediction(item):
    path=ROOT/item['input']
    if item['stratum']=='conditioned_control':
        base=original_pipeline(item);observed=base['observed_formulas']
        dev11=selection(base['dev11'],observed);paper=selection(base['paper'],observed,True);dev30=[]
    else:
        base=read(PRIOR/'predictions'/(item['case'].replace('/','__')+'.json.gz'))
        if base['status']!='complete':
            return dict(case=item['case'],status=base['status'],formula_count=None,dev11=[],paper=None,
                        conditioned_only=[],combined=[],diagnostics=[],dev30_diagnostic=[],labels_read=[])
        dev11=base['dev11'];paper=None;dev30=base['relation_only']
    model=WorkbookModel.from_xlsx(path)
    result=infer(model,load_typed_inputs(path));old={r['cell'] for r in dev11}
    combined=dev11+[r for r in result['suggestions'] if r['cell'] not in old]
    assert len({r['cell'] for r in combined})==len(combined)
    return dict(case=item['case'],status='complete',formula_count=len(model.formulas),dev11=dev11,paper=paper,
                conditioned_only=result['suggestions'],combined=combined,diagnostics=result['rows'],
                dev30_diagnostic=dev30,labels_read=[],original_workbook_modified=False)


def guard_inference():
    active,accesses=[True],set()
    def guard(event,args):
        if active[0] and event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
            name=os.fsdecode(args[0])
            if any(s in name.lower() for s in ['truth','training_labels','author_diff','product_sum_oracle',
                    'prepare_conditioned_controls','prepare_annotation','prepare_multisource','certification',
                    'natural_pair_docs','natural_score','after.xlsx','_uno.json']):
                raise PermissionError('DEV32 inference cannot read scoring/reference evidence: '+name)
            if name.endswith(('.xlsx','.xlsm')):accesses.add(name)
    sys.addaudithook(guard)
    for path in [RUN/'control_truth.json',ROOT/'qa/prepare_conditioned_controls_dev32.py']:
        try:path.read_bytes()
        except PermissionError:pass
        else:raise AssertionError('DEV32 inference guard ineffective')
    return active,accesses


def predict():
    verify();assert not (RUN/'prediction_lock.json').exists()
    active,accesses=guard_inference();wall,cpu=time.perf_counter(),time.process_time();files={};summary=[]
    for item in read(RUN/'public_index.json'):
        result=prediction(item);path=RUN/'predictions'/(item['case'].replace('/','__')+'.json.gz');save(path,result)
        files[str(path.relative_to(RUN))]=sha(path)
        row=dict(case=item['case'],status=result['status'],formulas=result['formula_count'],
                 suggestions={m:len(result[m]) for m in MODES})
        summary.append(row);print('DEV32',row,flush=True)
    save(RUN/'runtime.json',dict(cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall,
         peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,python=platform.python_version(),gpu_used=False,
         scope='new conditioned inference on whole files; old251 locked baseline reused; new26 full original paper/dev11 SG/FG',cases=summary))
    files['runtime.json']=sha(RUN/'runtime.json')
    save(RUN/'prediction_lock.json',dict(files=files,labels_read=[],input_accesses=sorted(accesses),
         source_lock_sha256=sha(RUN/'source_lock.json'),preparation_lock_sha256=sha(RUN/'preparation_lock.json'),
         inference_guard_exercised=True,main_candidate_adopted=False,final_validation_eligible=False))
    active[0]=False;verify();print('DEV32 predictions locked before scoring',flush=True)


def score():
    verify();assert not (RUN/'score.json').exists()
    lock=read(RUN/'prediction_lock.json')
    for rel,digest in lock['files'].items():assert sha(RUN/rel)==digest
    from product_sum_oracle_dev17 import equivalent as public_eq
    old=read(OLD/'heldout_truth.json.gz')['cases']
    controls={r['case']:r for r in read(RUN/'control_truth.json')['cases']}
    legacy={r['case']:r for r in read(PRIOR/'control_truth.json')['cases']}
    string={r['id']:r for r in read(ROOT/'development/record_candidates_dev29_v1/controls_truth.json.gz')['cases']}
    natural={r['cell']:r['accepted_formula'] for r in read(ROOT/'development/natural_cv500_dev27_v1/natural_truth.json.gz')['cases']}
    cases=[]
    for item in read(RUN/'public_index.json'):
        pred=read(RUN/'predictions'/(item['case'].replace('/','__')+'.json.gz'));truth={}
        if item['stratum']=='old213':truth=old[item['case']]
        elif item['stratum']=='conditioned_control':truth=controls[item['case']]
        elif item['stratum']=='new_control':truth=legacy[item['case']]
        elif item['stratum']=='string_control':
            t=string[item['id']];truth=dict(expected_formulas=t['all_expected'],errors=t['errors'])
        elif item['stratum']=='natural_original' and item['id']=='cv500':truth=dict(expected_formulas=natural,errors=list(natural))
        expected=truth.get('expected_formulas',{});errors=set(truth.get('errors',[]));workbook=None
        def matches(formula,cell):
            nonlocal workbook
            target=expected[cell]
            if formula==target:return True
            if item['stratum'] in ('natural_original','string_control'):return False
            if workbook is None:workbook=openpyxl.load_workbook(ROOT/item['input'])
            try:return public_eq(formula,target,cell.rsplit('!',1)[0],workbook)
            except (ValueError,TypeError,KeyError):return False
        record=dict(case=item['case'],stratum=item['stratum'],origin=item['origin_group'],status=pred['status'],
                    family=truth.get('family',item.get('family',item['stratum'])),scenario=str(truth.get('scenario',item['id'])))
        for name in MODES+(['paper'] if item['stratum']=='conditioned_control' else []):
            right,wrong,unknown,unnecessary=[],[],[],[]
            for row in pred[name]:
                cell=row['cell']
                if cell not in expected:unknown.append(cell)
                elif cell not in errors:wrong.append(cell);unnecessary.append(cell)
                elif matches(row['suggested_formula'],cell):right.append(cell)
                else:wrong.append(cell)
            metric=dict(suggestions=len(pred[name]),correct=len(right),wrong=len(wrong),unknown=len(unknown),
                 errors=len(errors),correct_errors=len(set(right)),unnecessary=len(unnecessary),
                 correct_cells=right,wrong_cells=wrong,unknown_cells=unknown)
            metric.update(precision_confirmed_lower_bound=len(right)/len(pred[name]) if pred[name] else None,
                          coverage=len(set(right))/len(errors) if errors else None)
            record[name]=metric
        cases.append(record)
        if workbook:workbook.close()
    by_stratum={key:{m:totals([r[m] for r in cases if r['stratum']==key]) for m in MODES}
                 for key in sorted({r['stratum'] for r in cases})}
    breakdowns={field:{key:{m:totals([r[m] for r in cases if r['stratum']=='old213' and r[field]==key]) for m in MODES}
                       for key in sorted({r[field] for r in cases if r['stratum']=='old213'})} for field in ['origin','family','scenario']}
    control_by_family={family:{m:totals([r[m] for r in cases if r['stratum']=='conditioned_control' and r['family']==family])
                                      for m in MODES+['paper']} for family in ['profit','debt']}
    save(RUN/'score.json',dict(cases=cases,by_stratum=by_stratum,old213_breakdowns=breakdowns,
         new_control_by_family=control_by_family,prediction_lock_sha256=sha(RUN/'prediction_lock.json'),
         control_truth_sha256=sha(RUN/'control_truth.json'),old_truth_sha256=sha(OLD/'heldout_truth.json.gz'),
         main_candidate_adopted=False,final_validation_complete=False,accepted_final_sources=0,accepted_final_families=0,
         mode='revealed development fixed hypothesis; no new-origin generalization claim'))
    for key,values in by_stratum.items():print('DEV32 SCORE',key,values,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','predict','score']);globals()[p.parse_args().phase]()
