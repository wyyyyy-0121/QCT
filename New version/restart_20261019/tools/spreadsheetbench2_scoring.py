"""Independent exact-formula metrics; no model imports or label access at import."""
from collections import Counter
import hashlib
import json
from pathlib import Path


def formula_inventory(workbook):
    """Capture formula cells including array formulas without numeric evaluation."""
    formulas = {}
    values = {}
    for sheet in workbook:
        for row in sheet:
            for cell in row:
                # read_only worksheets may yield EmptyCell placeholders with
                # no coordinate; they carry no formula or value evidence.
                coordinate = getattr(cell, 'coordinate', None)
                if coordinate is None:
                    continue
                key = f'{sheet.title}!{coordinate}'
                if cell.data_type == 'f':
                    value = cell.value
                    formulas[key] = value if isinstance(value, str) else {
                        'unsupported_formula_object': type(value).__name__,
                        'text': getattr(value, 'text', None), 'ref': getattr(value, 'ref', None)}
                elif cell.value is not None:
                    values[key] = (cell.data_type, str(cell.value))
    return formulas, values


def formula_differences(before, after):
    """Candidate changes ONLY; caller must certify task relevance independently."""
    old, old_values = formula_inventory(before)
    new, new_values = formula_inventory(after)
    changes = {cell: {'input_formula': old.get(cell), 'golden_formula': new.get(cell),
                      'kind': 'formula_changed' if cell in old and cell in new else
                              ('formula_added' if cell in new else 'formula_removed')}
               for cell in sorted(set(old) | set(new)) if old.get(cell) != new.get(cell)}
    return {'formula_changes': changes,
            'input_formula_count': len(old), 'golden_formula_count': len(new),
            'nonformula_value_change_count': sum(old_values.get(c) != new_values.get(c)
                                               for c in set(old_values) | set(new_values)),
            'input_sheets': before.sheetnames, 'golden_sheets': after.sheetnames,
            'interpretation': 'Differences are not certified formula-error labels'}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_prediction_lock(evidence):
    """Must succeed before a caller opens golden workbooks or task metadata."""
    evidence = Path(evidence)
    lock_path = evidence / 'prediction_lock.json'
    if not lock_path.is_file():
        raise ValueError('Prediction lock missing; scoring data must remain unopened')
    lock = json.loads(lock_path.read_text())
    if lock.get('scoring_may_begin') is not True or lock.get('scoring_files_read_before_lock') != []:
        raise ValueError('Prediction lock does not authorize scoring')
    if sha256(evidence / 'input_model_lock.json') != lock['input_model_lock_sha256']:
        raise ValueError('Input lock changed')
    inputs = json.loads((evidence / 'input_model_lock.json').read_text())
    tasks = lock['full_runtime']['tasks']
    predictions = lock['predictions']
    ids = [p['id'] for p in predictions]
    if len(ids) != 100 or len(set(ids)) != 100 or len(tasks) != 100 or {t['id'] for t in tasks} != set(ids):
        raise ValueError('Lock must cover all 100 distinct task terminal states')
    lookup = {t['id']: t for t in tasks}
    for item in predictions:
        task = lookup[item['id']]
        if item['status'] not in {'complete', 'timeout', 'failed'} or item['status'] != task['status']:
            raise ValueError('Ambiguous terminal state')
        if item['status'] == 'complete':
            path = Path(task['cwd']) / 'prediction.json'
            if not path.is_file() or sha256(path) != item['prediction_sha256'] or sha256(path) != task['output_sha256']['prediction.json']:
                raise ValueError('Prediction missing or changed')
        elif item['prediction_sha256'] is not None:
            raise ValueError('Failed task cannot supply a successful prediction')
    if len(inputs['inputs']) != 100 or any(sha256(row['local_path']) != row['sha256'] for row in inputs['inputs']):
        raise ValueError('An input changed')
    return lock, inputs


def exact_metrics(prediction, expected, *, terminal_status='complete', unknown_cells=()):
    """expected contains ONLY independently confirmed erroneous formula cells.

    Unknown is separate from certified errors. Every changed formula suggestion
    is counted, including unknown/control cells. Failed inference supplies no
    suggestions but does not alter the certified-error denominator.
    """
    if terminal_status not in {'complete', 'timeout', 'failed'}:
        raise ValueError('A terminal status is required')
    if terminal_status != 'complete' and prediction is not None:
        raise ValueError('Failed tasks must not supply predictions')
    observed = prediction['observed_formulas'] if prediction else {}
    rows = prediction['paper']['rows'] if prediction else []
    if len({row['cell'] for row in rows}) != len(rows):
        raise ValueError('Duplicate prediction cells')
    suggestions = {row['cell']: row['suggested_formula'] for row in rows
                   if isinstance(row.get('suggested_formula'), str)
                   and row['suggested_formula'].startswith('=')
                   and row['suggested_formula'] != observed.get(row['cell'])}
    correct = {cell for cell, formula in suggestions.items()
               if cell in expected and formula == expected[cell]}
    on_errors = set(suggestions) & set(expected)
    counts = dict(confirmed_errors=len(expected), all_suggestions=len(suggestions),
                  exact_correct=len(correct), suggestions_on_errors=len(on_errors),
                  wrong_formula_on_errors=len(on_errors - correct),
                  no_suggestion_on_errors=len(set(expected) - on_errors),
                  suggestions_outside_confirmed_errors=len(set(suggestions) - set(expected)),
                  suggestions_on_unknown=len(set(suggestions) & set(unknown_cells)),
                  terminal_status=terminal_status,
                  row_status_counts=dict(Counter(row.get('status', 'missing') for row in rows)))
    counts['precision_all_suggestions'] = len(correct) / len(suggestions) if suggestions else None
    counts['correct_repair_coverage'] = len(correct) / len(expected) if expected else None
    return counts
