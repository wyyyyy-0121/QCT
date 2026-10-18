"""Post-score necessary-condition ceiling for the unchanged deterministic ranker.

Equal feature rows within a cell must have equal preferences for any deterministic
model. A strictly positive top-two margin precludes selecting either member of
an eligible tie. This is a representation bound, not a model performance claim.
"""
from collections import Counter, defaultdict
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from run_relative_learning_dev21 import BASE, DATA, RUN, verify, case_path, case_data
from run_selector_dev5 import read, save, sha
from build_candidates_dev16 import uid


def main():
    verify()
    score = read(RUN/'score.json')
    truth = read(BASE/'heldout_truth.json.gz')['cases']
    index = {r['case']: r for r in read(BASE/'public_index.json')}
    units = read(ROOT/'development/unit_features_dev20_v1/feature_schema.json')['names']
    unit_column = -len(units) + units.index('unit_new_incompatible')
    counts = defaultdict(Counter)
    examples = []
    for fold in read(BASE/'fold_index.json')['folds']:
        for case in fold['test_cases']:
            t = truth[case]
            labels = read(BASE/'case_labels'/(case_path(case)+'.json.gz'))
            payload, x, keep, offsets = case_data(index[case])
            by_cell = defaultdict(list)
            for n, c in enumerate(payload['candidates']):
                if c['eligible']:
                    by_cell[c['cell']].append(n)
            prior = {r['cell']: r for r in payload['baseline']}
            for cell in t['errors']:
                count = counts[t['origin_group']]
                count['errors'] += 1
                groups = defaultdict(list)
                for n in by_cell[cell]:
                    # Match real float32 subtraction. Canonicalize signed zero,
                    # since +0 and -0 cannot distinguish tree decision paths.
                    k = keep[offsets[n]]
                    v = np.concatenate((k, x[n]-k))
                    v[v == 0] = 0
                    groups[v.tobytes()].append(n)
                good = [n for n in by_cell[cell] if labels[payload['candidates'][n]['id']] == 1]
                unique_good = [ns[0] for ns in groups.values() if len(ns) == 1
                               and labels[payload['candidates'][ns[0]]['id']] == 1
                               and not x[ns[0], unit_column]]
                base = prior.get(cell)
                base_correct = bool(base and labels[uid(case, cell, base['suggested_formula'])] == 1)
                count['eligible_correct_candidate_exists'] += bool(good)
                count['unique_compatible_correct_candidate_exists'] += bool(unique_good)
                count['baseline_correct'] += base_correct
                count['baseline_or_distinguishable_correct_upper_bound'] += bool(base_correct or unique_good)
                if good and not unique_good:
                    count['correct_candidates_blocked_by_tie_or_unit_gate'] += 1
                    if len(examples) < 30 or t['origin_group'] != 'authored_development':
                        tied = next((ns for ns in groups.values() if len(ns)>1 and
                                     any(labels[payload['candidates'][n]['id']] == 1 for n in ns)), [])
                        examples.append({'case': case, 'origin': t['origin_group'], 'cell': cell,
                                         'observed': t['observed_formulas'][cell],
                                         'feature_identical_candidates': [
                                             {'formula': payload['candidates'][n]['formula'],
                                              'label': labels[payload['candidates'][n]['id']]} for n in tied[:6]]})
            print('identifiability audited', case, flush=True)
    total = Counter()
    for c in counts.values():
        total.update(c)
    assert total['errors'] == score['all']['dev11']['errors']
    out = ROOT/'qa/RELATIVE_LEARNING_DEV21_IDENTIFIABILITY_20261018.json'
    assert not out.exists()
    save(out, {'by_origin': dict(counts), 'all': dict(total), 'examples': examples,
               'bound_scope': 'Necessary condition only; per-cell feature ties with strictly positive margin; not achieved coverage',
               'unknown_never_a_certified_correct_candidate': True,
               'posthoc_labels_read': True, 'decisions_unchanged': True,
               'prediction_lock_sha256': sha(RUN/'prediction_lock.json'),
               'audit_source_sha256': sha(Path(__file__)), 'final_validation_eligible': False})
    print(dict(counts)); print(dict(total))


if __name__ == '__main__':
    main()
