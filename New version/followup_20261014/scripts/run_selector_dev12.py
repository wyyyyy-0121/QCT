"""Freeze predictions before labels; compare explicit checks and legacy cases.

New workbooks run the full paper pipeline. Legacy workbooks rerun dev6 from
frozen upstream evidence, qualify, and compare exactly against dev11 locks.
No labelled preparation module is imported in prediction/replay processes.
"""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import platform
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
BASE = ROOT / 'baseline'
DATA = ROOT / 'development/reconciliation_dev12_inputs_v1'
RUN = ROOT / 'development/selector_dev12_reconciliation_v1'
OLD = ROOT / 'development/selector_dev11_complete_ast_v1'
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(BASE / 'source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
from formulaguard.v5_structural_guard import v5_structural_guard_scores
from structuralguard.detector import analyze_workbook
from selector_dev2 import select
from selector_dev4 import review_guard
from selector_dev6 import augment
from selector_dev11 import qualify
from selector_dev12 import apply, VERSION
from run_selector_dev5 import read, save, sha, metrics, total
from run_selector_dev8 import case_prediction, truth_and_observed, GROUPS, guard_prediction
from run_selector_dev11 import verify as verify_dev11

spec = importlib.util.spec_from_file_location('dev12_frozen_paper', BASE / 'scripts/predict.py')
paper_adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paper_adapter)
NAMES = ['paper', 'dev11', 'dev12']


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def protect_prediction():
    accesses, active = set(), [True]
    guard_prediction(accesses, active)
    def extra_guard(event, args):
        if active[0] and event == 'open' and isinstance(args[0], (str, bytes)):
            if 'prepare_reconciliation_dev12' in str(args[0]):
                raise PermissionError('Prediction cannot read development author/oracle code')
    sys.addaudithook(extra_guard)
    return accesses, active


def prediction(item):
    path = ROOT / item['input']
    model = WorkbookModel.from_xlsx(path)
    before = deepcopy((model.cells, model.formulas))
    if item['group'] == 'controlled_reconciliation':
        sg = analyze_workbook(path)['results']
        fg = [{'rank': i, 'cell': v.cell_label, 'score': v.score,
               'candidate_formula': v.candidate_formula, 'evidence': v.evidence}
              for i, v in enumerate(v5_structural_guard_scores(model), 1)]
        forms = {s+'!'+a: v for (s, a), v in model.formulas.items()}
        paper = paper_adapter.hybrid((model, sg, fg, forms, item['parallel_sheets']), {})
        dev2 = select(model, paper, fg, sg, item['parallel_sheets'])
        dev4 = review_guard(model, dev2)
        dev11 = qualify(model, augment(model, dev4, item['parallel_sheets']))
    else:
        dev6, count = case_prediction(item)
        assert count == len(model.formulas)
        dev11 = qualify(model, dev6)
        assert dev11 == read(OLD / 'predictions' / item['group'] / (item['id']+'.json.gz'))
        paper = None  # The 107-case comparison is dev11/dev12; paper was frozen earlier.
    prior_digest = digest(dev11)
    dev12 = apply(model, dev11)
    assert digest(dev11) == prior_digest
    assert (model.cells, model.formulas) == before
    labels = {s+'!'+a for s, a in model.formulas}
    for result in [dev11, dev12] + ([paper] if paper is not None else []):
        assert len(result['rows']) == len(labels)
        assert {r['cell'] for r in result['rows']} == labels
    return {'paper': paper, 'dev11': dev11, 'dev12': dev12,
            'observed_formulas': {s+'!'+a: v for (s, a), v in model.formulas.items()},
            'automatic_edit_applied': False}


def verify():
    lock = read(RUN / 'prediction_lock.json')
    assert sha(RUN / 'source_lock.json') == lock['source_lock_sha256']
    for rel, value in read(RUN / 'source_lock.json')['files'].items():
        assert sha(ROOT / rel) == value, rel
    for rel, value in lock['inputs_and_upstream'].items():
        assert sha(ROOT / rel) == value, rel
    for rel, value in lock['files'].items():
        assert sha(RUN / rel) == value, rel
    assert lock['labels_read'] == [] and not lock['final_validation_eligible']
    return lock


def predict():
    if RUN.exists():
        raise SystemExit('Preserve dev12 evidence; use a new experiment version')
    verify_dev11()
    index = [i for i in read(OLD / 'public_index.json') if i['group'] != 'public']
    index += read(DATA / 'public_index.json')
    assert len(index) == 167
    sources = sorted((ROOT / 'scripts').glob('*.py'))
    sources += sorted((ROOT / 'tests').glob('*.py'))
    sources += sorted((BASE / 'source').rglob('*.py'))
    sources += [BASE / 'scripts/predict.py', ROOT / 'DEV12_EXPERIMENT_PLAN_20261018.md']
    save(RUN / 'source_lock.json', {'version': VERSION,
         'files': {str(p.relative_to(ROOT)): sha(p) for p in sources}})
    save(RUN / 'public_index.json', index)
    inputs = {}
    for item in index:
        for field in ['input', 'upstream', 'parallel_metadata']:
            if field in item:
                path = ROOT / item[field]
                value = sha(path)
                assert value == item[field+'_sha256']
                inputs[item[field]] = value
        if item['group'] != 'controlled_reconciliation':
            old = OLD / 'predictions' / item['group'] / (item['id']+'.json.gz')
            inputs[str(old.relative_to(ROOT))] = sha(old)
    for path in [OLD / 'prediction_lock.json', OLD / 'public_index.json', DATA / 'public_index.json']:
        inputs[str(path.relative_to(ROOT))] = sha(path)
    accesses, active = protect_prediction()
    wall, cpu = time.perf_counter(), time.process_time()
    files, timings = {}, []
    for item in index:
        t, c = time.perf_counter(), time.process_time()
        result = prediction(item)
        path = RUN / 'predictions' / item['group'] / (item['id']+'.json.gz')
        save(path, result); files[str(path.relative_to(RUN))] = sha(path)
        timings.append({'id': item['id'], 'group': item['group'],
                        'wall_seconds': time.perf_counter()-t,
                        'cpu_seconds': time.process_time()-c,
                        'formula_cells': len(result['observed_formulas'])})
        print(item['group'], item['id'], 'changes',
              result['dev12']['reconciliation_summary']['changed_decisions'], flush=True)
    active[0] = False
    runtime = {'wall_seconds': time.perf_counter()-wall, 'cpu_seconds': time.process_time()-cpu,
               'gpu_used': False, 'cases': timings, 'python': platform.python_version(),
               'platform': platform.platform(),
               'process_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               'scope': '60 complete paper/dev11/dev12 cases; 107 dev6 replay + dev11/dev12 from frozen upstream'}
    save(RUN / 'runtime.json', runtime)
    for name in ['runtime.json', 'public_index.json']: files[name] = sha(RUN / name)
    save(RUN / 'prediction_lock.json', {'source_lock_sha256': sha(RUN / 'source_lock.json'),
         'files': files, 'inputs_and_upstream': inputs, 'labels_read': [],
         'accesses': sorted(accesses), 'final_validation_eligible': False,
         'role': 'controlled explicit-declaration development, separate from legacy and final validation'})
    print('DEV12 PREDICTIONS LOCKED', len(index), runtime['wall_seconds'], flush=True)


def paper_for_scoring(raw):
    # Paper statuses are not the follow-up selector's propose/review vocabulary.
    normalized = deepcopy(raw)
    for row in normalized['rows']:
        row['status'] = 'propose' if row.get('suggested_formula') else 'abstain'
    return normalized


def check_oracle(truth):
    # Imported only after the prediction lock is complete, in scoring process.
    from prepare_reconciliation_dev12 import independent_evaluate
    from openpyxl import load_workbook
    checks = 0
    items = {i['id']: i for i in read(DATA / 'public_index.json')}
    for case in truth:
        workbook = load_workbook(ROOT / items[case['id']]['input'], data_only=False)
        actual_formulas = {ws.title+'!'+cell.coordinate: cell.value
                           for ws in workbook for row in ws for cell in row if cell.data_type == 'f'}
        assert actual_formulas == case['observed_formulas']
        for label, expected in case['expected_values_fraction'].items():
            sheet, address = label.rsplit('!', 1)
            ws = workbook[sheet]
            value = independent_evaluate(case['expected_formulas'][label], lambda a: ws[a].value)
            assert str(value) == expected
            if label in case['errors']:
                assert independent_evaluate(case['observed_formulas'][label], lambda a: ws[a].value) != value
            checks += 1
        workbook.close()
    return {'correct_outputs_checked': checks, 'input_formulas_rechecked': True,
            'all_mutations_numeric_and_different': True, 'engine': 'independent Python AST + Fraction'}


def build_score():
    truths = read(DATA / 'truth.json')['cases']
    oracle = check_oracle(truths)
    truth_index = {c['id']: c for c in truths}
    cases, legacy = [], {g: [] for g in GROUPS}
    for item in read(RUN / 'public_index.json'):
        pred = read(RUN / 'predictions' / item['group'] / (item['id']+'.json.gz'))
        if item['group'] == 'controlled_reconciliation':
            truth = truth_index[item['id']]
            row = {k: truth[k] for k in ['id', 'family', 'scenario']}
            assert pred['observed_formulas'] == truth['observed_formulas']
            observed = pred['observed_formulas']
            for name in NAMES:
                normalized = paper_for_scoring(pred[name]) if name == 'paper' else pred[name]
                row[name] = metrics(normalized, truth, observed)
            row['reconciliation_reasons'] = dict(Counter(
                r.get('reason') for r in pred['dev12']['rows'] if 'reconciliation' in r))
            row['formula_identity_proven'] = False
            cases.append(row)
        else:
            truth, observed = truth_and_observed(item)
            row = {'id': item['id'], **{name: metrics(pred[name], truth, observed)
                                       for name in ['dev11', 'dev12']}}
            row['rows_unchanged'] = pred['dev11']['rows'] == pred['dev12']['rows']
            assert row['rows_unchanged']
            legacy[item['group']].append(row)
    family, scenario = {}, {}
    for key, table in [('family', family), ('scenario', scenario)]:
        for name in sorted({c[key] for c in cases}):
            selected = [c for c in cases if c[key] == name]
            table[name] = {v: total(selected, v) for v in NAMES}
    return {'role': 'revealed controlled-declaration development only',
            'final_validation_eligible': False, 'accepted_final_sources': 0,
            'accepted_final_families': 0, 'oracle': oracle,
            'prediction_lock_sha256': sha(RUN / 'prediction_lock.json'),
            'paper_scoring': 'all nonempty suggested_formula outputs differing from observed, irrespective of raw status',
            'controlled': {'cases': cases, 'totals': {v: total(cases, v) for v in NAMES},
                           'by_family': family, 'by_scenario': scenario},
            'legacy': {g: {'cases': rows, 'totals': {v: total(rows, v) for v in ['dev11', 'dev12']}}
                       for g, rows in legacy.items()}}


def score():
    verify()
    if (RUN / 'score.json').exists(): raise SystemExit('Preserve dev12 score')
    result = build_score(); save(RUN / 'score.json', result)
    print(json.dumps(result['controlled']['totals'], indent=2))
    print(json.dumps(result['controlled']['by_scenario'], indent=2))


def replay():
    verify()
    accesses, active = protect_prediction()
    t, c = time.perf_counter(), time.process_time()
    index = read(RUN / 'public_index.json')
    for item in index:
        actual = prediction(item)
        expected = read(RUN / 'predictions' / item['group'] / (item['id']+'.json.gz'))
        assert actual == expected, item['id']
        print('REPLAY', item['group'], item['id'], flush=True)
    active[0] = False
    assert build_score() == read(RUN / 'score.json')
    save(ROOT / 'qa/DEV12_REPLAY_20261018.json', {
         'cases': len(index), 'all_predictions_replayed_exactly': True,
         'score_recomputed_after_replay': True, 'labels_read_during_replay': False,
         'wall_seconds': time.perf_counter()-t, 'cpu_seconds': time.process_time()-c,
         'prediction_lock_sha256': sha(RUN / 'prediction_lock.json'),
         'score_sha256': sha(RUN / 'score.json'), 'final_validation_eligible': False,
         'utc': dt.datetime.now(dt.timezone.utc).isoformat()})
    print('DEV12 REPLAY VERIFIED', len(index))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['predict', 'score', 'verify', 'replay'])
    args = parser.parse_args()
    {'predict': predict, 'score': score, 'verify': verify, 'replay': replay}[args.stage]()
