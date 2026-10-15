"""Acquire and audit all 14 Pycel example/test XLSX files at a pinned commit.

Public software fixtures, not a representative business corpus or a natural
error dataset. No repair accuracy is inferred without authoritative labels.
This entire origin is permanently excluded from final validation.
"""
from collections import Counter
from pathlib import Path
import argparse
import concurrent.futures
import datetime
import gzip
import hashlib
import importlib.util
import json
import math
import platform
import resource
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'baseline'
RUN = ROOT / 'development/public_pycel_dev1'
COMMIT = '15c8dd17338eb2ec31c9fe9dab11ae7b77b2633b'
PREFIX = f'https://raw.githubusercontent.com/dgorissen/pycel/{COMMIT}/'
FILES = ['example/example.xlsx'] + ['tests/fixtures/'+name+'.xlsx' for name in
    ['basic','circular','cond-format','date-time','excelcompiler','information','logical',
     'lookup','npv','pv','stats','text','yearfrac']]
sys.path.insert(0,str(BASE / 'source/HybridGuard_V5_handoff_20260904/src'))
from run_selector_dev5 import read, save, sha, verify_run
from formulaguard.workbook import WorkbookModel
from formulaguard.v5_structural_guard import v5_structural_guard_scores
from structuralguard.detector import analyze_workbook
from structuralguard.formula import profile_formula
from selector_dev2 import select
from selector_dev4 import review_guard
from selector_dev5 import augment


def fetch(relative):
    url = PREFIX + relative
    receipt = {'source_path':relative,'url':url,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        with urllib.request.urlopen(urllib.request.Request(url,
                headers={'User-Agent':'HybridGuard-public-development-audit/1.0'}),timeout=20) as response:
            body = response.read(2_000_001)
            assert len(body) <= 2_000_000
            receipt.update(status=response.status,final_url=response.url,bytes=len(body),
                           sha256=hashlib.sha256(body).hexdigest(),ok=True)
        target = RUN / 'raw' / relative
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
        receipt['local_path']=str(target.relative_to(RUN))
    except Exception as error: receipt.update(ok=False,error=repr(error))
    return receipt


def acquire():
    if RUN.exists():raise SystemExit('Preserve public-development receipts')
    # Commit acquisition scope and exclusion BEFORE downloading any workbook.
    save(RUN / 'registration.json',{'role':'revealed public software-fixture development audit',
        'origin':'dgorissen/pycel and upstream fixture contributors, conservatively one excluded group',
        'commit':COMMIT,'selected_files':FILES,'selection':'all XLSX files in pinned repository tree; no score-based filtering',
        'final_validation_eligible':False,'new_final_sources':0,'new_final_families':0,
        'license':'repository GPL-3.0; per-fixture third-party ancestry not fully audited; raw files not uploaded',
        'labels':'no authoritative clean/error cell labels; cached values are compatibility references only',
        'parallel_sheet_policy':'none declared; never assume sheets are parallel by file membership',
        'method':'full original SG/FG paper inference and dev4/dev5; score no precision or coverage',
        'failure_policy':'retain all failed downloads, parsing failures and unsupported functions in audit',
        'dev5_prediction_lock_sha256':sha(ROOT / 'development/selector_dev5/prediction_lock.json')})
    (RUN / '.gitignore').write_text('raw/\n')
    receipt = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(fetch,['LICENSE.txt','README.rst',*FILES]):
            receipt.append(result);print(result['source_path'],result['ok'],result.get('error',''),flush=True)
    save(RUN / 'acquisition_receipt.json',{'commit':COMMIT,'records':receipt,
        'role':'development acquisition only; origin excluded from final validation'})


def audit():
    if (RUN / 'prediction_lock.json').exists(): raise SystemExit('Preserve audit evidence')
    verify_run()
    sources = [Path(__file__), BASE / 'scripts/predict.py',ROOT / 'scripts/run_selector_dev5.py',
        ROOT / 'scripts/selector_dev5.py',ROOT / 'scripts/selector_dev4.py',
        ROOT / 'scripts/selector_dev3.py',ROOT / 'scripts/selector_dev2.py']
    sources += sorted((BASE / 'source').rglob('*.py'))
    save(RUN / 'source_lock.json',{'files':{str(p.relative_to(ROOT)):sha(p) for p in sources}})
    spec = importlib.util.spec_from_file_location('public_dev_paper_adapter',BASE / 'scripts/predict.py')
    adapter = importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
    receipts = {r['source_path']:r for r in read(RUN / 'acquisition_receipt.json')['records']}
    files = {}; reports = []
    # Cached outputs are read only after inference; they never authorize repairs.
    for i, relative in enumerate(FILES,1):
        case = f'public{i:02d}';path=RUN / 'raw' / relative
        report = {'id':case,'source_path':relative,'parallel_sheets':[],
                  'precision':None,'coverage':None,'labels_available':False}
        receipt=receipts[relative]
        if not receipt['ok']:
            report.update(status='acquisition_failed',error=receipt.get('error'))
            reports.append(report);continue
        assert sha(path)==receipt['sha256']
        start, cpu = time.perf_counter(),time.process_time()
        try:
            model = WorkbookModel.from_xlsx(path)
            observed = {s+'!'+a:f for (s,a),f in model.formulas.items()}
            report['formula_cells'] = len(observed)
            functions = Counter(); profile_failures = []
            for (sheet,address), formula in model.formulas.items():
                try:
                    functions.update(profile_formula(formula,address,sheet).functions)
                except Exception as error:
                    profile_failures.append({'cell':sheet+'!'+address,'formula':formula,'error':repr(error)})
            report.update(functions=dict(functions),profile_failures=profile_failures)
            structural = analyze_workbook(path)['results']
            fg = [{'rank':rank,'cell':v.cell_label,'score':v.score,
                'candidate_formula':v.candidate_formula,'evidence':v.evidence}
                for rank,v in enumerate(v5_structural_guard_scores(model),1)]
            paper = adapter.hybrid((model,structural,fg,observed,[]),{})
            dev4 = review_guard(model,select(model,paper,fg,structural,[]))
            dev5 = augment(model,dev4,[])
            assert observed == {s+'!'+a:f for (s,a),f in model.formulas.items()}
            predictions = {'observed_formulas':observed,'paper':paper,'dev4':dev4,'dev5':dev5}
            target = RUN / 'predictions' / (case+'.json.gz')
            save(target,predictions);files[str(target.relative_to(RUN))]=sha(target)
            report['change_suggestions'] = {name:[{'cell':r['cell'],'formula':r['suggested_formula']}
                for r in pred['rows'] if r.get('suggested_formula')
                and r['suggested_formula'] != observed[r['cell']]
                and (name=='paper' or r['status']=='propose')]
                for name,pred in [('paper',paper),('dev4',dev4),('dev5',dev5)]}
            report['status']='inference_complete_unscored'
            values, errors = model.evaluate()
            report['evaluation_errors'] = {s+'!'+a:str(value) for (s,a),value in errors.items()}
            report['evaluated_without_error'] = len(observed)-len(errors)
            # Excel caches can be stale and fixtures deliberately include errors.
            # Record agreements/disagreements as diagnostics, never clean labels.
            from openpyxl import load_workbook
            cached = load_workbook(path,data_only=True,read_only=True)
            comparisons=[]
            for key, formula in model.formulas.items():
                sheet,address=key;reference=cached[sheet][address].value;actual=values.get(key)
                if (isinstance(reference,(int,float)) and not isinstance(reference,bool)
                        and isinstance(actual,(int,float)) and not isinstance(actual,bool)
                        and math.isfinite(reference) and math.isfinite(actual)):
                    comparisons.append({'cell':sheet+'!'+address,'reference_cache':reference,'actual':actual,
                        'numeric_agreement':math.isclose(actual,reference,rel_tol=1e-8,abs_tol=1e-8)})
            cached.close()
            report['cache_comparisons']=comparisons
            report['cache_caveat']='stale caches, date serials and deliberate test errors possible; no correctness ground truth'
        except Exception as error:
            report.update(status='inference_or_audit_failed',error=repr(error))
        report.update(wall_seconds=time.perf_counter()-start,cpu_seconds=time.process_time()-cpu,
                      cumulative_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        reports.append(report)
        print(case,relative,report['status'],report.get('formula_cells'),report.get('error',''),flush=True)
    report={'cases':reports,'case_count':len(FILES),'role':'public software fixtures compatibility development only',
        'command':[sys.executable,*sys.argv],'python':platform.python_version(),
        'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'precision':None,'coverage':None,
        'interpretation':'No authoritative business repair labels. Never interpret an unscored suggestion as a verified error.',
        'status_counts':dict(Counter(r['status'] for r in reports)),
        'new_final_sources':0,'new_final_families':0}
    save(RUN / 'audit.json',report);files['audit.json']=sha(RUN / 'audit.json')
    save(RUN / 'prediction_lock.json',{'files':files,
        'source_lock_sha256':sha(RUN / 'source_lock.json'),
        'acquisition_receipt_sha256':sha(RUN / 'acquisition_receipt.json'),
        'registration_sha256':sha(RUN / 'registration.json'),
        'inputs':{str((RUN / 'raw' / p).relative_to(RUN)):receipts[p]['sha256'] for p in FILES if receipts[p]['ok']},
        'labels_available':False,'role':'unscored public-development inference audit'})
    print(json.dumps(report['status_counts']))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['acquire','audit'])
    args=parser.parse_args();{'acquire':acquire,'audit':audit}[args.stage]()
