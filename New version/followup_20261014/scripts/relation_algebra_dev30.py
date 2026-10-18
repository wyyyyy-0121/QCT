"""Bounded exact relation comparison from observed formulas and scalar types.

This module receives no expected business formulas or scoring files. Callers
may compare any two expressions; equality supplies no business authority.
"""
from collections import defaultdict
from fractions import Fraction

from formulaguard.formula import Binary, Func, Number, Range, Ref, Unary, parse_formula
from formulaguard.a1 import num_to_col
from selector_dev11 import syntax_evidence


class UnknownRelation(ValueError):
    pass


def bounded(terms):
    terms = {key: value for key, value in terms.items() if value}
    if len(terms) > 32 or any(len(key) > 16 for key in terms):
        raise UnknownRelation('relation_budget')
    return terms


def add(a, b, scale=1):
    result = defaultdict(Fraction, a)
    for key, value in b.items():
        result[key] += scale * value
    return bounded(result)


def multiply(a, b):
    if len(a) * len(b) > 1024:
        raise UnknownRelation('multiplication_budget')
    result = defaultdict(Fraction)
    for ka, va in a.items():
        for kb, vb in b.items():
            result[tuple(sorted(ka + kb))] += va * vb
    return bounded(result)


def polynomial(formula, sheet, model):
    if not syntax_evidence(formula)['supported']:
        raise UnknownRelation('complete_ast_required')

    def scalar(ref, aggregate=False):
        requested = ref.sheet or sheet
        sheets = {s for s, _ in model.cells} | {s for s, _ in model.formulas}
        matches = [s for s in sheets if s.casefold() == requested.casefold()]
        if len(matches) != 1:
            raise UnknownRelation('unknown_sheet')
        name = matches[0]
        address = ref.address.a1.replace('$', '')
        key = name, address
        value = model.cells.get(key)
        if key not in model.formulas:
            if value is None:
                return {}
            if isinstance(value, (str, bool)):
                if aggregate:
                    return {}
                raise UnknownRelation('nonnumeric_direct_reference')
        return {(name.casefold() + '!' + address,): Fraction(1)}

    def visit(node, aggregate=False):
        if isinstance(node, Number):
            literal = node.source_text
            if len(literal) > 128 or ('e' in literal.lower() and abs(int(literal.lower().split('e')[1])) > 128):
                raise UnknownRelation('number_budget')
            return bounded({(): Fraction(literal)})
        if isinstance(node, Ref):
            return scalar(node, aggregate)
        if isinstance(node, Range):
            if not aggregate:
                raise UnknownRelation('range_outside_sum')
            a, b = node.start.address, node.end.address
            s = node.start.sheet or sheet
            if (node.end.sheet or s).casefold() != s.casefold() or b.col < a.col or b.row < a.row:
                raise UnknownRelation('range_shape')
            if (b.col - a.col + 1) * (b.row - a.row + 1) > 256:
                raise UnknownRelation('range_budget')
            result = {}
            from formulaguard.a1 import parse_address
            for row in range(a.row, b.row + 1):
                for col in range(a.col, b.col + 1):
                    result = add(result, scalar(Ref(parse_address(num_to_col(col) + str(row)), s), True))
            return result
        if isinstance(node, Unary) and node.op in ('+', '-'):
            return add({}, visit(node.value), 1 if node.op == '+' else -1)
        if isinstance(node, Binary) and node.op in ('+', '-', '*', '/'):
            a, b = visit(node.left), visit(node.right)
            if node.op in ('+', '-'):
                return add(a, b, 1 if node.op == '+' else -1)
            if node.op == '*':
                return multiply(a, b)
            if set(b) != {()} or not b[()]:
                raise UnknownRelation('nonconstant_or_zero_divisor')
            return bounded({key: value / b[()] for key, value in a.items()})
        if isinstance(node, Func) and node.name == 'SUM':
            result = {}
            for arg in node.args:
                result = add(result, visit(arg, True))
            return result
        raise UnknownRelation('unsupported_relation_ast')

    return visit(parse_formula(formula))


def equivalent(a, b, sheet, model):
    return polynomial(a, sheet, model) == polynomial(b, sheet, model)
