#!/usr/bin/env python3
"""Independently score locked real-workbook M9 on all225 faultsfw xlsx files."""
from collections import Counter, defaultdict
import json
from pathlib import Path

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, verify_frozen
from spreadsheetbench2_scoring import exact_metrics, sha256, verify_prediction_lock

EXPERIMENT = EVIDENCE / 'model_m9_external'
FAULTS = ROOT / 'source_evidence/raw/zenodo_581672'
HISTORICAL = ROOT / 'benchmark_runs_faultsfw_v1'


def aggregate(records):
    values = {key: sum(row[key] for row in records) for key in (
        'confirmed_errors', 'all_suggestions', 'exact_correct', 'suggestions_on_errors',
        'wrong_formula_on_errors', 'no_suggestion_on_errors', 'suggestions_outside_confirmed_errors')}
    values['precision_all_suggestions'] = values['exact_correct'] / values['all_suggestions'] if values['all_suggestions'] else None
    values['correct_repair_coverage'] = values['exact_correct'] / values['confirmed_errors'] if values['confirmed_errors'] else None
    return values


def main():
    amendment_path = EXPERIMENT / 'scoring_amendment_lock.json'
    amendment = json.loads(amendment_path.read_text())
    for name, expected_hash in amendment['files_sha256'].items():
        if sha256(Path(name)) != expected_hash:
            raise SystemExit('Scoring amendment artifact changed: ' + name)
    _, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    lock_path = EXPERIMENT / 'input_lock.json'
    lock = json.loads(lock_path.read_text())
    for name, expected in lock['files_sha256'].items():
        if sha256(Path(name)) != expected:
            raise SystemExit('Locked artifact changed: ' + name)
    terminal = json.loads((EXPERIMENT / 'output_lock.json').read_text())
    if (not terminal.get('scoring_may_begin') or terminal['input_lock_sha256'] != sha256(lock_path)
            or terminal['runtime_sha256'] != sha256(EXPERIMENT / 'runs/runtime.json')):
        raise SystemExit('External output lock invalid')
    original_runtime = json.loads((HISTORICAL / 'runtime.json').read_text())
    old_tasks = {row['id']: row for row in original_runtime['tasks']}
    outputs = {row['id']: row for row in terminal['outputs']}
    if len(outputs) != 225 or len(terminal['outputs']) != 225 or set(outputs) != set(old_tasks):
        raise SystemExit('External M9 task coverage changed')
    for item in outputs.values():
        if item['status'] == 'complete' and sha256(Path(item['path'])) != item['sha256']:
            raise SystemExit('Output changed')
    # Only after every terminal state/output is validated may truth be loaded.
    inventory = json.loads((FAULTS / 'score_inventory.json').read_text())
    scored = {row['id']: row for row in inventory['records']}
    if len(scored) != 219:
        raise SystemExit('Historical truth scope changed')
    records = {'paper': [], 'm9': []}
    families = {name: defaultdict(list) for name in records}
    gains, losses, retained, changed, statuses = Counter(), Counter(), Counter(), Counter(), Counter()
    rows, discrepancies = [], []
    for task_id, task in old_tasks.items():
        historical = json.loads((Path(task['cwd']) / 'prediction.json').read_text())
        expected = scored.get(task_id, {}).get('truth', {})
        family = scored.get(task_id, {}).get('template', 'unknown_truth')
        item = outputs[task_id]
        new = None
        if item['status'] == 'complete':
            new = json.loads(Path(item['path']).read_text())
            if (new['original_paper'] != historical['paper']
                    or new['observed_formulas'] != historical['observed_formulas']
                    or new['input_sha256'] != historical['input_sha256']
                    or new['labels_read'] or not new['original_unchanged']):
                discrepancies.append(dict(id=task_id, reason='baseline_or_provenance_differs'))
            old_rows, new_rows = historical['paper']['rows'], new['paper']['rows']
            if len(old_rows) != len(new_rows) or {k:v for k,v in new['paper'].items() if k != 'rows'} != {
                    k:v for k,v in historical['paper'].items() if k != 'rows'}:
                raise SystemExit('Unexpected paper metadata changes')
            actual_changes = 0
            for before, after in zip(old_rows, new_rows):
                cell = before['cell']
                original = historical['observed_formulas'].get(cell)
                fg, sg = new['fg_selected'].get(cell), new['sg_selected'].get(cell)
                condition = (before.get('suggestion_source') == 'formulaguard-v5'
                    and isinstance(fg, str) and fg.startswith('=') and fg == before.get('suggested_formula') and fg != original
                    and isinstance(sg, str) and sg.startswith('=') and sg != original and sg != fg)
                if condition:
                    restored = dict(after)
                    if (restored.pop('m9_decision', None) != 'prefer_emitted_sg_on_fg_conflict'
                            or restored.pop('m9_previous_formula', None) != fg
                            or restored.get('suggested_formula') != sg
                            or restored.get('suggestion_source') != 'm9-emitted-structuralguard'):
                        raise SystemExit('External M9 used an unregistered change')
                    restored.update(suggested_formula=fg, suggestion_source=before['suggestion_source'])
                    if restored != before:
                        raise SystemExit('Unrelated fields changed')
                    actual_changes += 1
                    changed['all'] += 1
                    changed['known_fault_targets' if cell in expected else 'outside_known_fault_targets'] += 1
                    if fg == expected.get(cell):
                        losses[family] += 1
                    if sg == expected.get(cell):
                        gains[family] += 1
                elif before != after:
                    raise SystemExit('External M9 changed non-conflict row')
                if cell in expected and before.get('suggested_formula') == expected[cell]:
                    retained['original'] += 1
                    retained['kept'] += after.get('suggested_formula') == expected[cell]
            if new['changed_selection_count'] != actual_changes:
                raise SystemExit('External M9 switch accounting differs')
        statuses[item['status']] += 1
        for name, prediction, status in [('paper', historical, 'complete'), ('m9', new, item['status'])]:
            metrics = exact_metrics(prediction, expected, terminal_status=status)
            records[name].append(metrics)
            families[name][family].append(metrics)
        rows.append(dict(id=task_id, template=family, truth_available=task_id in scored,
                         confirmed_faults=len(expected), status=item['status']))
    overall = {name: aggregate(values) for name, values in records.items()}
    old, new = overall['paper'], overall['m9']
    if (old['exact_correct'],old['all_suggestions'],old['confirmed_errors']) != (149,2022,374):
        raise SystemExit('Historical scoring mismatch')
    checks = dict(all225_complete=statuses['complete'] == 225, original_paper_identical=not discrepancies,
                  suggestions_do_not_increase=new['all_suggestions'] <= 2022,
                  exact_repairs_do_not_decrease=new['exact_correct'] >= 149,
                  precision_does_not_decrease=new['precision_all_suggestions'] is not None
                      and new['precision_all_suggestions'] >= 149/2022,
                  original_exact_at_least_95pct_retained=retained['kept'] >= .95*149)
    runtime = json.loads((EXPERIMENT / 'runs/runtime.json').read_text())
    summary = dict(experiment='M9 real-workbook entrypoint; unchanged rule on faultsfw225',
                   exposure='Already exposed public injected-fault development benchmark; not blind or natural',
                   overall=overall, exact_gained=sum(gains.values()), exact_lost=sum(losses.values()),
                   original_exact_retained=retained['kept'], exact_gained_by_template=dict(gains),
                   exact_lost_by_template=dict(losses), selection_changes=dict(changed), terminal_states=dict(statuses),
                   paper_reproduction_discrepancies=discrepancies, continuation_checks=checks,
                   continuation_gate_passed=all(checks.values()),
                   decision='natural_and_legitimate_exception_validation_needed' if all(checks.values()) else 'reject_cross_benchmark_adoption_no_tuning',
                   truth_known_versions=219, truth_unknown_versions=6, unsupported_xls_versions=27,
                   by_template={name:{key:aggregate(value) for key,value in group.items()} for name,group in families.items()},
                   historical_scoring_amendment=dict(raw_suggestion_rows=2116, unchanged_suggestions_excluded=94,
                       changed_suggestion_denominator=2022, baseline_correct_repairs_unchanged=149,
                       amendment_lock_sha256=sha256(amendment_path), amended_after_outputs_locked=True),
                   business_accuracy=None, final_validation_eligible=False, natural_validation_sources=0,
                   natural_validation_families=0, input_lock_sha256=sha256(lock_path),
                   output_lock_sha256=sha256(EXPERIMENT / 'output_lock.json'),
                   runtime={key:runtime[key] for key in ('requested_worker_count','worker_count','wall_seconds',
                            'child_cpu_seconds','aggregate_peak_rss_bytes_sampled','all_tasks_complete')})
    with (EXPERIMENT / 'independent_score_v2.json').open('x') as handle:
        json.dump(dict(summary=summary, tasks=rows),handle,indent=2)
        handle.write('\n')
    with (ROOT / 'MODEL_M9_EXTERNAL_SUMMARY.json').open('x') as handle:
        json.dump(summary,handle,ensure_ascii=False,indent=2)
        handle.write('\n')
    print(json.dumps({key:value for key,value in summary.items() if key != 'by_template'},indent=2))


if __name__ == '__main__':
    main()
