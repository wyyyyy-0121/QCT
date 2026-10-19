#!/usr/bin/env python3
"""Independently audit and score frozen SG-priority ablation; no fusion import."""
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, verify_frozen
from spreadsheetbench2_scoring import exact_metrics, sha256, verify_prediction_lock

EXPERIMENT = EVIDENCE / 'model_m9_fusion'
M2 = EVIDENCE / 'model_m2_trace'


def aggregate(records):
    counts = {name: sum(row[name] for row in records) for name in (
        'confirmed_errors', 'all_suggestions', 'exact_correct', 'suggestions_on_errors',
        'wrong_formula_on_errors', 'no_suggestion_on_errors', 'suggestions_outside_confirmed_errors')}
    counts['candidate_formula_differences'] = counts.pop('confirmed_errors')
    counts['precision_against_candidates'] = counts['exact_correct'] / counts['all_suggestions'] if counts['all_suggestions'] else None
    counts['candidate_repair_coverage'] = counts['exact_correct'] / counts['candidate_formula_differences'] if counts['candidate_formula_differences'] else None
    return counts


def main():
    baseline, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    lock_path = EXPERIMENT / 'input_lock.json'
    lock = json.loads(lock_path.read_text())
    for name, digest in lock['files_sha256'].items():
        if sha256(Path(name)) != digest:
            raise SystemExit('M9 locked artifact changed: ' + name)
    terminal = json.loads((EXPERIMENT / 'output_lock.json').read_text())
    if (not terminal.get('scoring_may_begin') or terminal['input_lock_sha256'] != sha256(lock_path)
            or terminal['runtime_sha256'] != sha256(EXPERIMENT / 'runs/runtime.json')):
        raise SystemExit('M9 output lock not ready/changed')
    complete_ids = {row['id'] for row in baseline['predictions'] if row['status'] == 'complete'}
    outputs = {row['id']: row for row in terminal['outputs']}
    inherited = [dict(id=row['id'], status=row['status']) for row in baseline['predictions'] if row['status'] != 'complete']
    if (len(outputs) != 90 or len(terminal['outputs']) != 90 or set(outputs) != complete_ids
            or terminal['inherited_terminal_states'] != inherited or lock['inherited_terminal_states'] != inherited):
        raise SystemExit('M9 terminal accounting changed')
    for row in outputs.values():
        if row['status'] == 'complete' and sha256(Path(row['path'])) != row['sha256']:
            raise SystemExit('Prediction changed')
    # Only now load the previously exposed candidate labels.
    candidate_path = EVIDENCE / 'scoring/candidate_differences.json'
    candidates = json.loads(candidate_path.read_text())
    if candidates['prediction_lock_sha256'] != lock['source_prediction_lock_sha256']:
        raise SystemExit('Candidate evidence belongs to another baseline')
    differences = {row['id']: row for row in candidates['tasks']}
    traces = {row['id']: row for row in json.loads((M2 / 'output_lock.json').read_text())['outputs']}
    records = {'paper': [], 'm9': []}
    families = {name: defaultdict(list) for name in records}
    switches, original_correct, retained, gains, losses, source_changes, terminals = (Counter() for _ in range(7))
    task_rows, cell_details = [], []
    for item in baseline['predictions']:
        task_id = item['id']
        expected = {cell: value['golden_formula'] for cell, value in differences[task_id]['formula_changes'].items()
                    if isinstance(value['golden_formula'], str) and value['golden_formula'].startswith('=')}
        family = differences[task_id]['group']
        paper = new = None
        new_status = item['status']
        task_switches = 0
        if item['status'] == 'complete':
            with gzip.open(traces[task_id]['path'], 'rt') as handle:
                trace = json.load(handle)
            paper = dict(observed_formulas=trace['observed_formulas'], paper=trace['paper'])
            new_status = outputs[task_id]['status']
            if new_status == 'complete':
                new = json.loads(Path(outputs[task_id]['path']).read_text())
                if (new['trace_sha256'] != traces[task_id]['sha256'] or new['input_sha256'] != item['input_sha256']
                        or new['labels_read'] or new['observed_formulas'] != paper['observed_formulas']):
                    raise SystemExit('M9 provenance or original formulas differ')
                old_rows, new_rows = paper['paper']['rows'], new['paper']['rows']
                if len(old_rows) != len(new_rows) or {k:v for k,v in new['paper'].items() if k != 'rows'} != {
                        k:v for k,v in paper['paper'].items() if k != 'rows'}:
                    raise SystemExit('M9 row/non-row metadata changed')
                for old, after in zip(old_rows, new_rows):
                    cell = old['cell']
                    observed = paper['observed_formulas'].get(cell)
                    old_formula = old.get('suggested_formula')
                    fg, sg = trace['fg_selected'].get(cell), trace['sg_selected'].get(cell)
                    should_switch = (old.get('suggestion_source') == 'formulaguard-v5'
                        and isinstance(fg, str) and fg.startswith('=') and old_formula == fg and fg != observed
                        and isinstance(sg, str) and sg.startswith('=') and sg != observed and sg != fg)
                    if should_switch:
                        restored = dict(after)
                        if (restored.pop('m9_decision', None) != 'prefer_emitted_sg_on_fg_conflict'
                                or restored.pop('m9_previous_formula', None) != old_formula
                                or restored['suggested_formula'] != sg
                                or restored['suggestion_source'] != 'm9-emitted-structuralguard'):
                            raise SystemExit('M9 switched candidate was not actual emitted SG')
                        restored.update(suggested_formula=old_formula, suggestion_source=old['suggestion_source'])
                        if restored != old:
                            raise SystemExit('M9 changed unrelated detection/ranking fields')
                        task_switches += 1
                        switches['all'] += 1
                        switches['on_candidate_targets' if cell in expected else 'outside_candidate_targets'] += 1
                        before_ok, after_ok = old_formula == expected.get(cell), sg == expected.get(cell)
                        if before_ok:
                            losses[family] += 1
                        if after_ok:
                            gains[family] += 1
                        switches['both_nonmatching'] += not before_ok and not after_ok
                        cell_details.append(dict(task_id=task_id, cell=cell, group=family, original_candidate=old_formula,
                                                 replacement=sg, gain=after_ok, loss=before_ok, target_known=cell in expected))
                        source_changes[str(old.get('suggestion_source'))] += 1
                    elif after != old:
                        raise SystemExit('M9 changed a non-conflict row')
                    if old_formula == expected.get(cell) and cell in expected:
                        original_correct['all'] += 1
                        retained['all'] += after.get('suggested_formula') == old_formula
                if task_switches != new['changed_selection_count']:
                    raise SystemExit('M9 change counter differs')
        terminals[new_status] += 1
        for name, prediction, status in [('paper', paper, item['status']), ('m9', new, new_status)]:
            result = exact_metrics(prediction, expected, terminal_status=status)
            records[name].append(result)
            families[name][family].append(result)
        task_rows.append(dict(id=task_id, group=family, baseline_status=item['status'], m9_status=new_status,
                              ordinary_targets=len(expected), switched=task_switches))
    overall = {name: aggregate(values) for name, values in records.items()}
    old, new = overall['paper'], overall['m9']
    if (old['all_suggestions'], old['exact_correct'], old['candidate_formula_differences']) != (97037, 449, 10948):
        raise SystemExit('Independent baseline totals differ')
    if sum(gains.values()) - sum(losses.values()) != new['exact_correct'] - old['exact_correct']:
        raise SystemExit('Gain/loss decomposition inconsistent')
    checks = dict(all_90_postprocess_tasks_complete=all(row['status'] == 'complete' for row in outputs.values()),
                  suggestions_do_not_increase=new['all_suggestions'] <= old['all_suggestions'],
                  retains_at_least_95pct_original_exact=retained['all'] >= .95 * old['exact_correct'],
                  net_at_least_50_exact=new['exact_correct'] - old['exact_correct'] >= 50,
                  candidate_precision_does_not_decrease=(new['precision_against_candidates'] is not None and
                      new['precision_against_candidates'] >= old['precision_against_candidates']))
    runtime = json.loads((EXPERIMENT / 'runs/runtime.json').read_text())
    summary = dict(experiment='M9 emitted SG priority on actual FG/SG conflicts',
                   role='Exposed-development fusion ablation; uncertified ordinary golden differences', overall=overall,
                   selection_changes=dict(switches), exact_gained=sum(gains.values()), exact_lost=sum(losses.values()),
                   original_exact_retained=retained['all'], exact_gained_by_group=dict(gains), exact_lost_by_group=dict(losses),
                   source_changes=dict(source_changes), terminal_states=dict(terminals), continuation_checks=checks,
                   continuation_gate_passed=all(checks.values()),
                   decision='independent_validation_needed' if all(checks.values()) else 'reject_fixed_sg_priority_no_tuning',
                   by_group={name: {key: aggregate(value) for key,value in groups.items()} for name, groups in families.items()},
                   business_accuracy=None, final_validation_eligible=False, natural_validation_sources=0,
                   natural_validation_families=0, candidate_differences_sha256=sha256(candidate_path),
                   input_lock_sha256=sha256(lock_path), output_lock_sha256=sha256(EXPERIMENT / 'output_lock.json'),
                   runtime={key: runtime[key] for key in ('requested_worker_count','worker_count','wall_seconds',
                       'child_cpu_seconds','aggregate_peak_rss_bytes_sampled','all_tasks_complete')})
    with (EXPERIMENT / 'independent_score.json').open('x') as handle:
        json.dump(dict(summary=summary, tasks=task_rows, changed_cells=cell_details), handle, indent=2)
        handle.write('\n')
    with (ROOT / 'MODEL_M9_FUSION_SUMMARY.json').open('x') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps({key:value for key,value in summary.items() if key != 'by_group'}, indent=2))


if __name__ == '__main__':
    main()
