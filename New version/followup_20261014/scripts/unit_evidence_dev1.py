"""Symbolic unit evidence from explicit visible [unit] headers only.

This is a candidate filter, not a source of business intent. In particular,
signs and dimensionless coefficients cannot be authorized by unit consistency.
Units retain their written scale (C != F, USD != EUR, m != cm); no conversion
factor or affine offset is inferred. Unknown evidence never means compatible.
"""
from bisect import bisect_left
from collections import defaultdict
from functools import lru_cache
import re

from formulaguard.a1 import parse_address, num_to_col
from formulaguard.formula import Binary, Func, Number, Range, Ref, Unary, parse_formula, tokenize

VERSION = 'hybridguard-symbolic-unit-evidence-dev1'
PARAMETERS = {'unit_source': 'nearest visible nonformula text above each cell; trailing [unit]',
              'unit_aliases': {}, 'literal_zero_polymorphic': True,
              'max_tokens': 512, 'max_range_cells': 256,
              'functions': ['SUM', 'AVERAGE', 'MIN', 'MAX', 'ABS'],
              'unknown_is_compatible': False, 'repair_authority': False}


class UnknownUnit(ValueError):
    pass


class UnitConflict(ValueError):
    pass


def combine(left, right, sign=1):
    values = defaultdict(int, dict(left))
    for key, power in right:
        values[key] += sign * power
    return tuple(sorted((key, power) for key, power in values.items() if power))


@lru_cache(maxsize=4096)
def parse_unit(text):
    text = text.strip().casefold()
    if text in {'1', '%'}:
        return ()
    # Explicit symbols only. Spaces/parentheses/implicit multiplication and
    # multiple division bars are deliberately unsupported rather than guessed.
    if not re.fullmatch(r'[a-z][a-z0-9_]*(?:\^-?\d+)?(?:[*/][a-z][a-z0-9_]*(?:\^-?\d+)?)*', text):
        raise UnknownUnit('unsupported_unit_syntax:' + text)
    if text.count('/') > 1:
        raise UnknownUnit('ambiguous_multiple_division_bars:' + text)
    result = (); sign = 1
    for part in re.split(r'([*/])', text):
        if part in {'*', '/'}:
            sign = -1 if part == '/' else 1
            continue
        symbol, _, exponent = part.partition('^')
        power = int(exponent) if exponent else 1
        if abs(power) > 12:
            raise UnknownUnit('unit_exponent_budget')
        result = combine(result, ((symbol, power),), sign)
    return result


@lru_cache(maxsize=32768)
def parse_bounded(formula):
    if len(formula) > 16384 or len(tokenize(formula)) - 1 > PARAMETERS['max_tokens']:
        raise UnknownUnit('formula_token_budget')
    return parse_formula(formula)


class UnitEvidence:
    def __init__(self, model):
        self.model = model
        headers = defaultdict(list)
        for (sheet, address), value in model.cells.items():
            if ((sheet, address) not in model.formulas and isinstance(value, str)
                    and value.strip() and model.is_visible((sheet, address))):
                pos = parse_address(address)
                headers[sheet, pos.col].append((pos.row, address, value.strip()))
        self.headers = {key: sorted(entries) for key, entries in headers.items()}
        self.header_rows = {key: [row for row, _, _ in entries] for key, entries in self.headers.items()}
        self._units = {}

    def declared(self, sheet, address):
        address = address.replace('$', '')
        key = sheet, address
        if key not in self._units:
            pos = parse_address(address)
            entries = self.headers.get((sheet, pos.col), [])
            idx = bisect_left(self.header_rows.get((sheet, pos.col), []), pos.row) - 1
            if idx < 0:
                self._units[key] = (None, 'no_explicit_unit_header', None)
            else:
                _, label, text = entries[idx]
                match = re.search(r'\[([^\[\]]+)\]\s*$', text)
                evidence = {'cell': sheet + '!' + label, 'text': text}
                try:
                    if not match:
                        raise UnknownUnit('nearest_text_has_no_explicit_unit')
                    self._units[key] = (parse_unit(match.group(1)), None, evidence)
                except UnknownUnit as exc:
                    self._units[key] = (None, str(exc), evidence)
        unit, error, evidence = self._units[key]
        if error:
            raise UnknownUnit(sheet + '!' + address + ':' + error)
        return unit, evidence

    def check(self, formula, sheet, address):
        evidence = {}

        def declared(s, a):
            unit, source = self.declared(s, a)
            evidence[s + '!' + a.replace('$', '')] = source
            return unit

        def compatible(left, right):
            # None is the exact literal-zero type; unknowns raise separately.
            if left is None:
                return right
            if right is None:
                return left
            if left != right:
                raise UnitConflict('addition_or_aggregation_has_different_units')
            return left

        def infer(node):
            if isinstance(node, Number):
                return None if node.value == 0 else ()
            if isinstance(node, Ref):
                s = node.sheet or sheet
                if not self.model.is_visible((s, node.address.a1.replace('$', ''))):
                    raise UnknownUnit('hidden_precedent')
                if (s, node.address.a1.replace('$', '')) not in self.model.cells:
                    if (s, node.address.a1.replace('$', '')) not in self.model.formulas:
                        raise UnknownUnit('absent_precedent')
                return declared(s, node.address.a1)
            if isinstance(node, Unary):
                return infer(node.value)
            if isinstance(node, Binary):
                if node.op not in {'+', '-', '*', '/', '^'}:
                    raise UnknownUnit('unsupported_operator:' + node.op)
                left, right = infer(node.left), infer(node.right)
                if node.op in {'+', '-'}:
                    return compatible(left, right)
                if node.op in {'*', '/'}:
                    if node.op == '/' and right is None:
                        raise UnknownUnit('literal_zero_denominator')
                    if left is None or right is None:
                        return None
                    return combine(left, right, 1 if node.op == '*' else -1)
                if not isinstance(node.right, Number) or not node.right.value.is_integer():
                    raise UnknownUnit('nonliteral_or_noninteger_power')
                exponent = int(node.right.value)
                if abs(exponent) > 12:
                    raise UnknownUnit('formula_exponent_budget')
                return tuple((key, power * exponent) for key, power in left or () if power * exponent)
            if isinstance(node, Range):
                first, last = node.start.address, node.end.address
                s = node.start.sheet or sheet
                if (node.end.sheet or s) != s or last.row < first.row or last.col < first.col:
                    raise UnknownUnit('unsupported_range')
                if (last.row-first.row+1) * (last.col-first.col+1) > PARAMETERS['max_range_cells']:
                    raise UnknownUnit('range_budget')
                unit = None
                for row in range(first.row, last.row+1):
                    for col in range(first.col, last.col+1):
                        unit = compatible(unit, infer(Ref(parse_address(num_to_col(col)+str(row)), s)))
                return unit
            if isinstance(node, Func):
                name = node.name.upper()
                if name not in PARAMETERS['functions'] or not node.args:
                    raise UnknownUnit('unsupported_function:' + name)
                if name == 'ABS' and len(node.args) != 1:
                    raise UnknownUnit('invalid_abs_arity')
                unit = None
                for arg in node.args:
                    unit = compatible(unit, infer(arg))
                return unit
            raise UnknownUnit('unsupported_ast')

        try:
            if not self.model.is_visible((sheet, address.replace('$', ''))):
                raise UnknownUnit('hidden_output')
            expected = declared(sheet, address)
            result = infer(parse_bounded(formula))
            if result is not None and result != expected:
                raise UnitConflict('output_unit_mismatch')
            return {'status': 'compatible', 'output_unit': list(expected),
                    'evidence': evidence, 'repair_authority': False}
        except UnitConflict as exc:
            return {'status': 'incompatible', 'reason': str(exc),
                    'evidence': evidence, 'repair_authority': False}
        except (UnknownUnit, ValueError, TypeError, OverflowError, RecursionError) as exc:
            return {'status': 'unknown', 'reason': str(exc),
                    'evidence': evidence, 'repair_authority': False}
