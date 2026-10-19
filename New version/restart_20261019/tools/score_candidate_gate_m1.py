#!/usr/bin/env python3
"""Independent post-lock M1 diagnostic; ordinary golden formulas are candidates."""
from collections import Counter, defaultdict
import json
from pathlib import Path

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, sha256, verify_frozen
from spreadsheetbench2_scoring import verify_prediction_lock, exact_metrics

EXPERIMENT = EVIDENCE / 'model_m1'


def modifications(prediction):
    if prediction is None:
        return {}
    return {r['cell']: r['suggested_formula'] for r in prediction['paper']['rows']
            if isinstance(r.get('suggested_formula'), str)
            and r['suggested_formula'].startswith('=')
            and r['suggested_formula'] != prediction['observed_formulas'].get(r['cell'])}


def source_class(row):
    source = row.get('suggestion_source') or ''
    if source == 'formulaguard-v5':
        return source
    if source.startswith('validated-parallel-sheet:'):
        return 'validated_parallel_sheet'
    return 'structural_peer' if source else 'unspecified'


def aggregate(rows):
    counts = {key: sum(r[key] for r in rows) for key in (
        'confirmed_errors', 'all_suggestions', 'exact_correct', 'suggestions_on_errors',
        'wrong_formula_on_errors', 'no_suggestion_on_errors', 'suggestions_outside_confirmed_errors')}
    counts['candidate_formula_differences'] = counts.pop('confirmed_errors')
    counts['precision_against_candidates'] = (counts['exact_correct'] / counts['all_suggestions']
                                              if counts['all_suggestions'] else None)
    counts['candidate_repair_coverage'] = (counts['exact_correct'] / counts['candidate_formula_differences']
                                           if counts['candidate_formula_differences'] else None)
    return counts


def main():
    baseline, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    output_lock_path = EXPERIMENT / 'output_lock.json'
    lock = json.loads(output_lock_path.read_text())
    if lock['scoring_may_begin'] is not True:
        raise SystemExit('M1 output lock not ready')
    prelock_path = EXPERIMENT / 'prelock.json'
    if sha256(prelock_path) != lock['prelock_sha256']:
        raise SystemExit('M1 prelock changed')
    prelock = json.loads(prelock_path.read_text())
    if sha256(EVIDENCE / 'prediction_lock.json') != prelock['prediction_lock_sha256']:
        raise SystemExit('Baseline changed')
    for path, expected in prelock['source_sha256'].items():
        if sha256(ROOT / path) != expected:
            raise SystemExit('M1 source changed')
    for path, key in [('manifest.jsonl', 'manifest_sha256'), ('runs/runtime.json', 'runtime_sha256')]:
        if sha256(EXPERIMENT / path) != lock[key]:
            raise SystemExit('M1 runtime or manifest changed')
    output_by_id = {o['id']: o for o in lock['outputs']}
    complete_ids = {t['id'] for t in baseline['predictions'] if t['status'] == 'complete'}
    inherited = [{'id': t['id'], 'status': t['status']}
                 for t in baseline['predictions'] if t['status'] != 'complete']
    if len(output_by_id) != len(lock['outputs']) or set(output_by_id) != complete_ids or inherited != lock['inherited_terminal_states']:
        raise SystemExit('M1 terminal states do not cover the frozen baseline')
    for item in output_by_id.values():
        if sha256(Path(item['path'])) != item['sha256']:
            raise SystemExit('M1 output changed')
    # First access to candidate labels occurs after validation of all outputs.
    candidate_path = EVIDENCE / 'scoring/candidate_differences.json'
    candidate = json.loads(candidate_path.read_text())
    if candidate['prediction_lock_sha256'] != prelock['prediction_lock_sha256']:
        raise SystemExit('Candidate audit uses a different baseline')
    differences = {t['id']: t for t in candidate['tasks']}
    runtime = {t['id']: t for t in baseline['full_runtime']['tasks']}
    records = {'paper': [], 'm1': []}
    by_source = {name: defaultdict(Counter) for name in records}
    by_status = {name: defaultdict(Counter) for name in records}
    by_family = {name: defaultdict(list) for name in records}
    gate_reasons = defaultdict(Counter)
    gaps = Counter()
    label_kinds = Counter()
    for task in baseline['predictions']:
        task_id, status = task['id'], task['status']
        changes = differences[task_id]['formula_changes']
        expected = {cell: v['golden_formula'] for cell, v in changes.items()
                    if isinstance(v['golden_formula'], str) and v['golden_formula'].startswith('=')}
        for change in changes.values():
            value = change['golden_formula']
            label_kinds['ordinary_formula' if isinstance(value, str) else
                        ('unsupported_array_or_object' if isinstance(value, dict) else 'formula_removed')] += 1
        paper = m1 = None
        if status == 'complete':
            paper = json.loads((Path(runtime[task_id]['cwd']) / 'prediction.json').read_text())
            m1 = json.loads(Path(output_by_id[task_id]['path']).read_text())
            if m1['frozen_prediction_sha256'] != task['prediction_sha256'] or m1['labels_read'] != []:
                raise SystemExit('M1 input identity or label access differs')
            old = modifications(paper)
            selected = modifications(m1)
            if not set(selected.items()) <= set(old.items()):
                raise SystemExit('M1 invented a candidate; this experiment is filter-only')
            observed = paper['observed_formulas']
            for cell, formula in expected.items():
                if cell in old:
                    gaps['exact_final_candidate' if old[cell] == formula else
                         'wrong_final_candidate_pool_membership_unresolved'] += 1
                elif cell not in observed:
                    gaps['target_not_in_observed_formula_inventory'] += 1
                else:
                    gaps['no_changed_final_candidate'] += 1
            for row in m1['paper']['rows']:
                if row['cell'] in old:
                    gate_reasons[row['m1_decision']]['suggestions'] += 1
                    gate_reasons[row['m1_decision']]['exact_candidates'] += int(old[row['cell']] == expected.get(row['cell']))
        else:
            gaps['baseline_timeout_or_failure'] += len(expected)
        family = task_id.split('_input_', 1)[0]
        for name, prediction in [('paper', paper), ('m1', m1)]:
            metrics = exact_metrics(prediction, expected, terminal_status=status)
            records[name].append(metrics)
            by_family[name][family].append(metrics)
            suggestions = modifications(prediction)
            for row in prediction['paper']['rows'] if prediction else []:
                if row['cell'] not in suggestions:
                    continue
                correct = int(suggestions[row['cell']] == expected.get(row['cell']))
                for bucket, key in [(by_source[name], source_class(row)),
                                    (by_status[name], row.get('status', 'missing'))]:
                    bucket[key]['suggestions'] += 1
                    bucket[key]['exact_candidates'] += correct
    overall = {name: aggregate(rows) for name, rows in records.items()}
    old, new = overall['paper'], overall['m1']
    checks = dict(suggestions_reduced_at_least_90pct=new['all_suggestions'] <= .1 * old['all_suggestions'],
                  retains_at_least_90pct_exact=new['exact_correct'] >= .9 * old['exact_correct'],
                  precision_at_least_10x=(new['precision_against_candidates'] is not None and
                       new['precision_against_candidates'] >= 10 * old['precision_against_candidates']))
    result = dict(role='Revealed development; golden differences are uncertified; ordinary formulas only',
                  baseline_prediction_lock_sha256=prelock['prediction_lock_sha256'],
                  m1_output_lock_sha256=sha256(output_lock_path),
                  candidate_differences_sha256=sha256(candidate_path),
                  overall=overall, candidate_difference_types=dict(label_kinds),
                  paper_gap_partition=dict(gaps), by_source=by_source, by_status=by_status,
                  by_error_family={name: {k: aggregate(v) for k, v in data.items()}
                                   for name, data in by_family.items()},
                  gate_reasons=gate_reasons, continuation_checks=checks,
                  continue_filter_only_route=all(checks.values()),
                  runtime=json.loads((EXPERIMENT / 'runs/runtime.json').read_text()) | {'tasks': []},
                  certified_business_accuracy=None, final_validation_eligible=False)
    target = EXPERIMENT / 'diagnostic_metrics.json'
    with target.open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps({k: result[k] for k in ('overall', 'paper_gap_partition', 'gate_reasons',
                                           'continuation_checks', 'continue_filter_only_route')}, indent=2))


if __name__ == '__main__':
    main()
