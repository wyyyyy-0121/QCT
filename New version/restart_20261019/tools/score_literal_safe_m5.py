#!/usr/bin/env python3
"""Independent M5 semantic controls and ordinary-formula candidate diagnostics."""
from collections import Counter
import json
import math
from pathlib import Path

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, verify_frozen
from spreadsheetbench2_scoring import verify_prediction_lock, sha256, exact_metrics

EXPERIMENT = EVIDENCE / 'model_m5_literal'


def aggregate(rows):
    result = {key: sum(row[key] for row in rows) for key in (
        'confirmed_errors', 'all_suggestions', 'exact_correct', 'suggestions_on_errors',
        'wrong_formula_on_errors', 'no_suggestion_on_errors', 'suggestions_outside_confirmed_errors')}
    result['ordinary_candidate_denominator'] = result.pop('confirmed_errors')
    result['candidate_precision'] = result['exact_correct'] / result['all_suggestions'] if result['all_suggestions'] else None
    result['candidate_repair_coverage'] = result['exact_correct'] / result['ordinary_candidate_denominator']
    result['terminal_status_counts'] = Counter(r['terminal_status'] for r in rows)
    return result


def main():
    baseline, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    lock = json.loads((EXPERIMENT / 'output_lock.json').read_text())
    prelock = json.loads((EXPERIMENT / 'prelock.json').read_text())
    if not lock.get('scoring_may_begin') or sha256(EXPERIMENT / 'prelock.json') != lock['prelock_sha256'] or sha256(EVIDENCE / 'prediction_lock.json') != prelock['prediction_lock_sha256']:
        raise SystemExit('M5 prediction lock differs')
    for path, digest in prelock['files_sha256'].items():
        if sha256(path) != digest:
            raise SystemExit('M5 implementation/control input changed')
    for path, key in [('manifest.jsonl', 'manifest_sha256'), ('runs/runtime.json', 'runtime_sha256')]:
        if sha256(EXPERIMENT / path) != lock[key]:
            raise SystemExit('M5 runtime/manifest differs')
    outputs = {o['id']: o for o in lock['outputs']}
    expected_ids = {t['id'] for t in baseline['predictions'] if t['status'] == 'complete'} | {'calc_semantic_control'}
    if len(outputs) != len(lock['outputs']) or set(outputs) != expected_ids:
        raise SystemExit('M5 task set differs')
    for output in outputs.values():
        if output['status'] == 'complete' and sha256(output['path']) != output['sha256']:
            raise SystemExit('M5 output changed')
    # All new outputs are locked/checked before opening scoring evidence.
    control = outputs['calc_semantic_control']
    checks = {'safe_controls_all_correct': False}
    control_report = dict(status=control['status'])
    if control['status'] == 'complete':
        calc = json.loads(Path(control['path']).read_text())
        if not calc['read_only'] or calc['workbook_saved'] or not calc['forced_calculate_all']:
            raise SystemExit('Calc did not follow read-only recalc policy')
        expected = json.loads((EXPERIMENT / 'calc_expected.json').read_text())
        agreements = Counter()
        failures = []
        for cell, correct in expected.items():
            observed = calc['cells'][cell]
            same = observed['kind'] == correct['kind']
            if same:
                same = (observed['value'] == correct['value'] if correct['kind'] == 'text' else
                        math.isclose(observed['value'], correct['value'], rel_tol=1e-12, abs_tol=1e-12))
            name = 'safe' if cell.rsplit('!', 1)[1].startswith('H') else 'native'
            agreements[name + '_compared'] += 1
            agreements[name + '_correct'] += int(same)
            if not same:
                failures.append(dict(cell=cell, variant=name, expected=correct, observed=observed))
        control_report = dict(status='complete', counts=agreements, failures=failures,
                              result_sha256=control['sha256'])
        checks['safe_controls_all_correct'] = agreements['safe_correct'] == agreements['safe_compared'] == 8
    candidate_path = EVIDENCE / 'scoring/candidate_differences.json'
    candidate = json.loads(candidate_path.read_text())
    if candidate['prediction_lock_sha256'] != prelock['prediction_lock_sha256']:
        raise SystemExit('Candidate evidence baseline differs')
    diffs = {t['id']: t for t in candidate['tasks']}
    runtime = {t['id']: t for t in baseline['full_runtime']['tasks']}
    metrics = {'native': [], 'm5': []}
    changed = Counter()
    for task in baseline['predictions']:
        task_id = task['id']
        expected = {cell: c['golden_formula'] for cell, c in diffs[task_id]['formula_changes'].items()
                    if isinstance(c['golden_formula'], str) and c['golden_formula'].startswith('=')}
        old = new = None
        old_status = new_status = task['status']
        if old_status == 'complete':
            old = json.loads((Path(runtime[task_id]['cwd']) / 'prediction.json').read_text())
            new_status = outputs[task_id]['status']
            if new_status == 'complete':
                new = json.loads(Path(outputs[task_id]['path']).read_text())
                if new['observed_formulas'] != old['observed_formulas'] or new['input_sha256'] != task['input_sha256'] or new['labels_read'] != [] or not new['original_unchanged']:
                    raise SystemExit('M5 source identity/immutability/access differs')
                before = {r['cell']: r for r in old['paper']['rows']}
                after = {r['cell']: r for r in new['paper']['rows']}
                if before.keys() != after.keys():
                    raise SystemExit('M5 formula target inventory changed')
                task_changed = False
                for cell in before:
                    a, b = before[cell], after[cell]
                    if a['suggested_formula'] != b['suggested_formula']:
                        task_changed = True
                        changed['changed_final_suggestions'] += 1
                        changed['gained_exact_candidates'] += int(b['suggested_formula'] == expected.get(cell) and cell in expected)
                        changed['lost_exact_candidates'] += int(a['suggested_formula'] == expected.get(cell) and cell in expected)
                changed['tasks_with_changed_final_suggestions'] += int(task_changed)
        metrics['native'].append(exact_metrics(old, expected, terminal_status=old_status))
        metrics['m5'].append(exact_metrics(new, expected, terminal_status=new_status))
    overall = {name: aggregate(rows) for name, rows in metrics.items()}
    old, new = overall['native'], overall['m5']
    checks.update(no_new_prediction_failures=new['terminal_status_counts'] == old['terminal_status_counts'],
                  candidate_precision_not_lower=new['candidate_precision'] is not None and new['candidate_precision'] >= old['candidate_precision'],
                  candidate_coverage_not_lower=new['candidate_repair_coverage'] >= old['candidate_repair_coverage'])
    result = dict(role='Revealed development ordinary-formula candidates; literal integrity and repair performance separate',
                  overall=overall, changed_predictions=changed, control=control_report, continuation_checks=checks,
                  model_adoption_eligible_for_further_research=all(checks.values()),
                  output_lock_sha256=sha256(EXPERIMENT / 'output_lock.json'),
                  candidate_differences_sha256=sha256(candidate_path),
                  business_accuracy=None, final_validation_eligible=False)
    with (EXPERIMENT / 'diagnostic_metrics.json').open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
