"""Certified preference experiment; prediction, scoring and replay are separate."""
from collections import Counter
from pathlib import Path
import argparse
import gc
import hashlib
import os
import platform
import resource
import sys
import tempfile
import time
import joblib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read, save, sha
from build_candidates_dev18 import compact, protection
from build_keep_features_dev21 import DATA as FEATURES, BASE, case_data, case_path
from prepare_certified_labels_dev22 import DATA as LABELS
from build_signed_features_dev19 import order_digest
from certified_matrix_dev22 import build_matrix
from run_candidate_learning_dev18 import training_protection, weights
from run_candidate_learning_dev16 import metrics, totals
from relative_learning_dev21 import PARAMETERS, THRESHOLD, MARGIN
from run_relative_learning_dev21 import infer
RUN = ROOT/'development/certified_learning_dev22_v1'
MODES = ['dev11', 'learned_only', 'keep_base_plus_learned', 'learned_unfiltered']


def verify_features():
    # Historical aggregate verifiers also hash old truth bodies. Verify the
    # identical observable inputs/features directly without traversing labels.
    for folder in [BASE, ROOT/'development/signed_features_dev19_v1',
                   ROOT/'development/unit_features_dev20_v1', FEATURES]:
        lock = read(folder/'feature_lock.json')
        for rel, value in lock['files'].items(): assert sha(folder/rel) == value, rel
        for field in ['sources', 'inputs']:
            for rel, value in lock.get(field, {}).items(): assert sha(ROOT/rel) == value, rel
        if 'base_feature_lock_sha256' in lock:
            assert sha(BASE/'feature_lock.json') == lock['base_feature_lock_sha256']
        if 'control_prediction_lock_sha256' in lock:
            assert sha(ROOT/'development/unit_learning_dev20_v1/prediction_lock.json') == lock['control_prediction_lock_sha256']
        assert lock['labels_read'] == []


def protect_preflight():
    active = [True]
    def guard(event, args):
        if active[0] and event == 'open' and isinstance(args[0], (str, bytes)):
            name = os.fsdecode(args[0])
            if any(part in name for part in ['/author_case_states/', '/author_case_pairs/',
                    '/training_labels/', '/case_labels/', '/heldout_truth', '/truth.json']):
                raise PermissionError('No label-body hashing or parsing in learner preflight')
    sys.addaudithook(guard)
    return active


def selection_digest(rows):
    return hashlib.sha256('\n'.join('\t'.join(str(r[k]) for k in
        ['case', 'cell', 'left_id', 'right_id', 'label']) for r in rows).encode()).hexdigest()


def verify_preparation(include_label_bodies=False):
    lock = read(LABELS/'preparation_lock.json')
    # The independent author audit verifies all bodies. A learner preflight
    # only binds the metadata locks; it must not even hash other-fold labels.
    names = lock['files'] if include_label_bodies else ['fold_index.json', 'state_counts.json']
    for rel in names: assert sha(LABELS/rel) == lock['files'][rel], rel
    for rel, value in lock['sources'].items(): assert sha(ROOT/rel) == value, rel
    assert sha(BASE/'label_preparation_lock.json') == lock['upstream_label_lock_sha256']
    assert sha(BASE/'fold_index.json') == lock['upstream_fold_index_sha256']
    assert sha(FEATURES/'feature_lock.json') == lock['feature_lock_sha256']


def fit(fold, index):
    path = LABELS/fold['train_label_file']; assert sha(path) == fold['train_label_sha256']
    labels = read(path); rows = labels['rows']
    assert labels['training_cases'] == fold['train_cases'] and labels['heldout_cases'] == fold['test_cases']
    assert not set(fold['train_cases']) & set(fold['test_cases'])
    assert all(r['case'] in fold['train_cases'] and r['source'] != fold['origin'] for r in rows)
    del labels
    y = np.asarray([r['label'] for r in rows], dtype=np.int8)
    w = weights(rows)
    assert np.array_equal(y[::2], np.ones(len(y)//2))
    assert np.array_equal(y[1::2], np.zeros(len(y)//2))
    assert np.array_equal(w[::2], w[1::2])
    sums = {source: float(w[[n for n, r in enumerate(rows) if r['source'] == source]].sum())
            for source in sorted({r['source'] for r in rows})}
    assert max(sums.values())-min(sums.values()) < 1e-5
    summary = dict(directed_pairs=len(rows), positive=int(y.sum()), negative=int((y == 0).sum()),
        source_weight_sums=sums, class_weight_sums=[float(w[y == v].sum()) for v in [0, 1]],
        selection_sha256=selection_digest(rows), features=2*read(FEATURES/'feature_schema.json')['base_width'])
    (ROOT/'tmp').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='dev22_', dir=ROOT/'tmp') as tmp:
        print('building certified matrix', fold['id'], len(rows), flush=True)
        x, matrix_sha = build_matrix(Path(tmp)/'training.npy', rows, summary['features']//2, index, case_data)
        del rows; gc.collect()
        print('fitting certified', fold['id'], x.shape, x.nbytes, flush=True)
        model = HistGradientBoostingClassifier(**PARAMETERS); model.fit(x, y, sample_weight=w)
        del x
    return model, {**summary, 'training_matrix_sha256': matrix_sha,
        'storage': 'read-only float64 mmap of float32 differences'}


def protect_training():
    active, accesses, allowed, reads = training_protection()
    def guard(event, args):
        if active[0] and event == 'open' and isinstance(args[0], (str, bytes)):
            name = os.fsdecode(args[0])
            if any(part in name for part in ['/author_case_states/', '/author_case_pairs/']):
                raise PermissionError('Author-only certified states forbidden in learner')
    sys.addaudithook(guard)
    for folder in ['author_case_states', 'author_case_pairs']:
        try: (LABELS/folder/'test.json.gz').read_bytes()
        except PermissionError: pass
        else: raise AssertionError('author-state guard')
    return active, accesses, allowed, reads


def predict():
    if RUN.exists(): raise SystemExit('Preserve dev22')
    preflight = protect_preflight()
    verify_features(); verify_preparation()
    sources = sorted((ROOT/'scripts').glob('*.py')) + sorted((ROOT/'tests').glob('*.py'))
    sources += [ROOT/'CERTIFIED_PREFERENCES_DEV22_PLAN_20261018.md']
    save(RUN/'source_lock.json', {'files': {str(p.relative_to(ROOT)): sha(p) for p in sources}})
    index = {item['case']: item for item in read(BASE/'public_index.json')}
    folds = read(LABELS/'fold_index.json')['folds']
    preflight[0] = False
    active, accesses, allowed, reads = protect_training()
    files = {}; runtime = []; wall, cpu = time.perf_counter(), time.process_time()
    for fold in folds:
        t, c = time.perf_counter(), time.process_time()
        allowed[0] = str((LABELS/fold['train_label_file']).resolve())
        model, summary = fit(fold, index); allowed[0] = None
        p = RUN/'models'/(fold['id']+'.joblib.gz'); p.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, p, compress=('gzip', 3)); files[str(p.relative_to(RUN))] = sha(p)
        counts = Counter()
        for case in fold['test_cases']:
            payload, x, k, positions = case_data(index[case]); probs, pred = infer(model, payload, x, k, positions)
            p = RUN/'predictions'/fold['id']/(case_path(case)+'.json.gz')
            compact(p, {'case': case, 'fold': fold['id'], **pred}); files[str(p.relative_to(RUN))] = sha(p)
            p = RUN/'probabilities'/fold['id']/(case_path(case)+'.npz'); p.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(p, probabilities=probs, order_digest=np.asarray(order_digest(payload['candidates'])))
            files[str(p.relative_to(RUN))] = sha(p); counts.update({m: len(pred[m]) for m in MODES})
        runtime.append(dict(fold=fold['id'], **summary, suggestions=dict(counts),
            wall_seconds=time.perf_counter()-t, cpu_seconds=time.process_time()-c))
        print('trained certified', fold['id'], summary, dict(counts), flush=True)
        del model; gc.collect()
    active[0] = False
    save(RUN/'runtime.json', dict(folds=runtime, wall_seconds=time.perf_counter()-wall, cpu_seconds=time.process_time()-cpu,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, parameters=PARAMETERS, threshold=THRESHOLD, margin=MARGIN,
        gpu_used=False, python=platform.python_version(), packages={'numpy': np.__version__, 'sklearn': sklearn.__version__, 'joblib': joblib.__version__},
        thread_environment={k: os.getenv(k) for k in ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS']},
        scope='certified comparison fits/inference; feature and label preparation excluded'))
    files['runtime.json'] = sha(RUN/'runtime.json')
    save(RUN/'prediction_lock.json', dict(files=files, source_lock_sha256=sha(RUN/'source_lock.json'),
        feature_lock_sha256=sha(FEATURES/'feature_lock.json'), preparation_lock_sha256=sha(LABELS/'preparation_lock.json'),
        fold_index_sha256=sha(LABELS/'fold_index.json'), training_labels_read=sorted(reads), heldout_labels_read=[],
        author_states_read=[], accesses=sorted(accesses), oracle_guard_exercised=True, final_validation_eligible=False))
    print('DEV22 PREDICTIONS LOCKED', flush=True)


def verify():
    verify_features(); verify_preparation(); lock = read(RUN/'prediction_lock.json')
    assert sha(RUN/'source_lock.json') == lock['source_lock_sha256']
    for rel, value in read(RUN/'source_lock.json')['files'].items(): assert sha(ROOT/rel) == value, rel
    for rel, value in lock['files'].items(): assert sha(RUN/rel) == value, rel
    assert sha(FEATURES/'feature_lock.json') == lock['feature_lock_sha256']
    for name in ['preparation_lock', 'fold_index']: assert sha(LABELS/(name+'.json')) == lock[name+'_sha256']
    assert lock['heldout_labels_read'] == lock['author_states_read'] == []
    expected = sorted(str((LABELS/fold['train_label_file']).resolve()) for fold in read(LABELS/'fold_index.json')['folds'])
    assert lock['training_labels_read'] == expected


def score():
    verify(); assert not (RUN/'score.json').exists()
    for rel, value in read(BASE/'label_preparation_lock.json')['files'].items(): assert sha(BASE/rel) == value, rel
    truth = read(BASE/'heldout_truth.json.gz')['cases']; cases = []
    for fold in read(LABELS/'fold_index.json')['folds']:
        for case in fold['test_cases']:
            t = truth[case]; labels = read(BASE/'case_labels'/(case_path(case)+'.json.gz'))
            pred = read(RUN/'predictions'/fold['id']/(case_path(case)+'.json.gz'))
            row = {'case': case, **{k: t[k] for k in ['origin_group', 'family', 'group', 'scenario']}}
            for mode in MODES: row[mode] = metrics(pred[mode], case, {'cases': {case: t}, 'candidate_labels': {case: labels}})
            cases.append(row)
    assert len(cases) == len({r['case'] for r in cases}) == 213
    report = dict(cases=cases, all={m: totals(cases, m) for m in MODES},
        prediction_lock_sha256=sha(RUN/'prediction_lock.json'), final_validation_eligible=False,
        accepted_final_sources=0, accepted_final_families=0, main_candidate_adopted=False,
        unknown_outputs_kept_in_denominator=True, candidate_pool_unchanged=True,
        control_dev20_all=read(ROOT/'development/unit_learning_dev20_v1/score.json')['all'],
        control_dev21_all=read(ROOT/'development/relative_learning_dev21_v1/score.json')['all'])
    for key in ['origin_group', 'family', 'group', 'scenario']:
        report[key] = {str(value): {m: totals([r for r in cases if r[key] == value], m) for m in MODES}
            for value in sorted({r[key] for r in cases}, key=str)}
    save(RUN/'score.json', report); print(report['all'], flush=True)
    for source, result in report['origin_group'].items(): print(source, result, flush=True)


def replay():
    verify(); active, accesses = protection(); count = 0; wall = time.perf_counter()
    index = {item['case']: item for item in read(BASE/'public_index.json')}
    for fold in read(LABELS/'fold_index.json')['folds']:
        model = joblib.load(RUN/'models'/(fold['id']+'.joblib.gz'))
        for case in fold['test_cases']:
            payload, x, k, positions = case_data(index[case]); probs, pred = infer(model, payload, x, k, positions)
            old = read(RUN/'predictions'/fold['id']/(case_path(case)+'.json.gz'))
            for mode, value in pred.items(): assert value == old[mode], (case, mode)
            with np.load(RUN/'probabilities'/fold['id']/(case_path(case)+'.npz'), allow_pickle=False) as saved:
                assert np.array_equal(probs, saved['probabilities'])
                assert str(saved['order_digest']) == order_digest(payload['candidates'])
            count += 1
        print('replayed certified', fold['id'], flush=True)
    active[0] = False
    p = ROOT/'qa/CERTIFIED_LEARNING_DEV22_REPLAY_20261018.json'; assert not p.exists()
    save(p, dict(cases=count, all_probabilities_and_suggestions_identical=True, labels_read=[], accesses=sorted(accesses),
        wall_seconds=time.perf_counter()-wall, prediction_lock_sha256=sha(RUN/'prediction_lock.json')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['predict', 'score', 'verify', 'replay'])
    {'predict': predict, 'score': score, 'verify': verify, 'replay': replay}[parser.parse_args().mode]()
