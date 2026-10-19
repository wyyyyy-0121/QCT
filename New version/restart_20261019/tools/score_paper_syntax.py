#!/usr/bin/env python3
"""Post-lock syntax inventory linked to existing candidate differences."""
from collections import Counter, defaultdict
import gzip
import json

from diagnose_paper_syntax import EXPERIMENT, classify
from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, verify_frozen
from spreadsheetbench2_scoring import sha256, verify_prediction_lock


def read_gzip(path):
    with gzip.open(path, 'rt') as handle:
        return json.load(handle)


def main():
    baseline, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    lock = json.loads((EXPERIMENT / 'output_lock.json').read_text())
    prelock = json.loads((EXPERIMENT / 'prelock.json').read_text())
    if not lock.get('scoring_may_begin') or sha256(EXPERIMENT / 'prelock.json') != lock['prelock_sha256'] or sha256(EVIDENCE / 'prediction_lock.json') != prelock['prediction_lock_sha256']:
        raise SystemExit('Syntax lock not ready or changed')
    for path, expected in prelock['source_sha256'].items():
        if sha256(ROOT / path) != expected:
            raise SystemExit('Syntax implementation changed')
    for path, key in [('manifest.jsonl', 'manifest_sha256'), ('runs/runtime.json', 'runtime_sha256')]:
        if sha256(EXPERIMENT / path) != lock[key]:
            raise SystemExit('Syntax runtime or manifest changed')
    outputs = {r['id']: r for r in lock['outputs']}
    complete = {r['id']: r for r in baseline['predictions'] if r['status'] == 'complete'}
    if len(outputs) != 90 or len(outputs) != len(lock['outputs']) or set(outputs) != set(complete):
        raise SystemExit('Syntax coverage differs from baseline')
    m2_path = EVIDENCE / 'model_m2_trace/output_lock.json'
    m2 = json.loads(m2_path.read_text())
    if not m2.get('scoring_may_begin'):
        raise SystemExit('M2 pool not ready')
    m2_outputs = {r['id']: r for r in m2['outputs']}
    for row in list(outputs.values()) + list(m2_outputs.values()):
        if sha256(row['path']) != row['sha256']:
            raise SystemExit('Diagnosis or trace output changed')
    candidates_path = EVIDENCE / 'scoring/candidate_differences.json'
    candidates = json.loads(candidates_path.read_text())
    if candidates['prediction_lock_sha256'] != prelock['prediction_lock_sha256']:
        raise SystemExit('Candidate baseline differs')
    counts, failure_types, flags, unsupported_functions = (Counter() for _ in range(4))
    target_pairs = Counter()
    ungenerated_by_type, target_functions = Counter(), Counter()
    by_group = defaultdict(Counter)
    for task in candidates['tasks']:
        expected = {cell: c['golden_formula'] for cell, c in task['formula_changes'].items()
                    if isinstance(c['golden_formula'], str) and c['golden_formula'].startswith('=')}
        counts['ordinary_candidate_denominator'] += len(expected)
        if task['id'] not in outputs:
            counts['baseline_timeout_targets'] += len(expected)
            continue
        diagnosis = read_gzip(outputs[task['id']]['path'])
        if diagnosis['labels_read'] != [] or diagnosis['frozen_prediction_sha256'] != complete[task['id']]['prediction_sha256']:
            raise SystemExit('Syntax input identity differs')
        trace = read_gzip(m2_outputs[task['id']]['path'])
        for row in diagnosis['cells'].values():
            counts['all_input_formula_cells'] += 1
            counts['input_' + row['status']] += 1
            if row['status'] == 'unsupported':
                failure_types[row['primary']] += 1
                flags.update(row['features'])
            elif row['unsupported_functions']:
                counts['parsed_cells_with_unsupported_functions'] += 1
                unsupported_functions.update(row['unsupported_functions'])
        fg, sg = trace['candidate_trace']['fg'], trace['candidate_trace']['sg']
        for cell, formula in expected.items():
            old = diagnosis['cells'].get(cell)
            target = classify(formula)
            old_kind = ('not_in_formula_inventory' if old is None else
                        ('parsed' if old['status'] == 'parsed' else old['primary']))
            new_kind = 'parsed' if target['status'] == 'parsed' else target['primary']
            target_pairs[old_kind + ' -> ' + new_kind] += 1
            if target['status'] == 'parsed':
                target_functions.update(target['unsupported_functions'])
            if old is not None and old['status'] == 'unsupported':
                counts['ordinary_targets_with_unsupported_original'] += 1
                by_group[task['group']]['targets_with_unsupported_original'] += 1
            pool = {p['formula'] for p in fg.get(cell, [])} | {
                p['formula'] for p in sg.get(cell, {}).get('candidates', [])}
            if old is not None and formula not in pool:
                ungenerated_by_type[old_kind + ' -> ' + new_kind] += 1
    result = dict(role='Static syntax and function-support diagnosis; not execution success or repair accuracy',
                  counts=counts, all_input_parse_failure_primary=failure_types,
                  all_input_failure_features_nonexclusive=flags,
                  parsed_input_unsupported_function_cells_by_name=unsupported_functions,
                  ordinary_target_original_to_expected_syntax=target_pairs,
                  no_exact_observed_pool_by_syntax=ungenerated_by_type,
                  parsed_expected_unsupported_function_cells_by_name=target_functions,
                  by_group=by_group, output_lock_sha256=sha256(EXPERIMENT / 'output_lock.json'),
                  m2_output_lock_sha256=sha256(m2_path),
                  candidate_differences_sha256=sha256(candidates_path),
                  final_validation_eligible=False, business_accuracy=None)
    with (EXPERIMENT / 'diagnostic_metrics.json').open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
