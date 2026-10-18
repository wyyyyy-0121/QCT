"""Unchanged paper/dev11 inference on the newly excluded Weights original."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'qa')]
import run_hobyah_natural_dev26 as engine

RUN = ROOT / 'development/natural_weights_dev33_v1'
engine.RUN = RUN
original_sources = engine.source_files


def sources():
    files = original_sources()
    for path in [Path(__file__), ROOT / 'WEIGHTS_NATURAL_DEV33_PREREGISTRATION_20261018.md']:
        files[str(path.relative_to(ROOT))] = engine.sha(path)
    return files


def run_worker():
    started = time.perf_counter()
    try:
        process = subprocess.run([sys.executable, str(Path(__file__)), 'worker'],
             capture_output=True, text=True, timeout=180,
             env=dict(os.environ, OMP_NUM_THREADS='4', OPENBLAS_NUM_THREADS='1'))
        if process.returncode:
            return dict(status='failed', returncode=process.returncode, stdout=process.stdout,
                        stderr=process.stderr, wall_seconds=time.perf_counter() - started)
        result = json.loads(process.stdout); result['stderr'] = process.stderr
        return result
    except subprocess.TimeoutExpired as error:
        return dict(status='timeout', seconds=180, stdout=str(error.stdout), stderr=str(error.stderr),
                    wall_seconds=time.perf_counter() - started)


engine.source_files = sources
engine.run_worker = run_worker

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['worker', 'predict', 'replay', 'verify'])
    getattr(engine, parser.parse_args().mode)()
