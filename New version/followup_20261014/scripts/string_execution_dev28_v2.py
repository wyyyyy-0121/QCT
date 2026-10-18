"""Preserve v1 parsing, reject unverified boolean-to-text coercion.

The immutable v1 remains available for replay of its failed reference case.
This module supplies execution evidence only, never business repair authority.
"""
from string_execution_dev28 import (
    Concat, Unsupported, parse, provenance, execute as execute_v1,
)

VERSION = 'typed-string-execution-dev28-v2-conservative-boolean'


def execute(node, current_sheet, inputs, formula_cells=(), sheet_names=None):
    # Materialize optional iterators once; repeated checks must see the same
    # formula inventory and sheet names as final execution.
    formula_cells = tuple(formula_cells)
    sheet_names = tuple(sheet_names) if sheet_names is not None else None
    pending = [node]
    while pending:
        current = pending.pop()
        if not isinstance(current, Concat):
            continue
        for child in current.parts:
            value = execute_v1(child, current_sheet, inputs, formula_cells, sheet_names)
            if isinstance(value, bool):
                raise Unsupported('boolean_text_coercion_unverified')
            pending.append(child)
    return execute_v1(node, current_sheet, inputs, formula_cells, sheet_names)
