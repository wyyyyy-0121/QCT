"""Lock development predictions before scoring, preserving all old evidence."""
from pathlib import Path
import argparse
import datetime
import gzip
import hashlib
import importlib.util
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'baseline'
RUN = ROOT/'development/selector_dev2'
sys.path.insert(0,str(BASE/'source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
from selector_dev2 import select, VERSION, PARAMETERS


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    if path.suffix=='.gz':
        with gzip.open(path,'rt') as f: return json.load(f)
    return json.loads(path.read_text())


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')


def predict():
    if RUN.exists(): raise SystemExit('Refusing to overwrite dev2 evidence')
    for name in ['source_lock.json','prediction_lock.json']:
        for relative,expected in read(BASE/'protocol'/name)['files'].items():
            assert sha(BASE/relative)==expected,relative
    sources=[Path(__file__),ROOT/'scripts/selector_dev2.py',BASE/'scripts/score.py']+sorted((BASE/'source').rglob('*.py'))
    save(RUN/'source_lock.json',{'version':VERSION,'parameters':PARAMETERS,
        'files':{str(p.relative_to(ROOT)):sha(p) for p in sources}})
    accesses=set()
    def guard(event,args):
        if event=='open' and isinstance(args[0],(str,bytes)):
            name=str(args[0])
            if any(x in name.lower() for x in ['truth.json','/results/','/score','failure_audit','data_manifest.json']):
                raise PermissionError('Prediction cannot access label/scoring evidence: '+name)
            if str(BASE) in name: accesses.add(name)
    sys.addaudithook(guard)
    entries=read(BASE/'protocol/public_index.json')
    for entry in entries:
        case=entry['id'];start=time.perf_counter();directory=BASE/'predictions'/case
        model=WorkbookModel.from_xlsx(BASE/'data'/case/'input.xlsx')
        before=dict(model.formulas)
        pred=select(model,read(directory/'full.json.gz'),read(directory/'fg.json.gz')['rows'],
                    read(directory/'sg.json.gz')['rows'],read(BASE/'data'/case/'public.json')['parallel_sheets'])
        assert model.formulas==before
        pred.update(case=case,seconds=time.perf_counter()-start)
        path=RUN/'predictions'/(case+'.json.gz');path.parent.mkdir(parents=True,exist_ok=True)
        with gzip.GzipFile(filename=str(path),mode='wb',mtime=0) as f:
            f.write(json.dumps(pred,ensure_ascii=False,sort_keys=True).encode())
        print(case, 'propose',sum(r['status']=='propose' for r in pred['rows']),flush=True)
    files=sorted((RUN/'predictions').glob('*.gz'));assert len(files)==len(entries)
    save(RUN/'prediction_lock.json',{'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'role':'revealed development only','labels_read':[],
        'source_lock_sha256':sha(RUN/'source_lock.json'),
        'baseline_prediction_lock_sha256':sha(BASE/'protocol/prediction_lock.json'),
        'baseline_accesses':sorted(accesses),
        'files':{str(p.relative_to(RUN)):sha(p) for p in files}})


def score():
    lock=read(RUN/'prediction_lock.json')
    assert sha(RUN/'source_lock.json')==lock['source_lock_sha256']
    for relative,expected in lock['files'].items():assert sha(RUN/relative)==expected
    for relative,expected in read(RUN/'source_lock.json')['files'].items():assert sha(ROOT/relative)==expected
    spec=importlib.util.spec_from_file_location('frozen_paper_scorer',BASE/'scripts/score.py')
    scorer=importlib.util.module_from_spec(spec);spec.loader.exec_module(scorer)
    cases=[]
    for entry in read(BASE/'protocol/data_manifest.json'):
        case=entry['id'];pred=read(RUN/'predictions'/(case+'.json.gz'))
        pred['rows']=[{**r,'candidate_formula':None,
            'suggested_formula':r.get('suggested_formula') if r['status']=='propose' else None} for r in pred['rows']]
        metrics=scorer.evaluate(pred,read(BASE/'predictions'/case/'input_formulas.json.gz'),read(BASE/'data'/case/'truth.json'))
        cases.append({'case':case,'family':entry['family'],**metrics})
    def aggregate(rows):
        p=sum(x['proposals'] for x in rows);c=sum(x['exact_repairs'] for x in rows);e=sum(x['errors'] for x in rows)
        return {'proposals':p,'correct':c,'errors':e,'precision':c/p if p else None,
                'coverage':c/e if e else None,'harmful_correct_cells':sum(x['harmful_correct_cells'] for x in rows)}
    families={f:aggregate([x for x in cases if x['family']==f]) for f in sorted({x['family'] for x in cases})}
    report={'role':'revealed development only; not final validation','totals':aggregate(cases),
            'families':families,'cases':cases,'prediction_lock_sha256':sha(RUN/'prediction_lock.json')}
    save(RUN/'score.json',report)
    print(json.dumps({'totals':report['totals'],'families':families},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['predict','score']);args=p.parse_args()
    predict() if args.stage=='predict' else score()
