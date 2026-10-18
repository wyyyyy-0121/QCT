"""Run frozen paper/dev11 on declared, already revealed static-view controls."""
from pathlib import Path
from copy import deepcopy
from collections import Counter
import argparse
import datetime
import importlib.util
import json
import platform
import resource
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
BASE = ROOT / 'baseline'
RUN = ROOT / 'development/static_ooxml_view_dev1'
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(BASE / 'source/HybridGuard_V5_handoff_20260904/src'))
from run_selector_dev5 import read, save, sha
from static_ooxml_view_dev1 import create_view, VERSION
from execution_reference import formula_declarations
from formulaguard.workbook import WorkbookModel
from formulaguard.v5_structural_guard import v5_structural_guard_scores
from structuralguard.detector import analyze_workbook
from selector_dev2 import select
from selector_dev4 import review_guard
from selector_dev6 import augment
from selector_dev11 import qualify


def pipeline(path):
    model = WorkbookModel.from_xlsx(path)
    before = deepcopy((model.cells, model.formulas))
    structural = analyze_workbook(path)['results']
    fg = [{'rank': i, 'cell': x.cell_label, 'score': x.score,
           'candidate_formula': x.candidate_formula, 'evidence': x.evidence}
          for i, x in enumerate(v5_structural_guard_scores(model), 1)]
    observed = {s+'!'+a: v for (s,a),v in model.formulas.items()}
    spec = importlib.util.spec_from_file_location('static_view_frozen_paper', BASE / 'scripts/predict.py')
    paper = importlib.util.module_from_spec(spec); spec.loader.exec_module(paper)
    raw = paper.hybrid((model, structural, fg, observed, []), {})
    dev11 = qualify(model, augment(model, review_guard(model, select(model, raw, fg, structural, [])), []))
    assert (model.cells, model.formulas) == before
    _values, errors = model.evaluate()
    return {'observed_formulas': observed, 'paper': raw, 'dev11': dev11,
            'evaluation_errors': {s+'!'+a: str(x) for (s,a),x in errors.items()},
            'formula_declarations': formula_declarations(path)}


def denied(event, args):
    if event == 'open' and args and isinstance(args[0], (str, bytes)):
        path = str(args[0]).casefold()
        if any(x in path for x in ['truth.json','registration.json','/score','input_oracle','mutation_log','failure_audit']):
            raise PermissionError('Static view worker may not read label evidence')


def worker(item, view):
    sys.addaudithook(denied)
    t,c = time.perf_counter(),time.process_time()
    source = REPO / item['relative_path']
    try:
        receipt = create_view(source, view)
    except ValueError as error:
        return {'id':item['id'], 'status':'input_rejected', 'error':str(error),
                'input_sha256':sha(source),'labels_read':[], 'precision':None,'coverage':None}
    result = pipeline(view)
    # The pure OOXML model reads static formulas directly from xlsm too. Its
    # pre/post comparison isolates the SG extension envelope from cell changes.
    original = WorkbookModel.from_xlsx(source)
    assert {s+'!'+a:v for (s,a),v in original.formulas.items()} == result['observed_formulas']
    formula_labels = set(result['observed_formulas'])
    summaries={}
    for name in ['paper','dev11']:
        rows = result[name]['rows']
        assert len(rows)==len({r['cell'] for r in rows})==len(formula_labels)
        assert {r['cell'] for r in rows}==formula_labels
        suggestions=[r for r in rows if r.get('suggested_formula') and
                     r['suggested_formula'] != result['observed_formulas'][r['cell']] and
                     (name=='paper' or r['status']=='propose')]
        summaries[name]={'actual_modification_suggestions':len(suggestions),
                         'raw_status_counts':dict(Counter(r['status'] for r in rows))}
    control={}
    if item['id']=='public01':
        prior = read(ROOT / 'development/public_candidate_pipeline_dev10/predictions/public01.json.gz')
        assert result['paper']==prior['predictions']['paper']
        assert result['dev11']==read(ROOT / 'development/selector_dev11_complete_ast_v1/predictions/public/public01.json.gz')
        control={'paper_exactly_matches_frozen_dev10':True,'dev11_exactly_matches_frozen_dev11':True}
    result.update(id=item['id'], status='static_inference_complete_unscored',
        input_sha256=sha(source), view_receipt=receipt, summaries=summaries,
        original_loader_formula_mapping_equal=True, control=control,
        declaration_count=len(result['formula_declarations']),formula_count=len(formula_labels),
        declarations_absent_from_prediction=sorted(set(result['formula_declarations'])-formula_labels),
        wall_seconds=time.perf_counter()-t,cpu_seconds=time.process_time()-c,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        original_pipeline_envelope='SG rejects original xlsm suffix' if source.suffix=='.xlsm' else 'xlsx control',
        labels_read=[],precision=None,coverage=None,gpu_used=False,
        final_validation_eligible=False)
    return result


def verify():
    lock=read(RUN/'prediction_lock.json')
    assert sha(RUN/'source_lock.json')==lock['source_lock_sha256']
    for rel,h in read(RUN/'source_lock.json')['files'].items():assert sha(ROOT/rel)==h,rel
    for rel,h in lock['files'].items():assert sha(RUN/rel)==h,rel
    for rel,h in lock['inputs'].items():assert sha(REPO/rel)==h,rel
    return lock


def launch(item, view):
    command=[sys.executable,str(Path(__file__)),'worker','--item',json.dumps(item),'--view',str(view)]
    try:
        p=subprocess.run(command,capture_output=True,text=True,timeout=180)
        if p.returncode==0:return json.loads(p.stdout)
        return {'id':item['id'],'status':'worker_failed','returncode':p.returncode,'stderr':p.stderr}
    except subprocess.TimeoutExpired:
        return {'id':item['id'],'status':'timeout','timeout_seconds':180}


def predict():
    if RUN.exists():raise SystemExit('Preserve prior run; use a new version')
    items=[x for x in read(ROOT/'development/public_candidate_pipeline_dev10/public_index.json')
           if x['id'] in ['public01','public05','public06','public07']]
    assert len(items)==4
    sources=[Path(__file__),ROOT/'scripts/static_ooxml_view_dev1.py',ROOT/'STATIC_VIEW_DEV1_PLAN_20261018.md']
    sources+=sorted((ROOT/'scripts').glob('*.py'))+sorted((ROOT/'tests').glob('*.py'))
    sources+=sorted((BASE/'source').rglob('*.py'))+[BASE/'scripts/predict.py']
    save(RUN/'source_lock.json',{'version':VERSION,'files':{str(p.relative_to(ROOT)):sha(p) for p in sources}})
    save(RUN/'public_index.json',items)
    files={};start=time.perf_counter();cpu=time.process_time()
    for item in items:
        assert sha(REPO/item['relative_path'])==item['sha256']
        result=launch(item,RUN/'views'/(item['id']+'.xlsx'))
        path=RUN/'predictions'/(item['id']+'.json.gz');save(path,result)
        files[str(path.relative_to(RUN))]=sha(path)
        print(item['id'],result['status'],result.get('formula_count'),result.get('summaries'),result.get('error'),flush=True)
    for p in (RUN/'views').glob('*.xlsx'):files[str(p.relative_to(RUN))]=sha(p)
    save(RUN/'runtime.json',{'wall_seconds':time.perf_counter()-start,'parent_cpu_seconds':time.process_time()-cpu,
                            'python':platform.python_version(),'gpu_used':False,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            'scope':'static view, complete SG/FG/paper/dev11 and control checks; worker costs in predictions'})
    for p in [RUN/'public_index.json',RUN/'runtime.json']:files[str(p.relative_to(RUN))]=sha(p)
    save(RUN/'prediction_lock.json',{'source_lock_sha256':sha(RUN/'source_lock.json'),
         'files':files,'inputs':{x['relative_path']:x['sha256'] for x in items},
         'role':'revealed development compatibility only','labels_read':[],'final_validation_eligible':False})


def replay():
    verify();cases=[]
    for item in read(RUN/'public_index.json'):
        with tempfile.TemporaryDirectory(prefix='hybridguard-static-replay-') as temp:
            result=launch(item,Path(temp)/'view.xlsx')
        old=read(RUN/'predictions'/(item['id']+'.json.gz'))
        for row in [result,old]:
            for key in ['wall_seconds','cpu_seconds','peak_rss_kib']:row.pop(key,None)
        assert result==old,item['id']
        cases.append({'id':item['id'],'status':result['status'],'deterministic_fields_replayed_exactly':True})
        print('REPLAY',item['id'],result['status'],flush=True)
    save(ROOT/'qa/STATIC_VIEW_DEV1_REPLAY_20261018.json',{'cases':cases,'view_and_predictions_replayed':True,
          'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),'final_validation_eligible':False})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['predict','worker','verify','replay'])
    p.add_argument('--item');p.add_argument('--view');a=p.parse_args()
    if a.stage=='worker':print(json.dumps(worker(json.loads(a.item),Path(a.view)),ensure_ascii=False))
    else:{'predict':predict,'verify':verify,'replay':replay}[a.stage]()
