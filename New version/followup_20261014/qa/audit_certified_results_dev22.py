"""Independent post-lock integer recount and explicit per-suggestion comparisons."""
from collections import Counter, defaultdict
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read, save, sha
from run_certified_learning_dev22 import RUN, BASE, LABELS, MODES, verify, case_path
from build_candidates_dev16 import uid


def main():
    verify(); truth = read(BASE/'heldout_truth.json.gz')['cases']; score = read(RUN/'score.json')
    cases = {r['case']: r for r in score['cases']}; aggregate = {m: Counter() for m in MODES}
    by_source = defaultdict(lambda: {m: Counter() for m in MODES}); failures = []; checks = 0
    additions = {version: set() for version in ['unit_learning_dev20_v1', 'relative_learning_dev21_v1', RUN.name]}
    for fold in read(LABELS/'fold_index.json')['folds']:
        for case in fold['test_cases']:
            t = truth[case]; errors = set(t['errors']); expected = t['expected_formulas']
            labels = read(BASE/'case_labels'/(case_path(case)+'.json.gz'))
            pred = read(RUN/'predictions'/fold['id']/(case_path(case)+'.json.gz'))
            for mode in MODES:
                rows = pred[mode]; assert len(rows) == len({r['cell'] for r in rows})
                counts = Counter(suggestions=len(rows), errors=len(errors))
                for row in rows:
                    cell = row['cell']; y = labels[uid(case, cell, row['suggested_formula'])]
                    if cell not in expected: outcome = 'unknown'; counts['unknown'] += 1
                    elif y == 1 and cell in errors:
                        outcome = 'correct'; counts['correct'] += 1; counts['correct_errors'] += 1
                    else:
                        outcome = 'wrong'; counts['wrong'] += 1; counts['wrong_clean_cells'] += cell not in errors
                    if outcome != 'correct': failures.append(dict(case=case, mode=mode, outcome=outcome, **row))
                for key in ['suggestions', 'correct', 'correct_errors', 'wrong', 'wrong_clean_cells', 'unknown', 'errors']:
                    assert counts[key] == cases[case][mode][key], (case, mode, key)
                    aggregate[mode][key] += counts[key]; by_source[t['origin_group']][mode][key] += counts[key]; checks += 1
                assert counts['suggestions'] == counts['correct']+counts['wrong']+counts['unknown']
                precision = counts['correct']/counts['suggestions'] if counts['suggestions'] else None
                coverage = counts['correct_errors']/counts['errors'] if counts['errors'] else None
                assert precision == cases[case][mode]['precision_confirmed_lower_bound']
                assert coverage == cases[case][mode]['coverage']
            for version in additions:
                p = ROOT/'development'/version/'predictions'/fold['id']/(case_path(case)+'.json.gz')
                for row in read(p)['learned_only']: additions[version].add((case, row['cell'], row['suggested_formula']))
    for mode in MODES:
        for key, value in aggregate[mode].items(): assert value == score['all'][mode][key]
    for source, modes in by_source.items():
        for mode, counts in modes.items():
            for key, value in counts.items(): assert value == score['origin_group'][source][mode][key]
    comparisons = {}
    current = additions[RUN.name]
    for version, old in additions.items():
        if version == RUN.name: continue
        delta = dict(shared=len(current & old), added=[], lost=[])
        for key, items in [('added', current-old), ('lost', old-current)]:
            for case, cell, formula in sorted(items):
                delta[key].append(dict(case=case, cell=cell, formula=formula,
                    label=read(BASE/'case_labels'/(case_path(case)+'.json.gz'))[uid(case, cell, formula)]))
        comparisons[version] = delta
    target = ROOT/'qa/CERTIFIED_LEARNING_DEV22_INDEPENDENT_COUNTS_20261018.json'; assert not target.exists()
    save(target, dict(integer_count_checks=checks, all_counts_identical=True, all_ratios_and_zero_suggestion_NA_verified=True,
        prediction_lock_sha256=sha(RUN/'prediction_lock.json'), score_sha256=sha(RUN/'score.json'),
        comparisons=comparisons, all_wrong_and_unknown_suggestions=failures,
        audit_source_sha256=sha(Path(__file__)), final_validation_eligible=False))
    print('Independent count checks:', checks, 'comparisons:', comparisons, flush=True)


if __name__ == '__main__': main()
