"""Dev30 exact algebra with a per-workbook sheet index, without changing old locks.

The polynomial and rejection rules are unchanged. Only repeated enumeration of
all workbook cells for each reference is replaced by a precomputed sheet map.
"""
from collections import defaultdict
from fractions import Fraction
from formulaguard.formula import Binary, Func, Number, Range, Ref, Unary, parse_formula
from formulaguard.a1 import num_to_col
from selector_dev11 import syntax_evidence
from relation_algebra_dev30 import add, multiply, bounded, UnknownRelation


def polynomial(formula, sheet, model, sheet_names):
    if not syntax_evidence(formula)['supported']:
        raise UnknownRelation('complete_ast_required')

    def scalar(ref, aggregate=False):
        requested = ref.sheet or sheet
        matches = sheet_names.get(requested.casefold(), [])
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



class Comparator:
    def __init__(self, model):
        self.model = model
        self.sheet_names = defaultdict(list)
        for name in {s for s, _ in model.cells} | {s for s, _ in model.formulas}:
            self.sheet_names[name.casefold()].append(name)

    def equivalent(self, a, b, sheet):
        return polynomial(a, sheet, self.model, self.sheet_names) == polynomial(b, sheet, self.model, self.sheet_names)
