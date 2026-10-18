"""Reuse the frozen natural-original worker with a separately locked LDAS run."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'qa')]
import run_hobyah_natural_dev26 as engine
RUN=ROOT/'development/natural_ldas_dev27_v1'
engine.RUN=RUN
original_sources=engine.source_files


def sources():
    files=original_sources()
    for path in [Path(__file__),ROOT/'LDAS_NATURAL_DEV27_PREREGISTRATION_20261018.md']:
        files[str(path.relative_to(ROOT))]=engine.sha(path)
    return files


def run_worker():
    start=time.perf_counter()
    try:
        p=subprocess.run([sys.executable,str(Path(__file__)),'worker'],capture_output=True,text=True,
                         timeout=180,env=dict(os.environ,OMP_NUM_THREADS='4',OPENBLAS_NUM_THREADS='1'))
        if p.returncode:return dict(status='failed',returncode=p.returncode,stdout=p.stdout,stderr=p.stderr,wall_seconds=time.perf_counter()-start)
        result=json.loads(p.stdout);result['stderr']=p.stderr;return result
    except subprocess.TimeoutExpired as error:
        return dict(status='timeout',seconds=180,stdout=str(error.stdout),stderr=str(error.stderr),wall_seconds=time.perf_counter()-start)


engine.source_files=sources
engine.run_worker=run_worker


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['worker','predict','replay','verify'])
    getattr(engine,p.parse_args().mode)()
