"""Run frozen models on the excluded natural-error original before author diff."""
from pathlib import Path
import argparse
import collections
import hashlib
import importlib.util
import json
import os
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'development/natural_hobyah_dev26_v1'
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read, save, sha


def source_files():
    paths = [Path(__file__), ROOT / 'HOBYAH_NATURAL_DEV26_PREREGISTRATION_20261018.md',
             ROOT / 'baseline/scripts/predict.py']
    paths += [ROOT / 'scripts' / ('selector_dev' + str(n) + '.py') for n in [2, 3, 4, 5, 6, 11]]
    paths += sorted((ROOT / 'baseline/source').rglob('*.py'))
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def worker():
    accesses = set()
    original = RUN / 'raw/before.xlsx'
    def guard(event, args):
        if event != 'open' or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        name = os.fsdecode(args[0]); low = name.lower()
        if any(x in low for x in ['after.xlsx', 'acquisition.json', 'historical_fix_', 'hobyah_docs_',
                                  'truth', 'score.json', 'author_diff', 'lineage', 'label']):
            raise PermissionError('Natural original inference cannot read correction evidence: ' + name)
        if str(RUN) in name:
            assert Path(name).resolve() == original.resolve(), name
            accesses.add(name)
    sys.addaudithook(guard)
    from formulaguard.workbook import WorkbookModel
    from formulaguard.v5_structural_guard import v5_structural_guard_scores
    from structuralguard.detector import analyze_workbook
    from selector_dev2 import select
    from selector_dev4 import review_guard
    from selector_dev6 import augment
    from selector_dev11 import qualify
    start = time.perf_counter(); cpu = time.process_time()
    model = WorkbookModel.from_xlsx(original)
    observed = {s + '!' + a: v for (s, a), v in model.formulas.items()}
    structural = analyze_workbook(original)['results']
    fg = [dict(rank=n, cell=v.cell_label, score=v.score, candidate_formula=v.candidate_formula,
               evidence=v.evidence) for n, v in enumerate(v5_structural_guard_scores(model), 1)]
    spec = importlib.util.spec_from_file_location('paper_adapter_dev26', ROOT / 'baseline/scripts/predict.py')
    adapter = importlib.util.module_from_spec(spec); spec.loader.exec_module(adapter)
    paper = adapter.hybrid((model, structural, fg, observed, []), {})
    dev11 = qualify(model, augment(model, review_guard(model, select(model, paper, fg, structural, [])), []))
    assert observed == {s + '!' + a: v for (s, a), v in model.formulas.items()}
    result = dict(status='complete', paper=paper, dev11=dev11, observed=observed,
                  formula_cells=len(observed), parallel_sheets=[], labels_read=[], correction_versions_read=[],
                  input_accesses=sorted(accesses), wall_seconds=time.perf_counter() - start,
                  cpu_seconds=time.process_time() - cpu, peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))


def run_worker():
    start = time.perf_counter()
    try:
        proc = subprocess.run([sys.executable, str(Path(__file__)), 'worker'], capture_output=True,
                              text=True, timeout=180, env=dict(os.environ, OMP_NUM_THREADS='4', OPENBLAS_NUM_THREADS='1'))
        if proc.returncode:
            return dict(status='failed', returncode=proc.returncode, stdout=proc.stdout,
                        stderr=proc.stderr, wall_seconds=time.perf_counter()-start)
        result = json.loads(proc.stdout)
        result['stderr'] = proc.stderr
        return result
    except subprocess.TimeoutExpired as error:
        return dict(status='timeout', seconds=180, stdout=str(error.stdout), stderr=str(error.stderr),
                    wall_seconds=time.perf_counter()-start)


def predict():
    assert not (RUN / 'prediction_lock.json').exists() and not (RUN / 'prediction.json.gz').exists()
    for rel, digest in read(ROOT / 'baseline/protocol/source_lock.json')['files'].items():
        assert sha(ROOT / 'baseline' / rel) == digest, rel
    acquisition = read(RUN / 'acquisition.json')
    assert all(r['ok'] for r in acquisition['records'])
    for row in acquisition['records']:
        assert sha(ROOT / row['path']) == row['sha256']
    save(RUN / 'source_lock.json', dict(files=source_files()))
    result = run_worker()
    save(RUN / 'prediction.json.gz', result)
    save(RUN / 'prediction_lock.json', dict(source_lock_sha256=sha(RUN / 'source_lock.json'),
         input_sha256=sha(RUN / 'raw/before.xlsx'), acquisition_sha256=sha(RUN / 'acquisition.json'),
         files={'prediction.json.gz': sha(RUN / 'prediction.json.gz')},
         status=result['status'], final_validation_eligible=False,
         prior_author_metadata_truth_exposure=True))
    print('DEV26 PREDICTION LOCKED', result['status'], result.get('formula_cells'), flush=True)


def verify():
    lock = read(RUN / 'prediction_lock.json')
    assert lock['source_lock_sha256'] == sha(RUN / 'source_lock.json')
    for rel, digest in read(RUN / 'source_lock.json')['files'].items():
        assert sha(ROOT / rel) == digest, rel
    for rel, digest in lock['files'].items():
        assert sha(RUN / rel) == digest
    assert sha(RUN / 'raw/before.xlsx') == lock['input_sha256']
    assert sha(RUN / 'acquisition.json') == lock['acquisition_sha256']


def replay():
    verify(); assert not (RUN / 'replay.json').exists()
    old = read(RUN / 'prediction.json.gz'); new = run_worker()
    assert old['status'] == new['status']
    keys = ['paper', 'dev11', 'observed', 'formula_cells', 'parallel_sheets', 'labels_read',
            'correction_versions_read', 'input_accesses'] if old['status'] == 'complete' else ['status', 'returncode', 'stderr']
    for key in keys:
        assert old.get(key) == new.get(key), key
    save(RUN / 'replay.json', dict(all_predictions_identical=True, status=new['status'],
         prediction_lock_sha256=sha(RUN / 'prediction_lock.json'), final_validation_eligible=False))
    print('DEV26 ORIGINAL REPLAY IDENTICAL', new['status'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['worker', 'predict', 'replay', 'verify'])
    globals()[parser.parse_args().mode]()
