#!/usr/bin/env python3
"""Lock and run actual-paper natural candidate observations after M9 rejection."""
import argparse
from pathlib import Path
import subprocess
import sys

from experiment_natural_m9 import ROOT, EVIDENCE, RUNNER, read, write, verify_context, verify_files
from spreadsheetbench2_scoring import sha256

EXPERIMENT = EVIDENCE/'natural_mechanism'
NATURAL = EVIDENCE/'model_m9_natural'


def prepare():
    verify_context()
    old_lock, old_output = read(NATURAL/'input_lock.json'), read(NATURAL/'output_lock.json')
    verify_files(old_lock)
    if old_output['input_lock_sha256'] != sha256(NATURAL/'input_lock.json'):
        raise SystemExit('M9 lock chain changed')
    for item in old_output['outputs']:
        if item['status'] != 'complete' or sha256(Path(item['path'])) != item['sha256']:
            raise SystemExit('M9 source outputs changed')
    cases = {k:v for k,v in read(NATURAL/'scoring/expected.json').items()
             if v['group'] in {'natural_errors','corrected_controls','range_candidates'}}
    if len(cases) != 7:
        raise SystemExit('Natural observation scope changed')
    rows, files = [], [NATURAL/'input_lock.json',NATURAL/'output_lock.json',NATURAL/'runs/runtime.json',
                      NATURAL/'scoring/expected.json',ROOT/'NATURAL_MECHANISM_PLAN.md',RUNNER,
                      Path(__file__),ROOT/'tools/trace_natural_mechanism.py',ROOT/'tools/trace_paper_candidates.py',
                      ROOT/'tools/score_natural_mechanism.py',ROOT/'tools/score_paper_candidate_trace.py',
                      ROOT/'tools/experiment_natural_m9.py',ROOT/'tools/spreadsheetbench2_scoring.py']
    for name,case in cases.items():
        files += [Path(case['workbook']),Path(next(r['path'] for r in old_output['outputs'] if r['id']==name))]
        rows.append(dict(id=name,argv=[sys.executable,str(ROOT/'tools/trace_natural_mechanism.py'),
                                      '--input',case['workbook'],'--output','trace.json.gz'],
                         outputs=['trace.json.gz'],timeout_seconds=900))
    hashes={str(p):sha256(p) for p in files}
    EXPERIMENT.mkdir(exist_ok=False)
    manifest=EXPERIMENT/'manifest.jsonl'
    import json
    with manifest.open('x') as handle:
        handle.write(''.join(json.dumps(row)+'\n' for row in rows))
    hashes[str(manifest)]=sha256(manifest)
    write(EXPERIMENT/'input_lock.json',dict(files_sha256=hashes,task_ids=sorted(cases),requested_workers=20,
                                           final_validation_eligible=False))
    print('NATURAL OBSERVATION INPUTS LOCKED',len(rows))


def run():
    verify_context()
    lock_path=EXPERIMENT/'input_lock.json'
    lock=read(lock_path)
    verify_files(lock)
    if (EXPERIMENT/'runs').exists() or (EXPERIMENT/'output_lock.json').exists():
        raise SystemExit('Preserve existing observation run')
    subprocess.run([sys.executable,str(RUNNER),'--manifest',str(EXPERIMENT/'manifest.jsonl'),
                    '--output-dir',str(EXPERIMENT/'runs'),'--workers','20','--worker-memory-mib','475',
                    '--timeout','900'],cwd=ROOT,check=False)
    runtime=read(EXPERIMENT/'runs/runtime.json')
    verify_files(lock)
    verify_context()
    if len(runtime['tasks'])!=7 or runtime['requested_worker_count']!=20:
        raise SystemExit('Observation task/worker accounting changed')
    outputs=[]
    for task in runtime['tasks']:
        path=Path(task['cwd'])/'trace.json.gz'
        if task['status']=='complete' and sha256(path)!=task['output_sha256']['trace.json.gz']:
            raise SystemExit('Trace changed')
        outputs.append(dict(id=task['id'],status=task['status'],path=str(path) if path.exists() else None,
                            sha256=sha256(path) if path.exists() else None))
    write(EXPERIMENT/'output_lock.json',dict(input_lock_sha256=sha256(lock_path),
          runtime_sha256=sha256(EXPERIMENT/'runs/runtime.json'),outputs=outputs,scoring_may_begin=True))
    print('NATURAL OBSERVATION OUTPUTS LOCKED',len(outputs))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('prepare','run'))
    (prepare if parser.parse_args().stage=='prepare' else run)()
