"""Full paper/control/annotation prediction; labels read only in separate scoring process."""
from copy import deepcopy
from pathlib import Path
import argparse
import importlib.util
import json
import platform
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'baseline'
DATA = ROOT/'development/annotation_dev14_inputs_v1'
RUN = ROOT/'development/annotation_dev14_v1'
sys.path[:0]=[str(ROOT/'scripts'),str(BASE/'source/HybridGuard_V5_handoff_20260904/src')]
from formulaguard.workbook import WorkbookModel
from formulaguard.v5_structural_guard import v5_structural_guard_scores
from structuralguard.detector import analyze_workbook
from selector_dev2 import select
from selector_dev4 import review_guard
from selector_dev6 import augment
from selector_dev11 import qualify
from annotation_evidence_dev14 import apply, VERSION
from run_selector_dev5 import read,save,sha
from run_selector_dev8 import guard_prediction

spec=importlib.util.spec_from_file_location('dev14_paper',BASE/'scripts/predict.py')
paper_adapter=importlib.util.module_from_spec(spec); spec.loader.exec_module(paper_adapter)
NAMES=['paper','dev11','note_only','dev11_plus_note']

def prediction(item):
    path=ROOT/item['input']
    model=WorkbookModel.from_xlsx(path)
    before=deepcopy((model.cells,model.formulas))
    sg=analyze_workbook(path)['results']
    fg=[{'rank':i,'cell':v.cell_label,'score':v.score,'candidate_formula':v.candidate_formula,'evidence':v.evidence}
        for i,v in enumerate(v5_structural_guard_scores(model),1)]
    forms={s+'!'+a:v for (s,a),v in model.formulas.items()}
    paper=paper_adapter.hybrid((model,sg,fg,forms,[]),{})
    dev2=select(model,paper,fg,sg,[])
    dev11=qualify(model,augment(model,review_guard(model,dev2),[]))
    prior=deepcopy(dev11)
    result={'paper':paper,'dev11':dev11,**apply(model,dev11,paper),
            'observed_formulas':forms,'automatic_edit_applied':False}
    assert prior==dev11 and before==(model.cells,model.formulas)
    for name in NAMES:
        assert len(result[name]['rows'])==len(forms)
        assert {r['cell'] for r in result[name]['rows']}==set(forms)
    return result

def protection():
    accesses,active=set(),[True]
    guard_prediction(accesses,active)
    def guard(event,args):
        if active[0] and event=='open' and isinstance(args[0],(str,bytes)):
            if 'prepare_annotation_dev14' in str(args[0]):
                raise PermissionError('Prediction cannot read author/oracle code')
    sys.addaudithook(guard)
    # Exercise the live access guard, rather than only inspect its source.
    for path in [DATA/'truth.json',ROOT/'scripts/prepare_annotation_dev14.py']:
        try:path.read_bytes()
        except PermissionError:pass
        else:raise AssertionError('oracle guard ineffective')
    return accesses,active

def verify():
    lock=read(RUN/'prediction_lock.json')
    assert sha(RUN/'source_lock.json')==lock['source_lock_sha256']
    for rel,value in read(RUN/'source_lock.json')['files'].items():
        assert sha(ROOT/rel)==value,rel
    for rel,value in lock['inputs'].items():assert sha(ROOT/rel)==value,rel
    for rel,value in lock['files'].items():assert sha(RUN/rel)==value,rel
    assert lock['labels_read']==[] and not lock['final_validation_eligible']
    return lock

def predict():
    if RUN.exists():raise SystemExit('Preserve frozen run; use another version')
    index=read(DATA/'public_index.json')
    sources=sorted((ROOT/'scripts').glob('*.py'))+sorted((ROOT/'tests').glob('*.py'))
    sources+=sorted((BASE/'source').rglob('*.py'))
    sources+=[BASE/'scripts/predict.py',ROOT/'ANNOTATION_DEV14_PLAN_20261018.md']
    save(RUN/'source_lock.json',{'version':VERSION,'files':{str(p.relative_to(ROOT)):sha(p) for p in sources}})
    save(RUN/'public_index.json',index)
    inputs={str((DATA/'public_index.json').relative_to(ROOT)):sha(DATA/'public_index.json')}
    files={}; timings=[]; accesses,active=protection()
    wall,cpu=time.perf_counter(),time.process_time()
    for item in index:
        assert sha(ROOT/item['input'])==item['input_sha256']
        inputs[item['input']]=item['input_sha256']
        t,c=time.perf_counter(),time.process_time()
        result=prediction(item)
        path=RUN/'predictions'/(item['id']+'.json.gz')
        save(path,result); files[str(path.relative_to(RUN))]=sha(path)
        timings.append({'id':item['id'],'wall_seconds':time.perf_counter()-t,
                        'cpu_seconds':time.process_time()-c,'formula_cells':len(result['observed_formulas'])})
        print(item['id'],{n:sum(bool(r.get('suggested_formula')) and r['suggested_formula']!=result['observed_formulas'][r['cell']]
                                    and (n=='paper' or r.get('status')=='propose') for r in result[n]['rows'])
                               for n in NAMES},flush=True)
    active[0]=False
    save(RUN/'runtime.json',{'wall_seconds':time.perf_counter()-wall,'cpu_seconds':time.process_time()-cpu,
                            'process_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                            'gpu_used':False,'scope':'full paper SG/FG and all selectors on 16 complete workbook inputs',
                            'cases':timings,'python':platform.python_version(),'platform':platform.platform()})
    for name in ['public_index.json','runtime.json']:files[name]=sha(RUN/name)
    save(RUN/'prediction_lock.json',{'source_lock_sha256':sha(RUN/'source_lock.json'),'files':files,
         'inputs':inputs,'labels_read':[],'accesses':sorted(accesses),'oracle_guard_exercised':True,
         'final_validation_eligible':False})
    print('DEV14 PREDICTIONS LOCKED',flush=True)

def suggestions(pred,name):
    observed=pred['observed_formulas']
    return [r for r in pred[name]['rows'] if r.get('suggested_formula')
            and r['suggested_formula']!=observed[r['cell']] and (name=='paper' or r.get('status')=='propose')]

def aggregate(rows,name):
    keys=['suggestions','confirmed_correct','confirmed_wrong','unknown','known_errors','correct_errors']
    r={k:sum(x[name][k] for x in rows) for k in keys}
    r['precision_confirmed_lower_bound']=r['confirmed_correct']/r['suggestions'] if r['suggestions'] else None
    r['known_injected_error_coverage']=r['correct_errors']/r['known_errors'] if r['known_errors'] else None
    return r

def score():
    verify()
    # Import author oracle only after lock verification, in this separate command.
    from prepare_annotation_dev14 import equivalent,evaluate
    from openpyxl import load_workbook
    truth=read(DATA/'truth.json')
    for rel,value in read(DATA/'preparation_lock.json')['files'].items():assert sha(DATA/rel)==value
    cases=[]
    for item,t in zip(read(RUN/'public_index.json'),truth['cases']):
        assert item['id']==t['id']
        pred=read(RUN/'predictions'/(item['id']+'.json.gz'))
        w=load_workbook(ROOT/item['input'])
        actual={ws.title+'!'+c.coordinate:c.value for ws in w for row in ws for c in row if c.data_type=='f'}
        assert actual==pred['observed_formulas']==t['observed_formulas']
        errors=set(t['errors']); expected=t['expected_formulas']
        assert errors=={k for k,f in expected.items() if not equivalent(actual[k],f)}
        for label,f in expected.items():
            s,a=label.rsplit('!',1); ws=w[s]
            assert str(evaluate(ws,f,(a,)))==t['numeric_oracle'][label]['expected']
            assert str(evaluate(ws,actual[label],(a,)))==t['numeric_oracle'][label]['observed']
        row={'id':t['id'],'scenario':t['scenario']}
        for name in NAMES:
            rows=suggestions(pred,name); correct=[]; wrong=[]; unknown=[]
            for proposal in rows:
                label=proposal['cell']
                if label not in expected:unknown.append(label)
                elif equivalent(proposal['suggested_formula'],expected[label]):correct.append(label)
                else:wrong.append(label)
            metrics={'suggestions':len(rows),'confirmed_correct':len(correct),'confirmed_wrong':len(wrong),
                     'unknown':len(unknown),'known_errors':len(errors),'correct_errors':len(set(correct)&errors),
                     'correct_cells':correct,'wrong_cells':wrong,'unknown_cells':unknown}
            metrics['precision_confirmed_lower_bound']=len(correct)/len(rows) if rows else None
            metrics['known_injected_error_coverage']=len(set(correct)&errors)/len(errors) if errors else None
            assert len(rows)==len(correct)+len(wrong)+len(unknown)
            row[name]=metrics
        cases.append(row); w.close()
    report={'cases':cases,'all_scenarios':{n:aggregate(cases,n) for n in NAMES},
            'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),
            'known_scope_formulas_per_case':80,'full_formulas_per_case':1349,
            'source_count':1,'templates_independent':False,'unknown_suggestions_kept_in_denominator':True,
            'precision_is_lower_bound_not_business_accuracy':True,
            'oracle_numeric_scope':'local relation given scenario input and observed upstream; no full-sheet recomputation claim',
            'original_source_sha256':truth['source_sha256'],
            'final_validation_eligible':False,'accepted_final_sources':0,'accepted_final_families':0,
            'main_candidate_adopted':False}
    assert not (RUN/'score.json').exists()
    save(RUN/'score.json',report)
    print(json.dumps(report['all_scenarios'],ensure_ascii=False,indent=2))

def replay():
    verify(); accesses,active=protection(); wall=time.perf_counter()
    for item in read(RUN/'public_index.json'):
        actual=prediction(item)
        assert actual==read(RUN/'predictions'/(item['id']+'.json.gz')),item['id']
        print('replayed',item['id'],flush=True)
    active[0]=False
    path=ROOT/'qa/ANNOTATION_DEV14_REPLAY_20261018.json'; assert not path.exists()
    save(path,{'cases':len(read(RUN/'public_index.json')),'identical':True,
               'wall_seconds':time.perf_counter()-wall,'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),
               'labels_read':[],'oracle_guard_exercised':True,'accesses':sorted(accesses)})
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('mode',choices=['predict','score','replay','verify'])
    args=p.parse_args()
    {'predict':predict,'score':score,'replay':replay,'verify':verify}[args.mode]()
