#!/usr/bin/env python3
"""Development-only rational candidate checker; no natural-language inference."""
import argparse
import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.formula import Tokenizer
import sympy as sp


class Unsupported(ValueError):
    pass


@dataclass
class Quantity:
    value: object
    units: tuple


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def arithmetic(expression, variables):
    """Parse a bounded arithmetic grammar without eval/sympify of input text."""
    if len(expression) > 2000:
        raise Unsupported('expression too long')
    tree = ast.parse(expression, mode='eval')
    if sum(1 for _ in ast.walk(tree)) > 120:
        raise Unsupported('expression too complex')

    def visit(node):
        if isinstance(node, ast.Name) and node.id in variables:
            return variables[node.id]
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            number = sp.Rational(str(node.value))
            if abs(number.p) > 10**30 or number.q > 10**30:
                raise Unsupported('constant too large')
            return Quantity(number, ())
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            arg = visit(node.operand)
            return Quantity(arg.value if isinstance(node.op, ast.UAdd) else -arg.value, arg.units)
        if not isinstance(node, ast.BinOp):
            raise Unsupported('arithmetic syntax unsupported')
        left, right = visit(node.left), visit(node.right)
        if isinstance(node.op, (ast.Add, ast.Sub)):
            if left.units != right.units:
                raise Unsupported('incompatible units in sum')
            return Quantity(left.value + right.value if isinstance(node.op, ast.Add)
                            else left.value - right.value, left.units)
        if isinstance(node.op, (ast.Mult, ast.Div)):
            sign = -1 if isinstance(node.op, ast.Div) else 1
            if sign == -1 and right.value.is_positive is not True and right.value.is_negative is not True:
                raise Unsupported('denominator not provably nonzero on positive-symbol domain')
            units = dict(left.units)
            for key, power in right.units:
                units[key] = units.get(key, 0) + sign * power
            units = tuple(sorted((k, v) for k, v in units.items() if v))
            value = left.value / right.value if sign == -1 else left.value * right.value
            return Quantity(value, units)
        if isinstance(node.op, ast.Pow) and not right.units and right.value.is_Integer:
            power = int(right.value)
            if abs(power) > 8:
                raise Unsupported('power outside bounded grammar')
            if power < 0 and left.value.is_positive is not True and left.value.is_negative is not True:
                raise Unsupported('negative power has unproved domain')
            return Quantity(left.value**power, tuple((k, p * power) for k, p in left.units if p * power))
        raise Unsupported('operator unsupported')

    return visit(tree.body)


def active_branch(formula, branch):
    if not branch:
        return formula
    tokens = [t for t in Tokenizer(formula).items if t.type != 'WHITE-SPACE']
    if not tokens or tokens[0].value.upper() != 'IF(' or tokens[-1].value != ')':
        raise Unsupported('expected IF envelope')
    args, part, depth = [], [], 0
    for token in tokens[1:-1]:
        if token.type == 'SEP' and token.subtype == 'ARG' and depth == 0:
            args.append(''.join(part))
            part = []
            continue
        part.append(token.value)
        if token.subtype == 'OPEN':
            depth += 1
        elif token.subtype == 'CLOSE':
            depth -= 1
    args.append(''.join(part))
    if len(args) != 3 or args[0] != branch['guard'] or args[1] != branch['inactive']:
        raise Unsupported('guard or inactive branch differs')
    return '=' + args[2]


def formula_quantity(formula, mapping, variables, branch):
    tokens = Tokenizer(active_branch(formula, branch)).items
    pieces = []
    for token in tokens:
        if token.type == 'WHITE-SPACE':
            continue
        if token.type == 'OPERAND' and token.subtype == 'RANGE':
            if token.value not in mapping:
                raise Unsupported('unmapped reference')
            pieces.append(mapping[token.value])
        elif token.type == 'OPERAND' and token.subtype == 'NUMBER':
            pieces.append(token.value)
        elif token.type == 'PAREN' or (token.type.startswith('OPERATOR') and token.value in '+-*/^'):
            pieces.append('**' if token.value == '^' else token.value)
        else:
            raise Unsupported('formula token unsupported: ' + token.type + '/' + token.subtype)
    return arithmetic(''.join(pieces), variables)


def equivalent(left, right):
    return left.units == right.units and sp.cancel(left.value - right.value) == 0


def select(request, observed):
    result = dict(status='abstain', reason=None, suggested_formula=None,
                  candidate_count=len(request['candidates']), candidate_diagnostics=[],
                  original_satisfies_contract=None, scope='provided candidates; positive-symbol rational domain',
                  final_validation_eligible=False)
    definitions = request['symbols']
    variables = {name: Quantity(sp.Symbol(name, positive=True), tuple(sorted(d['units'].items())))
                 for name, d in definitions.items()}
    if not request.get('constraints'):
        result['reason'] = 'missing_business_relation'
        return result
    try:
        constraints = [arithmetic(text, variables) for text in request['constraints']]
        if any(not equivalent(constraints[0], c) for c in constraints[1:]):
            result['reason'] = 'conflicting_business_relations'
            return result
        expected = constraints[0]
        original = formula_quantity(observed, request['references'], variables, request.get('branch'))
        result['original_satisfies_contract'] = equivalent(original, expected)
        accepted = []
        for formula in request['candidates']:
            try:
                quantity = formula_quantity(formula, request['references'], variables, request.get('branch'))
                matches = equivalent(quantity, expected)
                result['candidate_diagnostics'].append(dict(formula=formula, status='supported', matches=matches))
                if matches:
                    accepted.append(formula)
            except (Unsupported, SyntaxError, ValueError, ZeroDivisionError) as error:
                result['candidate_diagnostics'].append(dict(formula=formula, status='unsupported', reason=str(error)))
        if result['original_satisfies_contract']:
            result.update(reason='original_satisfies_contract')
        elif accepted:
            result.update(status='propose', reason='candidate_satisfies_explicit_relation',
                          suggested_formula=accepted[0])
        else:
            unsupported = result['candidate_diagnostics'] and all(
                c['status'] == 'unsupported' for c in result['candidate_diagnostics'])
            result.update(status='unsupported' if unsupported else 'abstain',
                          reason='candidate_syntax_unsupported' if unsupported else 'no_candidate_satisfies_relation')
    except (Unsupported, SyntaxError, ValueError, ZeroDivisionError) as error:
        result.update(status='unsupported', reason=str(error))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    source, output = Path(request['workbook']).resolve(), args.output.resolve()
    if output.exists() or output in (source, args.request.resolve()):
        raise SystemExit('Output must be new and distinct')
    before = sha(source)
    if before != request['workbook_sha256']:
        raise SystemExit('Workbook hash mismatch')
    # Only this entrypoint reads the request and the one declared workbook.
    # Guard further opens against scoring evidence, other workbooks and writes to source.
    import os
    import sys
    accesses = set()

    def guard(event, values):
        if event != 'open' or not values or not isinstance(values[0], (str, bytes, os.PathLike)):
            return
        path = Path(os.fsdecode(values[0])).resolve()
        if path == source:
            mode, flags = values[1], values[2]
            if (isinstance(mode, str) and any(x in mode for x in 'wa+')) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
                raise PermissionError('Source read-only')
            accesses.add(str(path))
        elif path.suffix.lower() in ('.xlsx', '.xls', '.xlsm', '.ods') or any(
                x in str(path).lower() for x in ('expected.json', 'truth', 'after.xlsx', 'score.json')):
            raise PermissionError('Scoring evidence or other workbook access denied')

    sys.addaudithook(guard)
    book = load_workbook(source, data_only=False, read_only=True)
    observed = book[request['sheet']][request['cell']].value
    book.close()
    result = select(request, observed)
    assert sha(source) == before
    result.update(workbook_sha256=before, request_sha256=sha(args.request),
                  original_unchanged=True, labels_read=[], input_accesses=sorted(accesses),
                  observed_formula=observed)
    with output.open('x') as handle:
        json.dump(result, handle, sort_keys=True, indent=2)
        handle.write('\n')


if __name__ == '__main__':
    main()
