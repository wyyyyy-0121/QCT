#!/usr/bin/env python3
"""Verify M2 traces, then independently diagnose pool reachability and XML types."""
from collections import Counter
import gzip
import json
from pathlib import Path

from openpyxl.utils.cell import range_boundaries

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, verify_frozen
from spreadsheetbench2_scoring import verify_prediction_lock, sha256

EXPERIMENT = EVIDENCE / 'model_m2_trace'


def difference_class(change):
    old, new = change['input_formula'], change['golden_formula']
    old_array = isinstance(old, dict) and old.get('unsupported_formula_object') == 'ArrayFormula'
    new_array = isinstance(new, dict) and new.get('unsupported_formula_object') == 'ArrayFormula'
    if old_array and new_array:
        try:
            a, b = range_boundaries(old['ref']), range_boundaries(new['ref'])
            valid = all(isinstance(v, int) and v >= 1 for v in a + b)
            same_bounds = valid and a == b
        except (KeyError, TypeError, ValueError):
            same_bounds = False
        if same_bounds and old.get('text') == new.get('text') and isinstance(old.get('text'), str):
            return 'array_text_and_bounds_identical_representation_only'
        if same_bounds:
            return 'array_text_changed_same_bounds'
        return 'array_region_changed_or_unknown'
    if old_array or new_array:
        old_text = old.get('text') if old_array else old
        new_text = new.get('text') if new_array else new
        return 'formula_type_conversion_same_text_unknown' if old_text == new_text else 'formula_type_conversion_changed_or_missing_text_unknown'
    if isinstance(new, str):
        return 'ordinary_formula_added' if old is None else 'ordinary_formula_changed'
    if new is None:
        return 'formula_removed'
    return 'other_unknown'


def pool_diagnosis(trace, expected, baseline_status):
    partition, reasons, outside_types = Counter(), Counter(), Counter()
    pool_counts = Counter()
    if baseline_status != 'complete':
        partition['baseline_timeout_unobserved_pool'] += len(expected)
        return partition, reasons, outside_types, pool_counts
    rows = {row['cell']: row for row in trace['paper']['rows']}
    observed = trace['observed_formulas']
    for cell, correct in expected.items():
        if cell not in observed:
            partition['target_not_in_input_formula_inventory'] += 1
            outside_types[trace['input_xml_types'].get(cell, 'missing')] += 1
            continue
        if observed[cell] == correct:
            partition['formula_text_already_matches_type_or_metadata_unknown'] += 1
            continue
        fg = trace['candidate_trace']['fg'].get(cell, [])
        sg = trace['candidate_trace']['sg'].get(cell, {})
        fg_has = any(p['formula'] == correct for p in fg)
        sg_has = any(p['formula'] == correct for p in sg.get('candidates', []))
        if fg_has or sg_has:
            pool_counts['union_exact_reachable'] += 1
        if fg_has:
            pool_counts['fg_exact_reachable'] += 1
        if sg_has:
            pool_counts['sg_exact_reachable'] += 1
        if fg_has and sg_has:
            pool_counts['both_exact_reachable'] += 1
        if rows.get(cell, {}).get('suggested_formula') == correct:
            partition['final_exact'] += 1
            if not (fg_has or sg_has):
                raise ValueError('Exact paper output absent from both observed pools')
        elif fg_has or sg_has:
            partition['exact_in_observed_pool_but_not_final'] += 1
            flags = []
            if fg_has:
                flags.append('fg_emitted' if trace['fg_selected'].get(cell) == correct else 'fg_not_emitted')
            if sg_has:
                if trace['sg_selected'].get(cell) == correct:
                    flags.append('sg_emitted_then_fusion_overrode')
                elif sg.get('pre_gate_selection') == correct:
                    flags.append('sg_selected_then_gate_withheld')
                else:
                    flags.append('sg_not_selected')
            reasons['+'.join(flags)] += 1
        else:
            partition['no_exact_in_observed_pools'] += 1
            reasons['no_exact_fg_probed' if cell in trace['candidate_trace']['fg'] else 'no_exact_fg_not_triggered'] += 1
    return partition, reasons, outside_types, pool_counts


def main():
    baseline, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    output_lock_path = EXPERIMENT / 'output_lock.json'
    output_lock = json.loads(output_lock_path.read_text())
    if output_lock.get('scoring_may_begin') is not True or output_lock.get('all_observed_paper_outputs_identical') is not True:
        raise SystemExit('Trace lock not ready; no scoring')
    prelock = json.loads((EXPERIMENT / 'prelock.json').read_text())
    if sha256(EXPERIMENT / 'prelock.json') != output_lock['prelock_sha256'] or sha256(EVIDENCE / 'prediction_lock.json') != prelock['prediction_lock_sha256']:
        raise SystemExit('Trace or original prediction lock changed')
    for path, expected in prelock['source_sha256'].items():
        if sha256(ROOT / path) != expected:
            raise SystemExit('Trace source changed')
    for path, key in [('runs/runtime.json', 'runtime_sha256'), ('manifest.jsonl', 'manifest_sha256')]:
        if sha256(EXPERIMENT / path) != output_lock[key]:
            raise SystemExit('Trace runtime or manifest changed')
    outputs = {item['id']: item for item in output_lock['outputs']}
    originals = {item['id']: item for item in baseline['predictions']}
    if len(outputs) != 100 or len(output_lock['outputs']) != 100 or set(outputs) != set(originals):
        raise SystemExit('Trace must cover all 100 tasks')
    for task_id, item in outputs.items():
        if item['trace_status'] != 'complete' or item['baseline_status'] != originals[task_id]['status'] or sha256(item['path']) != item['sha256']:
            raise SystemExit('Trace missing or changed')
    # Candidate evidence is opened only after validation of all trace outputs.
    candidates_path = EVIDENCE / 'scoring/candidate_differences.json'
    candidates = json.loads(candidates_path.read_text())
    if candidates['prediction_lock_sha256'] != prelock['prediction_lock_sha256']:
        raise SystemExit('Candidate evidence belongs to another baseline')
    difference_counts, partition, reasons, outside_types, pool_counts = (Counter() for _ in range(5))
    tasks = []
    total_candidates, fg_cells, sg_cells = 0, 0, 0
    input_by_sha = {row['sha256'] for row in inputs['inputs']}
    for item in candidates['tasks']:
        task_id = item['id']
        with gzip.open(outputs[task_id]['path'], 'rt') as handle:
            trace = json.load(handle)
        if trace['labels_read'] != [] or trace['input_sha256'] != originals[task_id]['input_sha256'] or trace['input_sha256'] not in input_by_sha:
            raise SystemExit('Trace source/label-access identity differs')
        if originals[task_id]['status'] == 'complete' and (
                not trace.get('paper_content_identical') or trace['frozen_prediction_sha256'] != originals[task_id]['prediction_sha256']):
            raise SystemExit('Trace paper output identity differs')
        changes = item['formula_changes']
        for change in changes.values():
            difference_counts[difference_class(change)] += 1
        expected = {cell: v['golden_formula'] for cell, v in changes.items()
                    if isinstance(v['golden_formula'], str) and v['golden_formula'].startswith('=')}
        part, why, outside, pools = pool_diagnosis(trace, expected, originals[task_id]['status'])
        partition.update(part)
        reasons.update(why)
        outside_types.update(outside)
        pool_counts.update(pools)
        ct = trace.get('candidate_trace', {})
        fg_cells += len(ct.get('fg', {}))
        sg_cells += len(ct.get('sg', {}))
        total_candidates += sum(len(v) for v in ct.get('fg', {}).values())
        total_candidates += sum(len(v['candidates']) for v in ct.get('sg', {}).values())
        tasks.append(dict(id=task_id, group=item['group'], ordinary_targets=len(expected),
                          baseline_status=originals[task_id]['status'],
                          gap_partition=part, pool_counts=pools, nonformula_input_types=outside))
    if sum(partition.values()) != sum(row['ordinary_targets'] for row in tasks):
        raise SystemExit('Gap partition changed the ordinary-candidate denominator')
    denominator = sum(partition.values())
    result = dict(role='Revealed-development mechanism diagnosis, uncertified golden differences',
                  ordinary_candidate_denominator=denominator,
                  all_observed_paper_outputs_identical=True, traced_paper_tasks=90, input_inventory_tasks=100,
                  baseline_timeout_tasks=10, gap_partition=partition, selection_and_trigger_details=reasons,
                  nonformula_target_xml_types=outside_types, observed_pool_counts=pool_counts,
                  observed_pool_oracle_coverage=pool_counts['union_exact_reachable'] / denominator,
                  raw_difference_representation_audit=difference_counts,
                  trace_totals=dict(fg_triggered_cells=fg_cells, sg_repair_calls=sg_cells,
                                    distinct_candidates_per_cell_summed=total_candidates),
                  trace_output_lock_sha256=sha256(output_lock_path),
                  candidate_differences_sha256=sha256(candidates_path), tasks=tasks,
                  final_validation_eligible=False, business_accuracy=None)
    target = EXPERIMENT / 'diagnostic_metrics.json'
    with target.open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'tasks'}, indent=2))


if __name__ == '__main__':
    main()
