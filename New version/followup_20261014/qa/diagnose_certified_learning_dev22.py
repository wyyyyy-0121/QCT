"""Post-lock, post-score attribution; this cannot alter learned decisions."""
from collections import Counter, defaultdict
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from run_certified_learning_dev22 import BASE, RUN, verify, case_path
from run_selector_dev5 import read, save, sha
from build_candidates_dev16 import uid
from candidate_features_dev16 import THRESHOLD, MARGIN


def main():
    verify()
    scored = read(RUN / 'score.json')
    truth = read(BASE / 'heldout_truth.json.gz')['cases']
    grouped = defaultdict(Counter)
    details = []
    ranges = {}
    for fold in read(BASE / 'fold_index.json')['folds']:
        min_p, max_p, n_above, n_candidates = 1., 0., 0, 0
        for case in fold['test_cases']:
            t = truth[case]
            labels = read(BASE / 'case_labels' / (case_path(case)+'.json.gz'))
            payload = read(BASE / 'features' / (case_path(case)+'.json.gz'))
            pred = read(RUN / 'predictions' / fold['id'] / (case_path(case)+'.json.gz'))
            with np.load(RUN / 'probabilities' / fold['id'] / (case_path(case)+'.npz'), allow_pickle=False) as d:
                probs = d['probabilities']
            assert len(probs) == len(payload['candidates'])
            if len(probs):
                assert np.isfinite(probs).all() and np.all((probs >= 0) & (probs <= 1))
                min_p, max_p = min(min_p, float(probs.min())), max(max_p, float(probs.max()))
                n_above += int((probs >= THRESHOLD).sum())
                n_candidates += len(probs)
            pool = defaultdict(list)
            for c, p in zip(payload['candidates'], probs):
                pool[c['cell']].append((c, float(p)))
            selected = {r['cell']: r for r in pred['keep_base_plus_learned']}
            for cell in t['errors']:
                rows = pool[cell]
                eligible = sorted([(c, p) for c, p in rows if c['eligible']], key=lambda r: (-r[1], r[0]['formula']))
                good = [(c, p) for c, p in eligible if labels[c['id']] == 1]
                out = selected.get(cell)
                if out and labels[uid(case, cell, out['suggested_formula'])] == 1:
                    reason = 'base_correct_selected' if out in pred['dev11'] else 'learned_correct_selected'
                elif out:
                    reason = 'selected_wrong_or_unknown'
                elif not any(labels[c['id']] == 1 for c, p in rows):
                    reason = 'correct_candidate_missing'
                elif not good:
                    reason = 'correct_candidate_ineligible'
                elif labels[eligible[0][0]['id']] != 1:
                    reason = 'wrong_or_unknown_ranked_first'
                elif eligible[0][1] < THRESHOLD:
                    reason = 'correct_first_below_threshold'
                elif len(eligible) > 1 and eligible[0][1]-eligible[1][1] < MARGIN:
                    reason = 'insufficient_margin'
                else:
                    reason = 'other_rejection'
                group = grouped[t['origin_group']]
                group[reason] += 1
                if t['origin_group'] != 'authored_development' or group[reason] <= 4:
                    details.append({'case': case, 'cell': cell, 'origin': t['origin_group'], 'reason': reason,
                                    'observed': t['observed_formulas'][cell], 'expected': t['expected_formulas'][cell],
                                    'best_correct_preference': max((p for c, p in good), default=None),
                                    'top': [{'formula': c['formula'], 'preference': p, 'label': labels[c['id']]} for c, p in eligible[:3]]})
        ranges[fold['origin']] = {'candidate_count': n_candidates, 'preference_min': min_p if n_candidates else None,
                                 'preference_max': max_p if n_candidates else None, 'at_least_0_90': n_above}
    assert sum(sum(g.values()) for g in grouped.values()) == scored['all']['keep_base_plus_learned']['errors']
    out = ROOT / 'qa/CERTIFIED_LEARNING_DEV22_MISS_DIAGNOSIS_20261018.json'
    assert not out.exists()
    save(out, {'by_origin': dict(grouped), 'preference_ranges': ranges, 'details': details,
               'prediction_lock_sha256': sha(RUN/'prediction_lock.json'), 'score_sha256': sha(RUN/'score.json'),
               'audit_source_sha256': sha(Path(__file__)), 'posthoc_labels_read': True,
               'preferences_are_not_calibrated_correctness_probabilities': True, 'final_validation_eligible': False})
    print(dict(grouped))
    print(ranges)


if __name__ == '__main__':
    main()
