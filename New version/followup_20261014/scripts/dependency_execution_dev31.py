"""Bounded numeric dependency execution, independent of cached formula results.

Execution is evidence about an expression, never authority for a business repair.
All branches/ranges are structurally audited; only selected IF/INDEX values run.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from pathlib import Path

from formulaguard.formula import Binary, Func, Number, Range, Ref, Unary, parse_formula
from formulaguard.a1 import num_to_col
from formulaguard.workbook import WorkbookModel
from typed_execution_adapter import ExcelError, load_typed_inputs

VERSION = 'bounded-dependency-execution-dev31-v1'
FUNCTIONS = {'SUM', 'MAX', 'MIN', 'IF', 'INDEX', 'PPMT', 'PMT'}


class Unsupported(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Budget:
    formula_chars: int = 8192
    formula_nodes: int = 4096
    ast_depth: int = 96
    dependency_cells: int = 5000
    dependency_nodes: int = 50000
    dependency_depth: int = 96
    range_cells: int = 4096
    execution_nodes: int = 200000


def numeric(value):
    if isinstance(value, ExcelError):
        return value
    if value is None:
        return 0.0
    if isinstance(value, (bool, int, float)):
        result = float(value)
        if math.isfinite(result):
            return result
        return ExcelError('#NUM!')
    raise Unsupported('text_numeric_coercion')


def record(value):
    if isinstance(value, ExcelError):
        return dict(kind='error', error=value.code)
    if isinstance(value, bool):
        return dict(kind='boolean', value=value)
    if isinstance(value, (int, float)) and math.isfinite(value):
        return dict(kind='number', value=value)
    if value is None:
        return dict(kind='missing')
    if isinstance(value, str):
        return dict(kind='text', value=value)
    raise Unsupported('nonfinite_or_unhandled_result')


def payment(rate, nper, pv, fv=0.0, when=0):
    """Stable restricted PMT; semantic domain is deliberately explicit."""
    if rate <= -1 or nper < 1 or nper != int(nper) or nper > 1000000 or when not in (0, 1):
        raise Unsupported('financial_domain')
    if rate == 0:
        return -(pv + fv) / nper
    growth = math.expm1(nper * math.log1p(rate))
    return -(pv * (growth + 1) + fv) / (growth / rate) / (1 + rate * when)


def principal_payment(rate, per, nper, pv, fv=0.0, when=0):
    if per < 1 or per > nper or per != int(per):
        raise Unsupported('financial_period_domain')
    total = payment(rate, nper, pv, fv, when)
    if rate == 0 or (when == 1 and per == 1):
        return total
    growth = math.expm1((per - 1) * math.log1p(rate))
    balance = pv * (1 + growth) + total * (1 + rate * when) * (growth / rate)
    interest = -balance * rate / (1 + rate * when)
    return total - interest


class Executor:
    def __init__(self, model, inputs, budget=Budget()):
        self.model, self.inputs, self.budget = model, dict(inputs), budget
        self.sheets = {s.casefold(): s for s in
                       set(model.sheet_visibility) | {k[0] for k in model.cells} | {k[0] for k in model.formulas}}
        self.nodes = {}

    @classmethod
    def from_xlsx(cls, path: str | Path, budget=Budget()):
        return cls(WorkbookModel.from_xlsx(path), load_typed_inputs(path), budget)

    def sheet(self, name):
        try:
            return self.sheets[name.casefold()]
        except KeyError as exc:
            raise Unsupported('unknown_or_external_sheet') from exc

    def ref(self, node, current_sheet):
        return self.sheet(node.sheet or current_sheet), node.address.a1.replace('$', '')

    def range_keys(self, node, current_sheet):
        a, b = node.start, node.end
        sheet = self.sheet(a.sheet or b.sheet or current_sheet)
        if a.sheet and b.sheet and self.sheet(a.sheet) != self.sheet(b.sheet):
            raise Unsupported('cross_sheet_range')
        if a.address.row > b.address.row or a.address.col > b.address.col:
            raise Unsupported('reverse_range')
        rows, cols = b.address.row - a.address.row + 1, b.address.col - a.address.col + 1
        if rows * cols > self.budget.range_cells:
            raise Unsupported('range_budget')
        keys = [(sheet, num_to_col(c) + str(r)) for r in range(a.address.row, b.address.row + 1)
                for c in range(a.address.col, b.address.col + 1)]
        return keys, rows, cols

    def parsed(self, key):
        if key in self.nodes:
            node, count, direct, functions = self.nodes[key]
            return node, count, direct, functions
        formula = self.model.formulas[key]
        if len(formula) > self.budget.formula_chars:
            raise Unsupported('formula_length_budget')
        # Frozen parser makes chained powers right-associative. Do not claim
        # Excel compatibility for that ambiguous subset, even parenthesized.
        if formula.count('^') > 1:
            raise Unsupported('multiple_power_operators')
        if self.model.formula_kinds.get(key, 'normal') not in ('normal', 'shared'):
            raise Unsupported('array_or_special_formula')
        try:
            node = parse_formula(formula)
        except (ValueError, RecursionError) as exc:
            raise Unsupported('unsupported_syntax') from exc
        pending, count, refs, funcs = [(node, 0)], 0, set(), Counter()
        while pending:
            item, depth = pending.pop(); count += 1
            if count > self.budget.formula_nodes or depth > self.budget.ast_depth:
                raise Unsupported('ast_budget')
            if isinstance(item, Number):
                if not math.isfinite(item.value):
                    raise Unsupported('nonfinite_literal')
            elif isinstance(item, Ref):
                refs.add(self.ref(item, key[0]))
            elif isinstance(item, Range):
                refs.update(self.range_keys(item, key[0])[0])
            elif isinstance(item, Unary):
                pending.append((item.value, depth + 1))
            elif isinstance(item, Binary):
                pending.extend([(item.left, depth + 1), (item.right, depth + 1)])
            elif isinstance(item, Func):
                if item.name not in FUNCTIONS:
                    raise Unsupported('unsupported_function:' + item.name)
                n = len(item.args)
                valid = ((item.name in ('SUM', 'MAX', 'MIN') and n >= 1)
                         or (item.name in ('IF', 'INDEX') and n in (2, 3))
                         or (item.name == 'PMT' and 3 <= n <= 5)
                         or (item.name == 'PPMT' and 4 <= n <= 6))
                if not valid:
                    raise Unsupported('function_arity:' + item.name)
                if item.name == 'INDEX' and not isinstance(item.args[0], (Range, Ref)):
                    raise Unsupported('index_requires_reference')
                funcs[item.name] += 1
                pending.extend((a, depth + 1) for a in item.args)
            else:
                raise Unsupported('unknown_ast')
        self.nodes[key] = node, count, refs, funcs
        return self.nodes[key]

    def audit(self, key):
        visiting, done, all_keys, functions, nodes = set(), set(), set(), Counter(), [0]
        def visit(cell, depth):
            if depth > self.budget.dependency_depth:
                raise Unsupported('dependency_depth_budget')
            if cell in visiting:
                raise Unsupported('circular_reference')
            if cell in done:
                return
            all_keys.add(cell)
            if len(all_keys) > self.budget.dependency_cells:
                raise Unsupported('dependency_cell_budget')
            if cell in self.model.formulas:
                visiting.add(cell)
                _, count, refs, funcs = self.parsed(cell)
                nodes[0] += count; functions.update(funcs)
                if nodes[0] > self.budget.dependency_nodes:
                    raise Unsupported('dependency_node_budget')
                for ref in sorted(refs):
                    visit(ref, depth + 1)
                visiting.remove(cell)
            done.add(cell)
        visit(key, 0)
        return dict(cells=sorted(all_keys), formula_cells=sorted(all_keys & self.model.formulas.keys()),
                    hidden_cells=sorted(k for k in all_keys if not self.model.cell_visibility.get(k, True)
                                        or not self.model.sheet_visibility.get(k[0], True)),
                    functions=dict(functions), ast_nodes=nodes[0])

    def execute(self, key):
        audit = None
        try:
            audit = self.audit(key)
            context = dict(values={}, accesses=set(), nodes=0)
            value = self._cell(key, context)
            value = 0.0 if value is None else value
            return dict(cell=key[0] + '!' + key[1], status='executed', value=record(value), audit=audit,
                        accessed=sorted(context['accesses']), execution_nodes=context['nodes'])
        except Unsupported as exc:
            return dict(cell=key[0] + '!' + key[1], status='unsupported', reason=exc.code, audit=audit)
        except (OverflowError, ZeroDivisionError, ValueError) as exc:
            return dict(cell=key[0] + '!' + key[1], status='unsupported',
                        reason='numeric_domain:' + type(exc).__name__, audit=audit)

    def _cell(self, key, ctx):
        ctx['accesses'].add(key)
        if key in ctx['values']:
            return ctx['values'][key]
        # The complete structural audit already excludes cycles and excess depth.
        value = (self._eval(self.parsed(key)[0], key[0], ctx) if key in self.model.formulas
                 else self.inputs.get(key))
        ctx['values'][key] = value
        return value

    def _eval(self, node, sheet, ctx):
        ctx['nodes'] += 1
        if ctx['nodes'] > self.budget.execution_nodes:
            raise Unsupported('execution_node_budget')
        if isinstance(node, Number):
            return node.value
        if isinstance(node, Ref):
            return self._cell(self.ref(node, sheet), ctx)
        if isinstance(node, Range):
            raise Unsupported('range_requires_function')
        if isinstance(node, Unary):
            v = numeric(self._eval(node.value, sheet, ctx))
            return v if isinstance(v, ExcelError) or node.op == '+' else -v
        if isinstance(node, Binary):
            a, b = self._eval(node.left, sheet, ctx), self._eval(node.right, sheet, ctx)
            if isinstance(a, ExcelError) or isinstance(b, ExcelError):
                return a if isinstance(a, ExcelError) else b
            if node.op in ('=', '<>', '<', '>', '<=', '>='):
                if isinstance(a, str) or isinstance(b, str) or type(a) is bool or type(b) is bool:
                    raise Unsupported('comparison_type_semantics')
                a, b = numeric(a), numeric(b)
                return {'=': lambda: a == b, '<>': lambda: a != b, '<': lambda: a < b,
                        '>': lambda: a > b, '<=': lambda: a <= b, '>=': lambda: a >= b}[node.op]()
            a, b = numeric(a), numeric(b)
            if isinstance(a, ExcelError) or isinstance(b, ExcelError):
                return a if isinstance(a, ExcelError) else b
            if node.op == '/' and b == 0:
                return ExcelError('#DIV/0!')
            try:
                result = {'+': lambda: a + b, '-': lambda: a - b, '*': lambda: a * b,
                          '/': lambda: a / b, '^': lambda: math.pow(a, b)}[node.op]()
            except (ValueError, OverflowError):
                return ExcelError('#NUM!')
            return result if math.isfinite(result) else ExcelError('#NUM!')
        name, args = node.name, node.args
        if name == 'IF':
            test = numeric(self._eval(args[0], sheet, ctx))
            if isinstance(test, ExcelError):
                return test
            return self._eval(args[1], sheet, ctx) if test != 0 else (
                self._eval(args[2], sheet, ctx) if len(args) == 3 else False)
        if name == 'INDEX':
            if isinstance(args[0], Ref):
                keys, rows, cols = [self.ref(args[0], sheet)], 1, 1
            else:
                keys, rows, cols = self.range_keys(args[0], sheet)
            indexes = [numeric(self._eval(a, sheet, ctx)) for a in args[1:]]
            for v in indexes:
                if isinstance(v, ExcelError):
                    return v
                if v != int(v):
                    raise Unsupported('noninteger_index')
                if v == 0:
                    raise Unsupported('index_array_return')
            if len(indexes) == 1:
                if rows > 1 and cols > 1:
                    raise Unsupported('index_missing_dimension')
                row, col = (1, int(indexes[0])) if rows == 1 else (int(indexes[0]), 1)
            else:
                row, col = map(int, indexes)
            if row < 1 or col < 1 or row > rows or col > cols:
                return ExcelError('#REF!')
            value = self._cell(keys[(row - 1) * cols + col - 1], ctx)
            return 0.0 if value is None else value
        if name in ('SUM', 'MAX', 'MIN'):
            numbers = []
            for arg in args:
                referenced = isinstance(arg, (Ref, Range))
                values = ([self._cell(k, ctx) for k in self.range_keys(arg, sheet)[0]]
                          if isinstance(arg, Range) else [self._eval(arg, sheet, ctx)])
                for value in values:
                    if isinstance(value, ExcelError):
                        return value
                    if value is None or (referenced and isinstance(value, (str, bool))):
                        continue
                    if isinstance(value, (str, bool)):
                        raise Unsupported('aggregate_direct_type')
                    value = numeric(value)
                    if isinstance(value, ExcelError):
                        return value
                    numbers.append(value)
            result = sum(numbers) if name == 'SUM' else (max(numbers) if name == 'MAX' else min(numbers)) if numbers else 0.0
            return result if math.isfinite(result) else ExcelError('#NUM!')
        values = [numeric(self._eval(a, sheet, ctx)) for a in args]
        for value in values:
            if isinstance(value, ExcelError):
                return value
        result = payment(*values) if name == 'PMT' else principal_payment(*values)
        return result if math.isfinite(result) else ExcelError('#NUM!')
