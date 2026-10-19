#!/usr/bin/env python3
"""Independently score locked source-equation conditions; no generator or SymPy import."""
from collections import Counter
from fractions import Fraction
import json
from pathlib import Path

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, verify_frozen
from spreadsheetbench2_scoring import sha256, verify_prediction_lock
from score_relation_m6 import formula_value, branch_expression

EXPERIMENT = EVIDENCE / 'model_m7_source'


def main():
    _, paper_inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(paper_inputs)
    lock_path = EXPERIMENT / 'input_lock.json'
    lock = json.loads(lock_path.read_text())
    for path, expected_hash in lock['files_sha256'].items():
        if sha256(Path(path)) != expected_hash:
            raise SystemExit('M7 locked artifact changed: ' + path)
    output_lock = json.loads((EXPERIMENT / 'output_lock.json').read_text())
    if output_lock['input_lock_sha256'] != sha256(lock_path) or output_lock['runtime_sha256'] != sha256(EXPERIMENT / 'runs/runtime.json'):
        raise SystemExit('Input/runtime lock changed')
    expected = json.loads((EXPERIMENT / 'scoring/expected.json').read_text())
    outputs = output_lock['outputs']
    if len(outputs) != len(expected) or {row['id'] for row in outputs} != set(expected):
        raise SystemExit('Output task set differs')
    counts, groups, mismatches, points, native_reachable = Counter(), {}, [], [], {}
    for row in outputs:
        key, target = row['id'], expected[row['id']]
        group = groups.setdefault(target['kind'], Counter())
        group['conditions'] += 1
        if row['status'] != 'complete':
            counts[row['status']] += 1
            group[row['status']] += 1
            mismatches.append(dict(id=key, terminal_status=row['status']))
            continue
        path = Path(row['path'])
        if sha256(path) != row['sha256']:
            raise SystemExit('Prediction changed')
        result = json.loads(path.read_text())
        request_path = EXPERIMENT / 'requests' / (key + '.json')
        request = json.loads(request_path.read_text())
        if result['request_sha256'] != sha256(request_path) or result['workbook_sha256'] != sha256(Path(request['workbook'])):
            raise SystemExit('Request/source provenance mismatch')
        counts[result['status']] += 1
        group[result['status']] += 1
        extracted = result.get('extracted_relation') is not None
        counts['equation_extracted'] += extracted
        group['equation_extracted'] += extracted
        observed = (result['status'], result['reason'], extracted)
        desired = (target['status'], target['reason'], target['extracted'])
        if observed != desired or bool(result.get('suggested_formula')) != target['repair']:
            mismatches.append(dict(id=key, observed=observed, expected=desired))
        if not result['original_unchanged'] or result['labels_read'] or result['automatic_field_mapping']:
            raise SystemExit('Evidence boundary changed')
        if result['status'] != 'propose':
            continue
        # Independently check the fixed source relation at distinct rational points.
        new, old = result['suggested_formula'], result['observed_formula']
        if request.get('branch'):
            old_active, new_active = branch_expression(old), branch_expression(new)
            if not old.endswith(old_active[1:] + ')') or not new.endswith(new_active[1:] + ')'):
                raise SystemExit('IF token text did not preserve original suffix')
            if old[:-len(old_active)] != new[:-len(new_active)]:
                raise SystemExit('IF guard/inactive prefix changed')
        else:
            old_active, new_active = old, new
        native_reachable[key] = result['native_pool_has_equivalent']
        for q, d in [(10, 2), (5, 10), (Fraction(3, 2), Fraction(1, 2)), (21, 7), (11, 3)]:
            correct = Fraction(q) / Fraction(d) * 100
            before = formula_value(old_active, request['references'], q, d)
            after = formula_value(new_active, request['references'], q, d)
            passed = after == correct and before != correct
            points.append(dict(id=key, q=str(q), d=str(d), expected=str(correct),
                               old=str(before), new=str(after), passed=passed))
            if not passed:
                mismatches.append(dict(id=key, failed_point=[str(q), str(d)]))
    runtime = json.loads((EXPERIMENT / 'runs/runtime.json').read_text())
    summary = dict(experiment='M7 explicit source-equation reader', task_count=len(outputs),
                   counts=dict(counts), groups={name: dict(value) for name, value in groups.items()},
                   expectation_mismatches=mismatches, acceptance_passed=not mismatches,
                   fraction_checks=len(points), fraction_passed=sum(row['passed'] for row in points),
                   native_pool_has_equivalent_for_proposals=native_reachable,
                   original_paper_preserved=True, automatic_field_mapping=False,
                   independent_human_annotation=False, natural_repair_accuracy_established=False,
                   natural_validation_sources=0, natural_validation_families=0,
                   final_validation_eligible=False, runtime={key: runtime[key] for key in (
                       'requested_worker_count', 'worker_count', 'wall_seconds', 'child_cpu_seconds',
                       'aggregate_peak_rss_bytes_sampled', 'all_tasks_complete')},
                   source_input_lock_sha256=sha256(lock_path),
                   source_output_lock_sha256=sha256(EXPERIMENT / 'output_lock.json'))
    details = EXPERIMENT / 'independent_score.json'
    with details.open('x') as handle:
        json.dump(dict(summary=summary, point_checks=points), handle, indent=2)
        handle.write('\n')
    destination = ROOT / 'MODEL_M7_SOURCE_SUMMARY.json'
    with destination.open('x') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps(summary, indent=2))
    if mismatches:
        raise SystemExit('M7 rejected: see preserved mismatches')


if __name__ == '__main__':
    main()
