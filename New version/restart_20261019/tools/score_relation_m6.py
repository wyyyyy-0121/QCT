#!/usr/bin/env python3
"""M6 independent Fraction verification and Calc control copies; no SymPy."""
import argparse
import ast
from collections import Counter
from fractions import Fraction
import json
import math
from pathlib import Path
import subprocess
import sys

import openpyxl
from openpyxl.formula import Tokenizer

from resume_spreadsheetbench2_after_pilot import ROOT, EVIDENCE, RUNNER, verify_frozen
from spreadsheetbench2_scoring import sha256, verify_prediction_lock

EXPERIMENT = EVIDENCE / 'model_m6_relation'
CALC = EXPERIMENT / 'calc_audit'
WORKER = ROOT.parent / 'followup_20261014/scripts/libreoffice_reference_worker.py'


def rational_expression(text, variables):
    def visit(node):
        if isinstance(node, ast.Name) and node.id in variables:
            return variables[node.id]
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return Fraction(str(node.value))
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return -visit(node.operand)
            if isinstance(node.op, ast.UAdd):
                return visit(node.operand)
        if isinstance(node, ast.BinOp):
            a, b = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, ast.Div):
                return a / b
            if isinstance(node.op, ast.Pow) and b.denominator == 1 and abs(b) <= 8:
                return a ** int(b)
        raise ValueError('Independent rational grammar unsupported')
    return visit(ast.parse(text, mode='eval').body)


def formula_value(formula, references, q, d):
    pieces = []
    variables = dict(q=Fraction(q), d=Fraction(d))
    for token in Tokenizer(formula).items:
        if token.type == 'WHITE-SPACE':
            continue
        if token.type == 'OPERAND' and token.subtype == 'RANGE':
            pieces.append(references[token.value])
        elif token.type == 'OPERAND' and token.subtype == 'NUMBER':
            pieces.append(token.value)
        elif token.type == 'PAREN' or (token.type.startswith('OPERATOR') and token.value in '+-*/^'):
            pieces.append('**' if token.value == '^' else token.value)
        else:
            raise ValueError('Independent formula syntax unsupported')
    return rational_expression(''.join(pieces), variables)


def branch_expression(formula):
    tokens = Tokenizer(formula).items
    depth, commas = 0, []
    for index, token in enumerate(tokens):
        if token.subtype == 'OPEN':
            depth += 1
        elif token.subtype == 'CLOSE':
            depth -= 1
        elif token.type == 'SEP' and token.subtype == 'ARG' and depth == 1:
            commas.append(index)
    if len(commas) != 2 or tokens[0].value.upper() != 'IF(' or tokens[-1].value != ')':
        raise ValueError('Independent IF shape check failed')
    return '=' + ''.join(token.value for token in tokens[commas[1] + 1:-1])


def verify_predictions():
    _, inputs = verify_prediction_lock(EVIDENCE)
    verify_frozen(inputs)
    lock = json.loads((EXPERIMENT / 'input_lock.json').read_text())
    output_lock = json.loads((EXPERIMENT / 'output_lock.json').read_text())
    if not output_lock.get('scoring_may_begin') or sha256(EXPERIMENT / 'input_lock.json') != output_lock['input_lock_sha256']:
        raise SystemExit('M6 output lock not ready')
    if sha256(EXPERIMENT / 'runs/runtime.json') != output_lock['runtime_sha256']:
        raise SystemExit('M6 runtime changed')
    for path, expected in lock['files_sha256'].items():
        if sha256(path) != expected:
            raise SystemExit('M6 input/source changed')
    expected_ids = {json.loads(line)['id'] for line in (EXPERIMENT / 'manifest.jsonl').read_text().splitlines()}
    outputs = {row['id']: row for row in output_lock['outputs']}
    if len(outputs) != 16 or len(output_lock['outputs']) != 16 or set(outputs) != expected_ids:
        raise SystemExit('M6 output task coverage differs')
    predictions = {}
    for name, row in outputs.items():
        if row['status'] != 'complete' or sha256(row['path']) != row['sha256']:
            raise SystemExit('M6 inference incomplete/changed; retain failure and do not score success')
        result = json.loads(Path(row['path']).read_text())
        request_path = EXPERIMENT / 'requests' / (name + '.json')
        request = json.loads(request_path.read_text())
        if result['request_sha256'] != sha256(request_path) or result['workbook_sha256'] != request['workbook_sha256'] or result['labels_read'] != [] or not result['original_unchanged']:
            raise SystemExit('M6 source/label access identity differs')
        predictions[name] = result
    # Read prelocked expected states only after all output hashes are checked.
    expected = json.loads((EXPERIMENT / 'scoring/expected.json').read_text())
    reports = {}
    points = [(10, 1), (10, 2), (9, 3), (13, 4), (7, Fraction(1, 2))]
    for name, result in predictions.items():
        target = expected[name]
        if any(result.get(key) != target[key] for key in ('status', 'reason')):
            raise SystemExit('M6 condition failed: ' + name + ' actual=' + result['status'] + '/' + str(result['reason']))
        request = json.loads((EXPERIMENT / 'requests' / (name + '.json')).read_text())
        if 'candidates' in request or result['generator_input_contains_candidates']:
            raise SystemExit('M6 input contains manual repair candidates')
        report = dict(status=result['status'], reason=result['reason'],
                      native_pool_has_equivalent=result['native_pool_has_equivalent'],
                      original_paper_has_changed_suggestion=(result['paper_target_row'].get('suggested_formula') is not None and
                                                           result['paper_target_row']['suggested_formula'] != result['observed_formula']))
        if target['status'] == 'propose':
            formula = result['suggested_formula']
            observed = result['observed_formula']
            if request.get('branch'):
                prefix = result['preserved_if_prefix']
                if not formula.startswith(prefix) or not observed.startswith(prefix):
                    raise SystemExit('M6 changed IF prefix')
                formula, observed = branch_expression(formula), branch_expression(observed)
            comparisons = []
            for q, d in points:
                predicted = formula_value(formula, request['references'], q, d)
                old = formula_value(observed, request['references'], q, d)
                correct = Fraction(q) / d if target['semantic'] == 'ratio' else Fraction(q) * (2 - d)
                if predicted != correct:
                    raise SystemExit('M6 independent Fraction check failed: ' + name)
                comparisons.append(dict(q=str(q), d=str(d), expected=str(correct), predicted=str(predicted),
                                        original=str(old), original_matches=old == correct))
            if all(point['original_matches'] for point in comparisons):
                raise SystemExit('M6 control original not distinguishable from target')
            report['fraction_point_checks'] = comparisons
        elif result['suggested_formula'] is not None:
            raise SystemExit('M6 non-propose case supplied a suggestion')
        reports[name] = report
    counter_requests = [json.loads((EXPERIMENT / 'requests' / (name + '.json')).read_text())
                        for name in reports if name.startswith('counter_')]
    if len({r['workbook_sha256'] for r in counter_requests}) != 1:
        raise SystemExit('M6 counterfactual workbook bytes differ')
    return predictions, reports


def prepare_calc(predictions):
    if CALC.exists():
        raise SystemExit('Preserve existing M6 Calc evidence')
    CALC.mkdir()
    request = json.loads((EXPERIMENT / 'requests/epa_ratio.json').read_text())
    native = predictions['epa_ratio']['observed_formula']
    corrected = predictions['epa_ratio']['suggested_formula']
    tasks, expected, files = [], {}, []
    for q, d, inactive in [(12, 2, False), (9, 3, False), (12, 2, True)]:
        for variant, formula in [('native', native), ('generated', corrected)]:
            name = f'q{q}_d{d}_' + ('inactive_' if inactive else 'active_') + variant
            book = openpyxl.load_workbook(request['workbook'], data_only=False)
            book['Data Inputs']['B23'] = q
            book['Design Parameters']['D34'] = d
            book['Design Parameters']['D35'] = 'Not applicable' if inactive else 0
            book['Design Parameters']['D36'] = formula
            path = CALC / (name + '.xlsx')
            book.save(path)
            book.close()
            req = CALC / (name + '_request.json')
            req.write_text(json.dumps(dict(input=str(path), cells=['Design Parameters!D36']), indent=2) + '\n')
            correct = q if inactive else (q / d if variant == 'generated' else q * (2 - d))
            expected[name] = correct
            tasks.append(dict(id=name, argv=['/usr/bin/python3', str(WORKER), str(req), 'result.json'],
                              outputs=['result.json'], timeout_seconds=120))
            files += [path, req]
    manifest = CALC / 'manifest.jsonl'
    manifest.write_text(''.join(json.dumps(t) + '\n' for t in tasks))
    key = CALC / 'expected.json'
    key.write_text(json.dumps(expected, indent=2) + '\n')
    files += [manifest, key, WORKER, Path(__file__), RUNNER, EXPERIMENT / 'output_lock.json']
    with (CALC / 'input_lock.json').open('x') as handle:
        json.dump(dict(files_sha256={str(path): sha256(path) for path in files}), handle, indent=2)
    subprocess.run([sys.executable, str(RUNNER), '--manifest', str(manifest), '--output-dir', str(CALC / 'runs'),
                    '--workers', '20', '--worker-memory-mib', '475', '--timeout', '120'], cwd=ROOT, check=True)


def verify_calc():
    lock = json.loads((CALC / 'input_lock.json').read_text())
    for path, expected in lock['files_sha256'].items():
        if sha256(path) != expected:
            raise SystemExit('M6 Calc input/source changed')
    runtime = json.loads((CALC / 'runs/runtime.json').read_text())
    if runtime['worker_count'] != 20 or not runtime['all_tasks_complete'] or len(runtime['tasks']) != 6:
        raise SystemExit('M6 Calc batch incomplete')
    expected = json.loads((CALC / 'expected.json').read_text())
    reports = {}
    for task in runtime['tasks']:
        path = Path(task['cwd']) / 'result.json'
        if sha256(path) != task['output_sha256']['result.json']:
            raise SystemExit('M6 Calc result changed')
        result = json.loads(path.read_text())
        cell = result['cells']['Design Parameters!D36']
        if not result['read_only'] or result['workbook_saved'] or not result['forced_calculate_all']:
            raise SystemExit('M6 Calc policy differs')
        matched = cell['kind'] == 'number' and math.isclose(cell['value'], expected[task['id']], rel_tol=1e-12, abs_tol=1e-12)
        reports[task['id']] = dict(expected=expected[task['id']], observed=cell.get('value'), agrees=matched)
    if not all(r['agrees'] for r in reports.values()):
        raise SystemExit('M6 Calc disagreement; preserve result')
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-calc', action='store_true')
    args = parser.parse_args()
    predictions, reports = verify_predictions()
    if args.prepare_calc:
        prepare_calc(predictions)
    calc = verify_calc()
    counts = Counter(p['status'] for p in predictions.values())
    result = dict(role='Supplied-relation generator on 16 engineering conditions and one revealed EPA target; not natural accuracy',
                  conditions=16, statuses=counts, all_condition_expectations_match=True,
                  all_fraction_checks_pass=True, calc_controls=calc, condition_results=reports,
                  proposed_with_absent_native_equivalent=sum(p['status'] == 'propose' and p['native_pool_has_equivalent'] is False for p in predictions.values()),
                  epa_target_generated=predictions['epa_ratio']['status'] == 'propose',
                  epa_native_pool_has_equivalent=predictions['epa_ratio']['native_pool_has_equivalent'],
                  unreviewed_paper_rows_epa=predictions['epa_ratio']['unreviewed_paper_formula_rows'],
                  output_lock_sha256=sha256(EXPERIMENT / 'output_lock.json'),
                  calc_input_lock_sha256=sha256(CALC / 'input_lock.json'),
                  automatic_relation_extraction=False, natural_error_accuracy=None,
                  full_workbook_precision=None, final_validation_eligible=False)
    with (EXPERIMENT / 'diagnostic_metrics.json').open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
