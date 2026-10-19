#!/usr/bin/env python3
"""Independent paired M9 scoring; separate natural truth and authored controls.

No fusion/model implementation is imported. Output hashes and every task's
terminal state are checked before the separate scoring key is opened.
"""
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, verify_frozen
from spreadsheetbench2_scoring import sha256, verify_prediction_lock

EXPERIMENT = EVIDENCE / 'model_m9_natural'
COUNT_FIELDS = ('known_errors', 'all_suggestions', 'exact_repairs',
                'suggestions_on_errors', 'wrong_formula_on_errors', 'errors_without_suggestion',
                'known_correct_targets', 'correct_targets_modified', 'unknown_suggestions',
                'range_candidates', 'candidate_exact_matches', 'suggestions_on_candidates',
                'blank_controls', 'blank_controls_modified')


def read(path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def suggestions(paper, observed):
    rows = paper['rows']
    require(len({row['cell'] for row in rows}) == len(rows), 'Duplicate prediction cell')
    return {row['cell']: row['suggested_formula'] for row in rows
            if isinstance(row.get('suggested_formula'), str)
            and row['suggested_formula'].startswith('=')
            and row['suggested_formula'] != observed.get(row['cell'])}


def audit_switches(prediction):
    """Audit the allowed delta row by row, independently of fusion_priority_m9."""
    original, updated = prediction['original_paper'], prediction['paper']
    require({k:v for k,v in original.items() if k != 'rows'} ==
            {k:v for k,v in updated.items() if k != 'rows'}, 'Unregistered metadata changes')
    require(len(original['rows']) == len(updated['rows']), 'Prediction row count changed')
    require(len({r['cell'] for r in original['rows']}) == len(original['rows']), 'Duplicate original cell')
    switched = []
    for before, after in zip(original['rows'], updated['rows']):
        cell = before['cell']
        fg, sg = prediction['fg_selected'].get(cell), prediction['sg_selected'].get(cell)
        observed = prediction['observed_formulas'].get(cell)
        permitted = (before.get('suggestion_source') == 'formulaguard-v5'
                     and isinstance(fg, str) and fg.startswith('=')
                     and before.get('suggested_formula') == fg and fg != observed
                     and isinstance(sg, str) and sg.startswith('=') and sg != observed and sg != fg)
        if permitted:
            restored = dict(after)
            require(restored.pop('m9_decision', None) == 'prefer_emitted_sg_on_fg_conflict'
                    and restored.pop('m9_previous_formula', None) == fg
                    and restored.get('suggested_formula') == sg
                    and restored.get('suggestion_source') == 'm9-emitted-structuralguard',
                    'M9 changed a conflict outside its registered contract')
            restored.update(suggested_formula=fg, suggestion_source=before['suggestion_source'])
            require(restored == before, 'Unrelated row fields changed')
            switched.append(cell)
        else:
            require(before == after, 'Non-conflict prediction changed')
    require(len(switched) == prediction['changed_selection_count'], 'Switch count differs')
    return switched


def metrics(selected, case):
    errors, correct = case['errors'], case['correct']
    candidates, blanks = case['candidate_targets'], set(case['blank_controls'])
    known = set(errors) | set(correct) | set(candidates) | blanks
    exact = {cell for cell, formula in errors.items() if selected.get(cell) == formula}
    on_errors = set(selected) & set(errors)
    values = dict(known_errors=len(errors), all_suggestions=len(selected), exact_repairs=len(exact),
                  suggestions_on_errors=len(on_errors), wrong_formula_on_errors=len(on_errors-exact),
                  errors_without_suggestion=len(set(errors)-on_errors), known_correct_targets=len(correct),
                  correct_targets_modified=len(set(selected) & set(correct)),
                  unknown_suggestions=len(set(selected)-known), range_candidates=len(candidates),
                  candidate_exact_matches=sum(selected.get(c) == f for c,f in candidates.items()),
                  suggestions_on_candidates=len(set(selected) & set(candidates)), blank_controls=len(blanks),
                  blank_controls_modified=len(set(selected) & blanks))
    return values, exact


def aggregate(records):
    values = {key:sum(row[key] for row in records) for key in COUNT_FIELDS}
    values['correct_repair_coverage'] = (values['exact_repairs']/values['known_errors']
                                         if values['known_errors'] else None)
    values['known_error_exact_share_of_all_suggestions'] = (values['exact_repairs']/values['all_suggestions']
                                                            if values['all_suggestions'] else None)
    # Partial labels and formula text alone cannot certify full business precision.
    values['business_precision'] = None
    return values


def main():
    _, baseline_inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(baseline_inputs)
    lock_path, terminal_path = EXPERIMENT/'input_lock.json', EXPERIMENT/'output_lock.json'
    lock, terminal = read(lock_path), read(terminal_path)
    for name, digest in lock['files_sha256'].items():
        require(sha256(Path(name)) == digest, 'Locked natural artifact changed: '+name)
    runtime_path = EXPERIMENT/'runs/runtime.json'
    require(terminal.get('scoring_may_begin') is True
            and terminal['input_lock_sha256'] == sha256(lock_path)
            and terminal['runtime_sha256'] == sha256(runtime_path), 'Invalid natural output lock')
    runtime = read(runtime_path)
    manifest = [json.loads(line) for line in (EXPERIMENT/'manifest.jsonl').read_text().splitlines()]
    tasks = {row['id']:row for row in runtime['tasks']}
    outputs = {row['id']:row for row in terminal['outputs']}
    identifiers = {row['id'] for row in manifest}
    require(len(manifest) == len(identifiers) == len(tasks) == len(runtime['tasks']) ==
            len(outputs) == len(terminal['outputs']) == lock['task_count'] == 49
            and identifiers == set(tasks) == set(outputs), 'Natural task coverage changed')
    require(runtime['requested_worker_count'] == lock['requested_workers'] == 20,
            'Natural requested worker count changed')
    for task_id, item in outputs.items():
        task = tasks[task_id]
        require(item['status'] in {'complete','failed','timeout'} and item['status'] == task['status'],
                'Invalid terminal state')
        if item['path'] is not None:
            require(Path(item['path']) == Path(task['cwd'])/'prediction.json'
                    and sha256(Path(item['path'])) == item['sha256'], 'Output missing or changed')
        if item['status'] == 'complete':
            require(item['path'] is not None and item['sha256'] == task['output_sha256']['prediction.json'],
                    'Complete task lacks a locked prediction')
    # Truth is only opened after all49 terminal records and outputs are validated.
    cases = read(EXPERIMENT/'scoring/expected.json')
    require(set(cases) == identifiers and sum(len(c['errors']) for c in cases.values()
            if c['group'] == 'natural_errors') == lock['natural_error_denominator'] == 513,
            'Natural scoring denominator changed')
    require({g:sum(c['group']==g for c in cases.values()) for g in lock['group_counts']} == lock['group_counts'],
            'Natural group membership changed')
    records = {name:defaultdict(list) for name in ('paper','m9')}
    per_task, details, discrepancies = [], [], []
    statuses, switches, changes = Counter(), Counter(), defaultdict(Counter)
    for task_id in sorted(identifiers):
        case, item = cases[task_id], outputs[task_id]
        group = case['group']
        require(not case['final_validation_eligible'], 'Revealed source claimed as final validation')
        require(not (set(case['errors']) & set(case['correct'])), 'Conflicting labels')
        selected = {'paper':{}, 'm9':{}}
        switched = []
        if item['status'] == 'complete':
            prediction = read(Path(item['path']))
            observed = prediction['observed_formulas']
            require(prediction['input_sha256'] == sha256(Path(case['workbook']))
                    and prediction['original_unchanged'] and prediction['labels_read'] == [],
                    'Inference provenance changed')
            require(all(observed.get(c) != f for c,f in case['errors'].items()), 'Error label equals observed formula')
            require(all(observed.get(c) == f for c,f in case['correct'].items()), 'Known-correct source label differs')
            if task_id in {'natural_cv500','corrected_cv500'}:
                require(set(observed) == set(case['errors']) | set(case['correct']), 'CV complete label scope differs')
            switched = audit_switches(prediction)
            selected = {name:suggestions(prediction[field], observed)
                        for name,field in [('paper','original_paper'),('m9','paper')]}
            if case['historical']:
                old = read(Path(case['historical']))
                if case['comparison'] == 'full':
                    old_observed = old.get('observed_formulas', old.get('observed'))
                    if old['paper'] != prediction['original_paper'] or old_observed != observed:
                        discrepancies.append(dict(id=task_id,reason='historical_full_prediction_differs'))
                    if 'input_sha256' in old and old['input_sha256'] != prediction['input_sha256']:
                        discrepancies.append(dict(id=task_id,reason='historical_input_hash_differs'))
                else:
                    require(case['comparison'] == 'suggestions_only' and isinstance(old['paper'],list),
                            'Unknown historical comparison schema')
                    require(len({r['cell'] for r in old['paper']}) == len(old['paper']), 'Duplicate historical cell')
                    historical = {r['cell']:r['suggested_formula'] for r in old['paper']}
                    if historical != selected['paper']:
                        discrepancies.append(dict(id=task_id,reason='historical_suggestions_differ'))
        statuses[item['status']] += 1
        row = dict(id=task_id,group=group,status=item['status'],selection_changes=len(switched))
        exact = {}
        for name in ('paper','m9'):
            row[name], exact[name] = metrics(selected[name],case)
            records[name][group].append(row[name])
        gained, lost = exact['m9']-exact['paper'], exact['paper']-exact['m9']
        changes[group].update(exact_gained=len(gained),exact_lost=len(lost),
                              exact_retained=len(exact['paper'] & exact['m9']))
        row.update(exact_gained=len(gained),exact_lost=len(lost))
        per_task.append(row)
        for cell in switched:
            scope = ('known_error' if cell in case['errors'] else
                     'known_correct' if cell in case['correct'] else
                     'range_candidate' if cell in case['candidate_targets'] else
                     'blank_control' if cell in case['blank_controls'] else 'unknown')
            switches[scope] += 1
            details.append(dict(id=task_id,cell=cell,scope=scope,
                                original_suggestion=selected['paper'].get(cell),m9_suggestion=selected['m9'].get(cell),
                                exact_gained=cell in gained,exact_lost=cell in lost))
    grouped = {name:{g:aggregate(rows) for g,rows in groups.items()} for name,groups in records.items()}
    natural_old, natural_new = grouped['paper']['natural_errors'], grouped['m9']['natural_errors']
    group_preservation = {g:grouped['m9'][g]['correct_targets_modified'] <=
                           grouped['paper'][g]['correct_targets_modified'] for g in grouped['paper']}
    all_old = sum(row['paper']['all_suggestions'] for row in per_task)
    all_new = sum(row['m9']['all_suggestions'] for row in per_task)
    checks = dict(all49_complete=statuses['complete']==49, historical_comparisons_consistent=not discrepancies,
                  natural_exact_repairs_strictly_increase=natural_new['exact_repairs']>natural_old['exact_repairs'],
                  no_natural_exact_lost=changes['natural_errors']['exact_lost']==0,
                  no_group_correct_target_modification_increase=all(group_preservation.values()),
                  total_suggestions_do_not_increase=all_new<=all_old)
    summary = dict(experiment='M9 fixed natural development and legitimate-control check',
                   exposure='All sources and labels previously revealed; no blind or final validation',
                   task_count=49, terminal_states=dict(statuses), by_group=grouped,
                   exact_changes_by_group={g:dict(c) for g,c in changes.items()},
                   all_changed_suggestions=dict(paper=all_old,m9=all_new),
                   selection_changes=dict(switches), paper_reproduction_discrepancies=discrepancies,
                   correct_target_preservation_by_group=group_preservation, continuation_checks=checks,
                   continuation_gate_passed=all(checks.values()),
                   decision=('eligible_for_further_independent_validation' if all(checks.values())
                             else 'reject_natural_adoption_no_casewise_tuning'),
                   cv500_complete_label_subset={row['id']:{name:aggregate([row[name]]) for name in ('paper','m9')}
                                                for row in per_task if row['id'] in {'natural_cv500','corrected_cv500'}},
                   natural_by_workbook=[row for row in per_task if row['group'] in
                                        {'natural_errors','corrected_controls','range_candidates'}],
                   metric_boundaries=dict(known_error_exact_share_is_not_full_business_precision=True,
                       correct_formula_change_is_preservation_failure_not_proven_business_error=True,
                       range_candidates_not_in_natural_513=True, authored_controls_not_natural=True),
                   final_validation_eligible=False,natural_validation_sources=0,natural_validation_families=0,
                   input_lock_sha256=sha256(lock_path), output_lock_sha256=sha256(terminal_path),
                   runtime={key:runtime[key] for key in ('requested_worker_count','worker_count','wall_seconds',
                           'child_cpu_seconds','aggregate_peak_rss_bytes_sampled','all_tasks_complete')})
    # Per-cell source content remains in the ignored evidence directory only.
    with (EXPERIMENT/'independent_score.json').open('x') as handle:
        json.dump(dict(summary=summary,tasks=per_task,changed_cells=details),handle,ensure_ascii=False,indent=2)
        handle.write('\n')
    with (ROOT/'MODEL_M9_NATURAL_SUMMARY.json').open('x') as handle:
        json.dump(summary,handle,ensure_ascii=False,indent=2)
        handle.write('\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in
                     {'natural_by_workbook','cv500_complete_label_subset','by_group'}},indent=2))


if __name__ == '__main__':
    main()
