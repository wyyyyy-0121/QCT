"""Author-only full-pool certificates; no training or heldout performance scoring."""
from collections import Counter
from pathlib import Path
import resource
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from openpyxl import load_workbook
from run_selector_dev5 import read, save, sha
from run_certified_learning_dev22 import verify as verify22
from build_keep_features_dev21 import BASE, DATA as FEATURES, case_path
from build_candidates_dev18 import compact
from tristate_relations_dev23 import NumericRelations, BUDGETS, SEEDS
DATA = ROOT/'development/tristate_states_dev23_v1'
KEEP = '__observed_formula__'


def prepare():
    if DATA.exists(): raise SystemExit('Preserve dev23 certificates')
    verify22()
    for rel, value in read(BASE/'label_preparation_lock.json')['files'].items(): assert sha(BASE/rel) == value, rel
    truth = read(BASE/'heldout_truth.json.gz')['cases']
    sources = [Path(__file__), ROOT/'scripts/tristate_relations_dev23.py',
               ROOT/'tests/test_tristate_relations_dev23.py', ROOT/'TRISTATE_RELATIONS_DEV23_PLAN_20261018.md']
    save(DATA/'source_lock.json', dict(files={str(p.relative_to(ROOT)): sha(p) for p in sources}))
    files = {}; summaries = []; inputs = {}; wall, cpu = time.perf_counter(), time.process_time()
    for item in read(BASE/'public_index.json'):
        case = item['case']; t = truth[case]; expected = t['expected_formulas']; errors = set(t['errors'])
        path = ROOT/item['input']; assert sha(path) == item['input_sha256']
        inputs[item['input']] = sha(path)
        payload = read(BASE/'features'/(case_path(case)+'.json.gz'))
        labels = read(BASE/'case_labels'/(case_path(case)+'.json.gz'))
        workbook = load_workbook(path, data_only=False)
        oracle = NumericRelations(workbook, expected)
        states = []; counts = Counter(); reasons = Counter(); transitions = Counter(); targets = {}
        def certify(key, cell, formula, kind):
            sheet, address = cell.rsplit('!', 1)
            result = oracle.certify(formula, expected.get(cell), sheet, target=cell, in_scope=cell in expected)
            state = dict(id=key, case=case, cell=cell, kind=kind, **result)
            y = 'unknown' if result['label'] is None else str(result['label'])
            scope = 'outside' if cell not in expected else ('error' if cell in errors else 'clean')
            counts[f'{scope}_{kind}_{y}'] += 1; reasons[result['reason']] += 1
            return state
        for cell in sorted({c['cell'] for c in payload['candidates']}):
            sheet, address = cell.rsplit('!', 1); formula = workbook[sheet][address].value
            if cell in t['observed_formulas']: assert formula == t['observed_formulas'][cell]
            state = certify(KEEP, cell, formula, 'keep'); states.append(state)
            targets[cell] = dict(keep_label=state['label'], positive=0, negative=0, unknown=0)
        for candidate in payload['candidates']:
            state = certify(candidate['id'], candidate['cell'], candidate['formula'], 'candidate'); states.append(state)
            bucket = 'unknown' if state['label'] is None else ('positive' if state['label'] else 'negative')
            targets[candidate['cell']][bucket] += 1
            scope = 'outside' if candidate['cell'] not in expected else ('error' if candidate['cell'] in errors else 'clean')
            transitions[f'{scope}_legacy_{labels[candidate["id"]]}_relation_{state["label"]}'] += 1
        workbook.close()
        p = DATA/'author_case_states'/(case_path(case)+'.json.gz')
        compact(p, dict(case=case, alternatives=states)); files[str(p.relative_to(DATA))] = sha(p)
        summary = dict(case=case, source=t['origin_group'], family=t['family'], counts=dict(counts),
            reasons=dict(reasons), old_repair_to_relation_states=dict(transitions), candidates=len(payload['candidates']), targets=len(targets),
            clean_targets_with_certified_negative=sum(cell in expected and cell not in errors and value['negative'] > 0 for cell, value in targets.items()),
            targets_with_certified_contrast=sum((value['positive'] > 0 or value['keep_label'] == 1) and
                (value['negative'] > 0 or value['keep_label'] == 0) for value in targets.values()))
        summaries.append(summary)
        print('tristate prepared', case, summary['candidates'], summary['targets_with_certified_contrast'], dict(counts), flush=True)
        del workbook, oracle, states, payload, labels, targets
    save(DATA/'state_counts.json', summaries); files['state_counts.json'] = sha(DATA/'state_counts.json')
    save(DATA/'runtime.json', dict(wall_seconds=time.perf_counter()-wall, cpu_seconds=time.process_time()-cpu,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, gpu_used=False, scope='author-only full-pool numeric relation certification'))
    files['runtime.json'] = sha(DATA/'runtime.json')
    save(DATA/'preparation_lock.json', dict(files=files, inputs=inputs, source_lock_sha256=sha(DATA/'source_lock.json'),
        upstream_label_lock_sha256=sha(BASE/'label_preparation_lock.json'), upstream_fold_index_sha256=sha(BASE/'fold_index.json'),
        feature_lock_sha256=sha(FEATURES/'feature_lock.json'), budgets=BUDGETS, witness_seeds=list(SEEDS),
        predictor_access_forbidden=True, final_validation_eligible=False,
        semantic_scope='numeric dependency abstraction conditional on reviewed expected formulas and visible remaining dependencies',
        old_repair_labels_and_scores_unchanged=True))
    print('DEV23 AUTHOR STATES LOCKED; NO MODEL TRAINED', flush=True)


if __name__ == '__main__': prepare()
