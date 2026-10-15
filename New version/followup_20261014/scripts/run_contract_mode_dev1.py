"""Run auxiliary declared-contract mode on explicit files; no scoring access."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import platform
import resource
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
from contract_mode_dev1 import apply_contract, load_contract
from run_selector_dev5 import read


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    for name in ('input','upstream','contract','output'):parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--prediction-key')
    args=parser.parse_args()
    inputs=[args.input.resolve(),args.upstream.resolve(),args.contract.resolve()]
    target=args.output.resolve()
    if target.exists() or target in inputs:raise SystemExit('Preserve existing files; choose a new output')
    accesses=set()
    def guard(event,values):
        if event=='open' and isinstance(values[0],(str,bytes)):
            text=str(values[0]);lower=text.casefold()
            if any(v in lower for v in ['truth.json','registration.json','data_manifest.json',
                                       '/score','input_oracle','mutation_log']):
                raise PermissionError('Contract inference denies scoring evidence: '+text)
            if str(ROOT) in text:accesses.add(text)
    sys.addaudithook(guard)
    start=time.perf_counter();before={str(p):sha(p) for p in inputs}
    contract,contract_hash=load_contract(args.contract)
    observed=WorkbookModel.from_xlsx(args.input)
    prior=read(args.upstream)
    if args.prediction_key:prior=prior[args.prediction_key]
    before_formulas=dict(observed.formulas)
    result=apply_contract(observed,prior,contract,before[str(args.input.resolve())],contract_hash)
    assert observed.formulas==before_formulas
    assert before=={str(p):sha(p) for p in inputs}
    sources=[Path(__file__),ROOT/'scripts/contract_mode_dev1.py',ROOT/'scripts/formula_candidates_dev1.py',
             ROOT/'scripts/run_selector_dev5.py',ROOT/'scripts/selector_dev5.py',
             ROOT/'scripts/selector_dev3.py',ROOT/'scripts/selector_dev2.py']
    sources+=sorted((ROOT/'baseline/source').rglob('*.py'))
    result['execution_receipt']={
        'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'command':[sys.executable,*sys.argv], 'inputs_sha256':before,
        'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in sources},
        'wall_seconds':time.perf_counter()-start,
        'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'python':platform.python_version(),'platform':platform.platform(),
        'labels_read':[], 'accesses':sorted(accesses),'input_files_unchanged':True}
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x') as handle:json.dump(result,handle,indent=2,ensure_ascii=False,allow_nan=False);handle.write('\n')
    print('Wrote',target,'rows',len(result['rows']),'main_acceptance_eligible',False)


if __name__=='__main__':main()
