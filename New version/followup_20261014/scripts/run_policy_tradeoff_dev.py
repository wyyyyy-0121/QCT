"""Measure dev3 review coverage loss and unmarked exceptions on revealed data."""
from pathlib import Path
import argparse
import importlib.util
import json
import sys

import run_semantic_stress_dev as helpers

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'development/policy_tradeoff_dev1'
PRIOR = ROOT / 'development/semantic_stress_dev1'
BASE = ROOT / 'baseline'
sys.path.insert(0, str(BASE / 'source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
from formulaguard.v5_structural_guard import v5_structural_guard_scores
from structuralguard.detector import analyze_workbook
from selector_dev2 import select as dev2_select
from selector_dev3 import review_guard

sha, save, read = helpers.sha, helpers.save, helpers.read


def prepare():
    from openpyxl import load_workbook
    if RUN.exists():
        raise SystemExit('Preserve existing tradeoff development evidence')
    truth = {x['id']: x for x in read(PRIOR / 'truth.json')['cases']}
    scenarios = [
        ('p01', 'c01', 'real_sign_errors_with_policy_note', 'add_A'),
        ('p02', 'c03', 'unmarked_legitimate_shipping_waiver', 'remove_A'),
        ('p03', 'c08', 'unmarked_legitimate_cost_reimbursement', 'remove_A'),
        ('p04', 'c01', 'real_sign_errors_note_on_other_sheet', 'add_B'),
    ]
    public = []; answers = []
    for case, parent, scenario, mutation in scenarios:
        book = load_workbook(PRIOR / 'inputs' / (parent + '.xlsx'))
        if mutation == 'remove_A':
            book['A']['H1'] = None; book['A']['H2'] = None
        else:
            sheet = mutation[-1]
            book[sheet]['H1'] = 'Business policy'
            book[sheet]['H2'] = 'All ordinary shipping costs in this sheet are borne by the seller.'
        path = RUN / 'inputs' / (case + '.xlsx'); path.parent.mkdir(parents=True, exist_ok=True)
        book.save(path)
        public.append({'id': case, 'input': str(path.relative_to(RUN)), 'sha256': sha(path),
                       'parallel_sheets': ['A', 'B', 'C', 'D', 'E']})
        answers.append({**truth[parent], 'id': case, 'scenario': scenario})
    save(RUN / 'public_index.json', public)
    save(RUN / 'truth.json', {'cases': answers, 'role': 'revealed development; derived counterexamples'})
    save(RUN / 'registration.json', {'role': 'guard tradeoff diagnostics; zero new final families',
        'cases': len(public), 'hypotheses': ['Policy review can hide real errors.',
            'Unmarked legal exceptions remain unsafe.', 'A note on one sheet should not suppress another.']})
    print('prepared', len(public))


def predict():
    if (RUN / 'predictions').exists():
        raise SystemExit('Preserve tradeoff predictions')
    for previous in [ROOT / 'development/selector_dev3', PRIOR]:
        lock = read(previous / 'prediction_lock.json')
        assert sha(previous / 'source_lock.json') == lock['source_lock_sha256']
        for relative, expected in lock['files'].items():
            assert sha(previous / relative) == expected, relative
        for relative, expected in read(previous / 'source_lock.json')['files'].items():
            assert sha(ROOT / relative) == expected, relative
    sources = [Path(__file__), Path(helpers.__file__), ROOT / 'scripts/selector_dev2.py',
               ROOT / 'scripts/selector_dev3.py', BASE / 'scripts/predict.py']
    sources += sorted((BASE / 'source').rglob('*.py'))
    save(RUN / 'source_lock.json', {'files': {str(p.relative_to(ROOT)): sha(p) for p in sources}})
    spec = importlib.util.spec_from_file_location('tradeoff_paper_adapter', BASE / 'scripts/predict.py')
    adapter = importlib.util.module_from_spec(spec); spec.loader.exec_module(adapter)
    accesses = set()
    def guard(event, args):
        if event == 'open' and isinstance(args[0], (str, bytes)):
            name = str(args[0])
            if any(x in name.lower() for x in ['truth.json', 'registration.json', '/score', '/results/', 'failure_audit']):
                raise PermissionError('Prediction cannot read answer evidence: ' + name)
            if str(ROOT) in name:
                accesses.add(name)
    sys.addaudithook(guard)
    files = {}
    for entry in read(RUN / 'public_index.json'):
        path = RUN / entry['input']; assert sha(path) == entry['sha256']
        model = WorkbookModel.from_xlsx(path); before = dict(model.formulas)
        structural = analyze_workbook(path)['results']
        fg = [{'rank': i, 'cell': x.cell_label, 'score': x.score, 'candidate_formula': x.candidate_formula,
               'evidence': x.evidence} for i, x in enumerate(v5_structural_guard_scores(model), 1)]
        observed = {s + '!' + a: f for (s, a), f in model.formulas.items()}
        paper = adapter.hybrid((model, structural, fg, observed, entry['parallel_sheets']), {})
        dev2 = dev2_select(model, paper, fg, structural, entry['parallel_sheets'])
        dev3 = review_guard(model, dev2)
        assert model.formulas == before
        target = RUN / 'predictions' / (entry['id'] + '.json')
        save(target, {'paper': paper, 'dev2': dev2, 'dev3': dev3, 'observed_formulas': observed})
        files[str(target.relative_to(RUN))] = sha(target)
        print(entry['id'], flush=True)
    save(RUN / 'prediction_lock.json', {'files': files, 'labels_read': [], 'accesses': sorted(accesses),
         'source_lock_sha256': sha(RUN / 'source_lock.json'), 'public_index_sha256': sha(RUN / 'public_index.json')})


def score():
    if (RUN / 'score.json').exists():
        raise SystemExit('Preserve scores')
    lock = read(RUN / 'prediction_lock.json')
    assert sha(RUN / 'source_lock.json') == lock['source_lock_sha256']
    assert sha(RUN / 'public_index.json') == lock['public_index_sha256']
    for relative, expected in lock['files'].items():
        assert sha(RUN / relative) == expected, relative
    for relative, expected in read(RUN / 'source_lock.json')['files'].items():
        assert sha(ROOT / relative) == expected, relative
    cases = []
    for truth in read(RUN / 'truth.json')['cases']:
        pred = read(RUN / 'predictions' / (truth['id'] + '.json'))
        result = {'id': truth['id'], 'scenario': truth['scenario'], 'errors': len(truth['errors'])}
        for name in ['paper', 'dev2', 'dev3']:
            rows = pred[name]['rows']
            assert len(rows) == len({r['cell'] for r in rows}) == len(truth['expected_formulas'])
            assert {r['cell'] for r in rows} == set(truth['expected_formulas'])
            proposals = [r for r in rows if r.get('suggested_formula')
                and r['suggested_formula'] != pred['observed_formulas'][r['cell']]
                and (name == 'paper' or r['status'] == 'propose')]
            c = sum(r['suggested_formula'] == truth['expected_formulas'][r['cell']] for r in proposals)
            result[name] = {'proposals': len(proposals), 'correct': c, 'wrong': len(proposals) - c,
                            'precision': c / len(proposals) if proposals else None,
                            'coverage': c / len(truth['errors']) if truth['errors'] else None,
                            'reviewed': sum(r.get('reason') == 'unresolved_visible_business_policy' for r in rows)}
        cases.append(result); print(result, flush=True)
    save(RUN / 'score.json', {'role': 'revealed tradeoff diagnostic; not final validation', 'cases': cases,
                            'prediction_lock_sha256': sha(RUN / 'prediction_lock.json')})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('stage', choices=['prepare', 'predict', 'score'])
    args = parser.parse_args(); {'prepare': prepare, 'predict': predict, 'score': score}[args.stage]()
