#!/usr/bin/env python3
"""Score the frozen paper predictions against post-lock formula differences.

The golden-workbook differences are candidate labels only.  This report is
strictly an exact-formula diagnostic and must not be described as certified
business-error accuracy or natural-error generalisation.
"""
from collections import Counter, defaultdict
import json
from pathlib import Path

from spreadsheetbench2_scoring import exact_metrics, verify_prediction_lock
from resume_spreadsheetbench2_after_pilot import verify_frozen

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'source_evidence/raw/spreadsheetbench2'


def main():
    lock, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    candidate_path = EVIDENCE / 'scoring/candidate_differences.json'
    if not candidate_path.is_file():
        raise SystemExit('Run audit_spreadsheetbench2_locked.py first')
    candidate = json.loads(candidate_path.read_text())
    by_id = {row['id']: row for row in candidate['tasks']}
    runtime_by_id = {row['id']: row for row in lock['full_runtime']['tasks']}
    rows = []
    for item in lock['predictions']:
        task_id = item['id']
        diff = by_id[task_id]
        expected = {
            cell: change['golden_formula']
            for cell, change in diff['formula_changes'].items()
            if isinstance(change.get('golden_formula'), str)
            and change['golden_formula'].startswith('=')
        }
        prediction = None
        if item['status'] == 'complete':
            prediction = json.loads((Path(runtime_by_id[task_id]['cwd']) / 'prediction.json').read_text())
        metrics = exact_metrics(prediction, expected, terminal_status=item['status'])
        metrics.update(id=task_id, group=diff['group'])
        rows.append(metrics)

    def aggregate(items):
        expected = sum(x['confirmed_errors'] for x in items)
        suggestions = sum(x['all_suggestions'] for x in items)
        correct = sum(x['exact_correct'] for x in items)
        return {
            'tasks': len(items),
            'confirmed_formula_differences': expected,
            'all_suggestions': suggestions,
            'exact_correct': correct,
            'precision_all_suggestions': correct / suggestions if suggestions else None,
            'correct_repair_coverage': correct / expected if expected else None,
            'terminal_status_counts': dict(Counter(x['terminal_status'] for x in items)),
        }

    payload = {
        'role': 'Strict exact-formula diagnostic against post-lock golden differences; candidate labels are not certified error truth',
        'prediction_lock_sha256': __import__('hashlib').sha256((EVIDENCE / 'prediction_lock.json').read_bytes()).hexdigest(),
        'overall': aggregate(rows),
        'by_group': {},
        'tasks': rows,
    }
    # Fill group buckets without relying on dict insertion behavior above.
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['group']].append(row)
    payload['by_group'] = {group: aggregate(items) for group, items in sorted(grouped.items())}
    target = EVIDENCE / 'scoring/strict_candidate_metrics.json'
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'overall': payload['overall'], 'by_group': payload['by_group']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
