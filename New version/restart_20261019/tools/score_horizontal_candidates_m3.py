#!/usr/bin/env python3
"""Post-lock independent pool reachability; no chosen repair accuracy claimed."""
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, verify_frozen
from spreadsheetbench2_scoring import verify_prediction_lock, sha256

EXPERIMENT = EVIDENCE / 'model_m3_horizontal'


def read_gzip(path):
    with gzip.open(path, 'rt') as handle:
        return json.load(handle)


def native_pool(trace):
    result = defaultdict(set)
    for cell, probes in trace['candidate_trace']['fg'].items():
        result[cell].update(p['formula'] for p in probes)
    for cell, data in trace['candidate_trace']['sg'].items():
        result[cell].update(p['formula'] for p in data['candidates'])
    return result


def main():
    baseline, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    lock = json.loads((EXPERIMENT / 'output_lock.json').read_text())
    if lock.get('scoring_may_begin') is not True:
        raise SystemExit('M3 output lock not ready')
    prelock = json.loads((EXPERIMENT / 'prelock.json').read_text())
    if sha256(EXPERIMENT / 'prelock.json') != lock['prelock_sha256'] or sha256(EVIDENCE / 'prediction_lock.json') != prelock['prediction_lock_sha256']:
        raise SystemExit('Prelock or original baseline differs')
    for path, expected in prelock['source_sha256'].items():
        if sha256(ROOT / path) != expected:
            raise SystemExit('M3 source changed')
    for path, key in [('manifest.jsonl', 'manifest_sha256'), ('runs/runtime.json', 'runtime_sha256')]:
        if sha256(EXPERIMENT / path) != lock[key]:
            raise SystemExit('M3 manifest/runtime changed')
    m2_path = EVIDENCE / 'model_m2_trace/output_lock.json'
    if sha256(m2_path) != prelock['m2_output_lock_sha256']:
        raise SystemExit('M2 pool lock changed')
    m2_lock = json.loads(m2_path.read_text())
    if not m2_lock.get('scoring_may_begin'):
        raise SystemExit('M2 not valid')
    old_outputs = {o['id']: o for o in m2_lock['outputs']}
    outputs = {o['id']: o for o in lock['outputs']}
    complete = {t['id'] for t in baseline['predictions'] if t['status'] == 'complete'}
    if len(outputs) != len(lock['outputs']) or set(outputs) != complete:
        raise SystemExit('M3 output task set differs')
    if set(lock['inherited_timeout_ids']) != {t['id'] for t in baseline['predictions'] if t['status'] != 'complete'}:
        raise SystemExit('M3 timeout accounting differs')
    for output in list(outputs.values()) + list(old_outputs.values()):
        if sha256(output['path']) != output['sha256']:
            raise SystemExit('Candidate or original pool evidence changed')
    # All new output identities are checked before opening candidate labels.
    candidates_path = EVIDENCE / 'scoring/candidate_differences.json'
    candidates = json.loads(candidates_path.read_text())
    if candidates['prediction_lock_sha256'] != prelock['prediction_lock_sha256']:
        raise SystemExit('Candidate baseline differs')
    baseline_by_id = {t['id']: t for t in baseline['predictions']}
    counts, statuses = Counter(), Counter()
    by_group = defaultdict(Counter)
    for task in candidates['tasks']:
        task_id = task['id']
        expected = {cell: c['golden_formula'] for cell, c in task['formula_changes'].items()
                    if isinstance(c['golden_formula'], str) and c['golden_formula'].startswith('=')}
        counts['ordinary_candidate_denominator'] += len(expected)
        if task_id not in outputs:
            counts['baseline_timeout_unobserved_targets'] += len(expected)
            continue
        new = read_gzip(outputs[task_id]['path'])
        old_trace = read_gzip(old_outputs[task_id]['path'])
        if new['frozen_prediction_sha256'] != baseline_by_id[task_id]['prediction_sha256'] or new['labels_read'] != [] or new['selected_repairs'] != [] or new['automatic_edit_applied'] is not False:
            raise SystemExit('M3 input identity, access or candidate-only semantics differ')
        old = native_pool(old_trace)
        horizontal = {cell: {p['formula'] for p in values} for cell, values in new['candidate_pool'].items()}
        statuses.update(new['target_status_counts'])
        counts['horizontal_candidates'] += sum(len(v) for v in horizontal.values())
        counts['horizontal_candidates_distinct_from_native'] += sum(len(v - old.get(c, set())) for c, v in horizontal.items())
        counts['horizontal_target_cells'] += len(horizontal)
        for cell, formula in expected.items():
            orig_hit = formula in old.get(cell, set())
            new_hit = formula in horizontal.get(cell, set())
            counts['native_exact_reachable'] += int(orig_hit)
            counts['horizontal_exact_reachable'] += int(new_hit)
            counts['union_exact_reachable'] += int(orig_hit or new_hit)
            counts['newly_exact_reachable'] += int(new_hit and not orig_hit)
            by_group[task['group']]['ordinary_targets'] += 1
            by_group[task['group']]['newly_exact_reachable'] += int(new_hit and not orig_hit)
    newly = counts['newly_exact_reachable']
    ratio = counts['horizontal_candidates_distinct_from_native'] / newly if newly else None
    checks = dict(at_least_100_additional_exact_targets=newly >= 100,
                  at_most_100_new_candidates_per_new_exact_target=ratio is not None and ratio <= 100)
    result = dict(role='Candidate generation only on revealed data; not repair accuracy', counts=counts,
                  candidate_expansion_per_new_exact_target=ratio,
                  union_oracle_coverage=counts['union_exact_reachable'] / counts['ordinary_candidate_denominator'],
                  continuation_checks=checks, continue_to_selector_research=all(checks.values()),
                  target_status_counts=statuses, by_group=by_group,
                  output_lock_sha256=sha256(EXPERIMENT / 'output_lock.json'),
                  candidate_differences_sha256=sha256(candidates_path),
                  chosen_repairs=0, business_accuracy=None, final_validation_eligible=False)
    with (EXPERIMENT / 'diagnostic_metrics.json').open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
