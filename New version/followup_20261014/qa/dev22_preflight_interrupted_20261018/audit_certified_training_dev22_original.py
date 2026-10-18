"""Rebuild certified training pairs independently; never call the constructor."""
from collections import Counter, defaultdict
from pathlib import Path
import argparse
import hashlib
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_selector_dev5 import read, save, sha
from run_certified_learning_dev22 import LABELS, RUN, verify_preparation, selection_digest
from run_candidate_learning_dev18 import weights
from build_keep_features_dev21 import BASE, case_path


def audit(check_runtime=False):
    verify_preparation(); summaries = []; coverage = Counter()
    truth = read(BASE/'heldout_truth.json.gz')['cases']
    metadata = {case: (t['origin_group'], t['family']) for case, t in truth.items()}
    for item in read(BASE/'public_index.json'):
        case = item['case']; t = truth[case]; expected = t['expected_formulas']; errors = set(t['errors'])
        payload = read(BASE/'features'/(case_path(case)+'.json.gz'))
        labels = read(BASE/'case_labels'/(case_path(case)+'.json.gz'))
        states = read(LABELS/'author_case_states'/(case_path(case)+'.json.gz'))['alternatives']
        target_cells = sorted({c['cell'] for c in payload['candidates']})
        assert len(states) == len(target_cells)+len(payload['candidates'])
        for cell, state in zip(target_cells, states):
            y = None if cell not in expected else (0 if cell in errors else 1)
            assert state == dict(id='__observed_formula__', cell=cell, case=case, kind='keep', label=y)
        for candidate, state in zip(payload['candidates'], states[len(target_cells):]):
            cell = candidate['cell']
            if cell not in expected: y = None
            elif cell in errors: y = labels[candidate['id']]
            elif candidate['formula'] == expected[cell]: y = 1
            else: y = None
            assert state == dict(id=candidate['id'], cell=cell, case=case, kind='candidate', label=y)
    del truth, payload, labels, states
    runtime = {r['fold']: r for r in read(RUN/'runtime.json')['folds']} if check_runtime else {}
    for fold in read(LABELS/'fold_index.json')['folds']:
        data = read(LABELS/fold['train_label_file']); rows = data['rows']; states = data['alternatives']
        assert data['training_cases'] == fold['train_cases'] and data['heldout_cases'] == fold['test_cases']
        assert not set(fold['train_cases']) & set(fold['test_cases'])
        grouped = defaultdict(list)
        for state in states:
            assert state['case'] in fold['train_cases'] and state['case'] not in fold['test_cases']
            grouped[state['case'], state['cell']].append(state)
        offset = 0
        for case in fold['train_cases']:
            original = read(LABELS/'author_case_states'/(case_path(case)+'.json.gz'))['alternatives']
            assert states[offset:offset+len(original)] == original
            offset += len(original)
        assert offset == len(states)
        expected = []
        order = {case: n for n, case in enumerate(fold['train_cases'])}
        for (case, cell), options in sorted(grouped.items(), key=lambda item: (order[item[0][0]], item[0][1])):
            assert sum(r['kind'] == 'keep' for r in options) == 1
            assert len({r['id'] for r in options}) == len(options)
            positive = sorted((r['id'] for r in options if r['label'] == 1))
            negative = sorted(r['id'] for r in options if r['kind'] == 'candidate' and r['label'] == 0)[:32]
            negative += [r['id'] for r in options if r['kind'] == 'keep' and r['label'] == 0]
            for left in positive:
                for right in negative:
                    expected.extend([(case, cell, left, right, 1), (case, cell, right, left, 0)])
        actual = [tuple(r[k] for k in ['case', 'cell', 'left_id', 'right_id', 'label']) for r in rows]
        assert actual == expected
        assert all(r['source'] != fold['origin'] for r in rows)
        assert all((r['source'], r['family']) == metadata[r['case']] for r in rows)
        w = weights(rows); assert all(w[n] == w[n+1] for n in range(0, len(w), 2))
        # Independent source/family/case balancing formula.
        source_families = defaultdict(set); family_cases = defaultdict(set)
        counts = Counter(r['case'] for r in rows)
        for r in rows:
            source_families[r['source']].add(r['family']); family_cases[r['source'], r['family']].add(r['case'])
        raw = [1/(len(source_families[r['source']])*len(family_cases[r['source'], r['family']])*counts[r['case']]) for r in rows]
        scale = len(raw)/sum(raw); source_sums = defaultdict(float)
        for r, value, weight in zip(rows, raw, w):
            assert abs(value*scale-weight) < 1e-8
            source_sums[r['source']] += weight
        assert max(source_sums.values())-min(source_sums.values()) < 1e-5
        digest = hashlib.sha256('\n'.join('\t'.join(map(str, r)) for r in expected).encode()).hexdigest()
        assert digest == selection_digest(rows)
        summary = dict(fold=fold['id'], directed_pairs=len(rows), positive=sum(r['label'] for r in rows),
            negative=sum(1-r['label'] for r in rows), selection_sha256=digest, source_weight_sums=dict(source_sums))
        if check_runtime:
            for key in ['directed_pairs', 'positive', 'negative', 'selection_sha256']: assert runtime[fold['id']][key] == summary[key]
            assert runtime[fold['id']]['features'] == 712
        summaries.append(summary); print(summary, flush=True)
        del data, rows, states, grouped, actual, expected, w, raw
    for case in read(LABELS/'state_counts.json'):
        coverage.update(case['states']); coverage['targets_without_certified_contrast'] += case['targets_without_certified_contrast']
        coverage['targets'] += case['targets']; coverage['directed_pairs'] += case['directed_pairs']
    suffix = 'RUNTIME' if check_runtime else 'PRETRAIN'
    p = ROOT/('qa/CERTIFIED_LEARNING_DEV22_'+suffix+'_AUDIT_20261018.json'); assert not p.exists()
    save(p, dict(folds=summaries, unique_case_state_counts=dict(coverage), pairs_match_independent_reconstruction=True,
        wrong_wrong_and_unknown_pairs_absent=True, mirrored_weights_equal=True, source_balancing_verified=True,
        all_case_states_match_independent_upstream_mapping=True,
        preparation_lock_sha256=sha(LABELS/'preparation_lock.json'), audit_source_sha256=sha(Path(__file__)), final_validation_eligible=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--check-runtime', action='store_true')
    audit(parser.parse_args().check_runtime)
