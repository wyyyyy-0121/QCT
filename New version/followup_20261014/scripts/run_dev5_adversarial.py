"""Counterexamples for frozen dev5, not final or prevalence-representative data.

Four already revealed families, six variants each. Several expose information
insufficiency using an external business contract deliberately absent from the
input. Their scores must not be pooled as a real-world accuracy estimate.
"""
from pathlib import Path
import argparse
import importlib.util
import json
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'baseline'
RUN = ROOT / 'development/dev5_adversarial1'
sys.path.insert(0,str(BASE / 'source/HybridGuard_V5_handoff_20260904/src'))
from run_crossdomain_dev import build_case, corrupt_formula, FAMILIES
from run_selector_dev5 import sha, save, read, verify_files, verify_run, metrics, total
from selector_dev5 import augment
from selector_dev2 import select
from selector_dev4 import review_guard
from formulaguard.workbook import WorkbookModel
from formulaguard.v5_structural_guard import v5_structural_guard_scores
from structuralguard.detector import analyze_workbook

VARIANTS = ['unmarked_reversed_role','all_peers_corrupted','unknown_output_label',
            'peer_unit_mismatch','multiline_scope_conflict','row_exception_and_error']


def prepare():
    if RUN.exists(): raise SystemExit('Preserve adversarial evidence')
    # dev5 source and predictions must already be frozen before creating inputs.
    verify_run()
    save(RUN / 'registration.json', {'role':'revealed adversarial development only',
        'families':FAMILIES,'variants':VARIANTS,'cases':24,'new_final_families':0,
        'dev5_prediction_lock_sha256':sha(ROOT / 'development/selector_dev5/prediction_lock.json'),
        'external_contract_cases':['unmarked_reversed_role','multiline_scope_conflict','row_exception_and_error'],
        'interpretation':'unmarked reversed role intentionally has the same visible formula and inputs as an error; no pooled acceptance accuracy',
        'oracle':'preserved Fraction-checked source fixture formulas plus explicit exact syntactic sign mutation; no claim of real natural errors'})
    public = []; truths = []
    for fi, family in enumerate(FAMILIES,1):
        for vi, variant in enumerate(VARIANTS,1):
            case = f'a{fi}{vi}'
            seed_variant = ('whole_column_error' if variant in ['all_peers_corrupted','peer_unit_mismatch','multiline_scope_conflict']
                            else 'exception_and_error' if variant=='row_exception_and_error' else 'sparse_error')
            book, expected, _, _ = build_case(family,seed_variant)
            contract = None
            if variant == 'unmarked_reversed_role':
                expected['A!F16'] = book['A']['F16'].value
                contract = 'External authorized row-16 convention intentionally reverses the tested role; contract not included in input. Visible input matches this family sparse_error development case.'
            elif variant == 'all_peers_corrupted':
                for ws in book:
                    for row in range(2,26): ws[f'F{row}'] = corrupt_formula(family,row)
            elif variant == 'unknown_output_label':
                for ws in book: ws['F1']='Result (organization-specific)'
            elif variant == 'peer_unit_mismatch':
                for sheet in 'BCDE': book[sheet]['F1'] = 'Result [different unit system]'
            elif variant == 'multiline_scope_conflict':
                book['A']['H1']='Business policy'
                book['A']['H2']='Row 10: use an exceptional calculation.'
                book['A']['H3']='All rows in this sheet use the opposite convention for the affected role.'
                for row in range(2,26): expected[f'A!F{row}']=book['A'][f'F{row}'].value
                contract = 'Second visible policy line authorizes opposite convention on the entire A sheet; first line alone is incomplete.'
            elif variant == 'row_exception_and_error':
                book['A']['F10']=corrupt_formula(family,10)
                expected['A!F10']=book['A']['F10'].value
                book['A']['H2']='Row 10: use the opposite convention for the affected role.'
                contract = 'Explicit visible row-10 exception is legitimate; row-16 remains an injected error.'
            path = RUN / 'inputs' / (case+'.xlsx')
            path.parent.mkdir(parents=True,exist_ok=True); book.save(path)
            model = WorkbookModel.from_xlsx(path)
            observed = {s+'!'+a:f for (s,a),f in model.formulas.items()}
            assert set(observed)==set(expected)
            _, failures = model.evaluate(); assert not failures, (case,failures)
            # The exception contracts specify exact formula targets; confirm all
            # targets are executable without claiming the formulas prove intent.
            _, failures = model.evaluate(overrides={tuple(k.rsplit('!',1)):v for k,v in expected.items()})
            assert not failures,(case,failures)
            errors = [k for k in expected if expected[k]!=observed[k]]
            public.append({'id':case,'input':str(path.relative_to(RUN)),'sha256':sha(path),
                           'parallel_sheets':['A','B','C','D','E']})
            truths.append({'id':case,'family':family,'scenario':variant,'external_contract':contract,
                'expected_formulas':expected,'errors':errors,
                'mutation_log':[{'cell':k,'before':expected[k],'after':observed[k]} for k in errors]})
    save(RUN / 'public_index.json',public)
    save(RUN / 'truth.json',{'cases':truths,'role':'revealed authored adversarial contracts; not natural errors'})
    print('Prepared',len(public),'adversarial cases after dev5 freeze')


def predict():
    if (RUN / 'predictions').exists(): raise SystemExit('Preserve predictions')
    verify_run()
    sources = [Path(__file__), BASE / 'scripts/predict.py', ROOT / 'scripts/run_crossdomain_dev.py',
        ROOT / 'scripts/run_selector_dev5.py', ROOT / 'scripts/selector_dev5.py',
        ROOT / 'scripts/selector_dev4.py', ROOT / 'scripts/selector_dev3.py',ROOT / 'scripts/selector_dev2.py']
    sources += sorted((BASE / 'source').rglob('*.py'))
    save(RUN / 'source_lock.json',{'files':{str(p.relative_to(ROOT)):sha(p) for p in sources}})
    spec = importlib.util.spec_from_file_location('adversarial_paper_adapter',BASE/'scripts/predict.py')
    adapter = importlib.util.module_from_spec(spec); spec.loader.exec_module(adapter)
    accesses = set()
    def guard(event,args):
        if event=='open' and isinstance(args[0],(str,bytes)):
            name = str(args[0])
            if any(word in name.casefold() for word in ['truth.json','registration.json','data_manifest.json',
                    '/score','/results/','failure_audit','mutation_log','input_oracle']):
                raise PermissionError('Prediction cannot read labels: '+name)
            if str(ROOT) in name: accesses.add(name)
    sys.addaudithook(guard)
    files = {}; timings = []
    for entry in read(RUN / 'public_index.json'):
        path = RUN / entry['input']; assert sha(path)==entry['sha256']
        wall, cpu = time.perf_counter(),time.process_time()
        model = WorkbookModel.from_xlsx(path); before = dict(model.formulas)
        structural = analyze_workbook(path)['results']
        fg = [{'rank':i,'cell':v.cell_label,'score':v.score,'candidate_formula':v.candidate_formula,
               'evidence':v.evidence} for i,v in enumerate(v5_structural_guard_scores(model),1)]
        observed = {s+'!'+a:v for (s,a),v in model.formulas.items()}
        paper = adapter.hybrid((model,structural,fg,observed,entry['parallel_sheets']),{})
        dev4 = review_guard(model,select(model,paper,fg,structural,entry['parallel_sheets']))
        dev5 = augment(model,dev4,entry['parallel_sheets'])
        assert model.formulas==before
        timing = {'id':entry['id'],'wall_seconds':time.perf_counter()-wall,
            'cpu_seconds':time.process_time()-cpu,
            'cumulative_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
        timings.append(timing)
        target = RUN / 'predictions' / (entry['id']+'.json.gz')
        save(target,{'paper':paper,'dev4':dev4,'dev5':dev5,'observed_formulas':observed,'timing':timing})
        files[str(target.relative_to(RUN))]=sha(target)
        print(entry['id'],'dev5 proposals',sum(r['status']=='propose' for r in dev5['rows']),flush=True)
    save(RUN / 'runtime.json',{'cases':timings,'command':[sys.executable,*sys.argv],
        'scope':'full paper SG/FG plus dev4 and dev5 inference on fresh inputs','gpu_used':False})
    files['runtime.json']=sha(RUN / 'runtime.json')
    save(RUN / 'prediction_lock.json',{'files':files,
        'source_lock_sha256':sha(RUN / 'source_lock.json'),
        'public_index_sha256':sha(RUN / 'public_index.json'),'labels_read':[],
        'accesses':sorted(accesses),'role':'adversarial development only'})


def score():
    if (RUN / 'score.json').exists(): raise SystemExit('Preserve scores')
    lock = read(RUN / 'prediction_lock.json')
    assert sha(RUN / 'source_lock.json')==lock['source_lock_sha256']
    assert sha(RUN / 'public_index.json')==lock['public_index_sha256']
    verify_files(ROOT,read(RUN / 'source_lock.json')['files']);verify_files(RUN,lock['files'])
    for entry in read(RUN / 'public_index.json'): assert sha(RUN / entry['input'])==entry['sha256']
    cases = []
    for truth in read(RUN / 'truth.json')['cases']:
        pred = read(RUN / 'predictions' / (truth['id']+'.json.gz'))
        result = {k:truth[k] for k in ['id','family','scenario','external_contract']}
        for name in ['paper','dev4','dev5']:
            if name=='paper':
                # Original adapter supplies candidate suggestions with legacy
                # statuses; every actual change suggestion counts for baseline.
                pred[name] = {**pred[name],'rows':[{**r,'status':'propose' if r.get('suggested_formula') else 'abstain'}
                                                   for r in pred[name]['rows']]}
            result[name]=metrics(pred[name],truth,pred['observed_formulas'])
        cases.append(result)
        print(truth['id'],truth['scenario'],'dev5',result['dev5']['correct'],result['dev5']['wrong'],flush=True)
    by_variant = {variant:{name:total([c for c in cases if c['scenario']==variant],name)
        for name in ['paper','dev4','dev5']} for variant in VARIANTS}
    save(RUN / 'score.json',{'cases':cases,'by_variant':by_variant,
        'pooled_acceptance_metric':False,'prediction_lock_sha256':sha(RUN / 'prediction_lock.json'),
        'interpretation':'purpose-built counterexamples; external intent not recoverable in unmarked cases; no realistic prevalence or final generalization claim'})
    print(json.dumps(by_variant,indent=2))


if __name__=='__main__':
    parser = argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','predict','score'])
    args=parser.parse_args();{'prepare':prepare,'predict':predict,'score':score}[args.stage]()
