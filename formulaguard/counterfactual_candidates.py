"""Deterministic, single-AST-edit counterfactual formula candidates.

This module deliberately generates candidates without consulting formula peers.
The formula-only entry point performs bounded AST enumeration; the workbook
entry point adds reference and dependency-graph validity checks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import NamedTuple

from .a1 import Address, iter_rect, num_to_col, parse_address
from .formula import (
    Binary,
    FormulaSyntaxError,
    Func,
    Node,
    Number,
    Range,
    Ref,
    Unary,
    iter_refs,
    normalized_formula,
    parse_formula,
    render,
)
from .workbook import CellKey, WorkbookModel

DEFAULT_CANDIDATE_BUDGET = 32
MAX_EXCEL_ROW = 1_048_576
MAX_EXCEL_COLUMN = 16_384

OPERATOR_REPLACEMENT = "operator_replacement"
REFERENCE_OFFSET = "reference_offset"
RANGE_BOUNDARY = "range_boundary"
NUMERIC_CONSTANT = "numeric_constant"

_EDIT_KIND_ORDER = {
    OPERATOR_REPLACEMENT: 0,
    REFERENCE_OFFSET: 1,
    RANGE_BOUNDARY: 2,
    NUMERIC_CONSTANT: 3,
}
_ARITHMETIC_OPERATORS = ("+", "-", "*", "/", "^")
_COMPARISON_OPERATORS = ("=", "<>", "<", ">", "<=", ">=")
_OPERATOR_ORDER = {
    operator: index
    for index, operator in enumerate((*_ARITHMETIC_OPERATORS, *_COMPARISON_OPERATORS))
}


class EditWitness(NamedTuple):
    """Auditable proof of the one AST field changed for a candidate."""

    target: str
    path: str
    before: str
    after: str
    axis: str | None = None
    delta: float | int | None = None
    boundary: str | None = None


@dataclass(frozen=True)
class CounterfactualCandidate:
    formula: str
    edit_kind: str
    witness: EditWitness


@dataclass(frozen=True)
class _Mutation:
    node: Node
    edit_kind: str
    witness: EditWitness


def _checked_budget(budget: int) -> int:
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise TypeError("budget must be an integer")
    if budget < 0:
        raise ValueError("budget must be non-negative")
    return budget


def _plain_target(target_address: str) -> str:
    address = parse_address(target_address)
    return f"{num_to_col(address.col)}{address.row}"


def _moved_ref(ref: Ref, axis: str, delta: int) -> Ref | None:
    address = ref.address
    row = address.row + delta if axis == "row" else address.row
    col = address.col + delta if axis == "column" else address.col
    if row < 1 or row > MAX_EXCEL_ROW or col < 1 or col > MAX_EXCEL_COLUMN:
        return None
    return Ref(
        Address(
            row=row,
            col=col,
            row_abs=address.row_abs,
            col_abs=address.col_abs,
        ),
        ref.sheet,
    )


def _numeric_changes(number: Number) -> tuple[tuple[Number, float], ...]:
    if not math.isfinite(number.value):
        return ()
    # ``render`` is the canonical formula spelling used for every candidate.
    # Deriving the edit quantum from the same spelling prevents a sub-render
    # precision change from collapsing back to the original candidate.
    decimal_value = Decimal(render(number))
    if decimal_value == decimal_value.to_integral_value():
        step = Decimal(1)
    else:
        step = Decimal(1).scaleb(decimal_value.normalize().as_tuple().exponent)

    changes: list[tuple[Number, float]] = []
    for sign in (-1, 1):
        changed_decimal = decimal_value + sign * step
        changed = float(changed_decimal)
        if math.isfinite(changed) and changed != number.value:
            changes.append(
                (
                    Number(changed, source_text=str(changed_decimal)),
                    float(sign * step),
                )
            )
    return tuple(changes)


def _mutations(node: Node, target: str, path: str = "root"):
    if isinstance(node, Number):
        for changed, delta in _numeric_changes(node):
            yield _Mutation(
                changed,
                NUMERIC_CONSTANT,
                EditWitness(target, path, render(node), render(changed), delta=delta),
            )
        return

    if isinstance(node, Ref):
        for axis in ("row", "column"):
            for delta in (-1, 1):
                changed = _moved_ref(node, axis, delta)
                if changed is None:
                    continue
                yield _Mutation(
                    changed,
                    REFERENCE_OFFSET,
                    EditWitness(
                        target,
                        path,
                        render(node),
                        render(changed),
                        axis=axis,
                        delta=delta,
                    ),
                )
        return

    if isinstance(node, Range):
        for boundary, endpoint in (("start", node.start), ("end", node.end)):
            for axis in ("row", "column"):
                for delta in (-1, 1):
                    changed_endpoint = _moved_ref(endpoint, axis, delta)
                    if changed_endpoint is None:
                        continue
                    changed = (
                        Range(changed_endpoint, node.end)
                        if boundary == "start"
                        else Range(node.start, changed_endpoint)
                    )
                    yield _Mutation(
                        changed,
                        RANGE_BOUNDARY,
                        EditWitness(
                            target,
                            f"{path}.{boundary}",
                            render(endpoint),
                            render(changed_endpoint),
                            axis=axis,
                            delta=delta,
                            boundary=boundary,
                        ),
                    )
        return

    if isinstance(node, Unary):
        replacement = "-" if node.op == "+" else "+"
        yield _Mutation(
            Unary(replacement, node.value),
            OPERATOR_REPLACEMENT,
            EditWitness(target, path, node.op, replacement),
        )
        for mutation in _mutations(node.value, target, f"{path}.value"):  # type: ignore[arg-type]
            yield _Mutation(
                Unary(node.op, mutation.node),
                mutation.edit_kind,
                mutation.witness,
            )
        return

    if isinstance(node, Binary):
        operator_group = (
            _ARITHMETIC_OPERATORS
            if node.op in _ARITHMETIC_OPERATORS
            else _COMPARISON_OPERATORS
        )
        for replacement in operator_group:
            if replacement == node.op:
                continue
            yield _Mutation(
                Binary(replacement, node.left, node.right),
                OPERATOR_REPLACEMENT,
                EditWitness(target, path, node.op, replacement),
            )
        for mutation in _mutations(node.left, target, f"{path}.left"):  # type: ignore[arg-type]
            yield _Mutation(
                Binary(node.op, mutation.node, node.right),
                mutation.edit_kind,
                mutation.witness,
            )
        for mutation in _mutations(node.right, target, f"{path}.right"):  # type: ignore[arg-type]
            yield _Mutation(
                Binary(node.op, node.left, mutation.node),
                mutation.edit_kind,
                mutation.witness,
            )
        return

    if isinstance(node, Func):
        for index, argument in enumerate(node.args):
            for mutation in _mutations(argument, target, f"{path}.args[{index}]"):  # type: ignore[arg-type]
                arguments = list(node.args)
                arguments[index] = mutation.node
                yield _Mutation(
                    Func(node.name, tuple(arguments)),
                    mutation.edit_kind,
                    mutation.witness,
                )


def candidate_sort_key(candidate: CounterfactualCandidate) -> tuple[object, ...]:
    """Public, peer-independent ordering contract used before budget truncation."""
    witness = candidate.witness
    axis_order = {None: -1, "row": 0, "column": 1}
    delta_order = {-1: 0, 1: 1}
    if candidate.edit_kind == OPERATOR_REPLACEMENT:
        variation = (_OPERATOR_ORDER.get(witness.after, len(_OPERATOR_ORDER)),)
    elif candidate.edit_kind == RANGE_BOUNDARY:
        variation = (
            {"start": 0, "end": 1}.get(witness.boundary, 2),
            axis_order.get(witness.axis, 2),
            delta_order.get(witness.delta, 2),
        )
    else:
        variation = (
            axis_order.get(witness.axis, -1),
            delta_order.get(witness.delta, 2),
            witness.after,
        )
    return (
        _EDIT_KIND_ORDER.get(candidate.edit_kind, len(_EDIT_KIND_ORDER)),
        witness.path,
        *variation,
        normalized_formula(candidate.formula),
    )


def _all_formula_candidates(
    formula: str, target_address: str
) -> list[CounterfactualCandidate]:
    target = _plain_target(target_address)
    try:
        original_node = parse_formula(formula)
    except (FormulaSyntaxError, ValueError, OverflowError):
        return []

    prefix = "=" if formula.startswith("=") else ""
    original = prefix + render(original_node)
    original_normalized = normalized_formula(original)
    raw: list[CounterfactualCandidate] = []
    for mutation in _mutations(original_node, target):
        candidate_formula = prefix + render(mutation.node)
        if normalized_formula(candidate_formula) == original_normalized:
            continue
        try:
            parse_formula(candidate_formula)
        except (FormulaSyntaxError, ValueError, OverflowError):
            continue
        raw.append(
            CounterfactualCandidate(
                formula=candidate_formula,
                edit_kind=mutation.edit_kind,
                witness=mutation.witness,
            )
        )

    raw.sort(key=candidate_sort_key)
    unique: list[CounterfactualCandidate] = []
    seen: set[str] = set()
    for candidate in raw:
        normalized = normalized_formula(candidate.formula)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(candidate)
    return unique


def _round_robin(
    groups: list[list[CounterfactualCandidate]],
) -> list[CounterfactualCandidate]:
    ordered: list[CounterfactualCandidate] = []
    offsets = [0] * len(groups)
    while True:
        added = False
        for index, group in enumerate(groups):
            if offsets[index] >= len(group):
                continue
            ordered.append(group[offsets[index]])
            offsets[index] += 1
            added = True
        if not added:
            return ordered


def _select_stratified_budget(
    candidates: list[CounterfactualCandidate],
    budget: int,
) -> list[CounterfactualCandidate]:
    if len(candidates) <= budget:
        return candidates

    by_kind_and_site: dict[str, dict[str, list[CounterfactualCandidate]]] = {}
    for candidate in candidates:
        by_site = by_kind_and_site.setdefault(candidate.edit_kind, {})
        by_site.setdefault(candidate.witness.path, []).append(candidate)

    kind_sequences: list[list[CounterfactualCandidate]] = []
    for edit_kind in sorted(
        by_kind_and_site,
        key=lambda kind: (_EDIT_KIND_ORDER.get(kind, len(_EDIT_KIND_ORDER)), kind),
    ):
        by_site = by_kind_and_site[edit_kind]
        site_groups = [by_site[path] for path in sorted(by_site)]
        kind_sequences.append(_round_robin(site_groups))

    selected = _round_robin(kind_sequences)[:budget]
    return sorted(selected, key=candidate_sort_key)


def generate_formula_candidates(
    formula: str,
    target_address: str,
    *,
    budget: int = DEFAULT_CANDIDATE_BUDGET,
) -> list[CounterfactualCandidate]:
    """Return at most ``budget`` deterministic one-AST-edit candidates."""
    checked_budget = _checked_budget(budget)
    if checked_budget == 0:
        _plain_target(target_address)
        return []
    return _select_stratified_budget(
        _all_formula_candidates(formula, target_address),
        checked_budget,
    )


def _resolved_references(node: Node, current_sheet: str) -> set[CellKey] | None:
    references: set[CellKey] = set()
    for item in iter_refs(node):
        if isinstance(item, Ref):
            references.add(
                (item.sheet or current_sheet, item.address.a1.replace("$", ""))
            )
            continue

        start_sheet = item.start.sheet
        end_sheet = item.end.sheet
        if (
            start_sheet is not None
            and end_sheet is not None
            and start_sheet != end_sheet
        ):
            return None
        sheet = start_sheet or end_sheet or current_sheet
        references.update(
            (sheet, address)
            for address in iter_rect(item.start.address, item.end.address)
        )
    return references


def generate_counterfactual_candidates(
    model: WorkbookModel,
    key: CellKey,
    *,
    budget: int = DEFAULT_CANDIDATE_BUDGET,
) -> list[CounterfactualCandidate]:
    """Generate candidates whose references remain valid and acyclic in ``model``.

    A reference to an unstored cell on a known worksheet is legal Excel and is
    therefore retained. Only unknown worksheets, out-of-grid coordinates, and
    dependency cycles are rejected here; later behavioral evidence decides
    whether a legal blank reference is a plausible repair.
    """
    checked_budget = _checked_budget(budget)
    if key not in model.formulas:
        raise KeyError(f"Formula cell not found: {key[0]}!{key[1]}")
    if checked_budget == 0:
        return []

    known_sheets = (
        set(model.sheet_visibility)
        | {cell[0] for cell in model.cells}
        | {cell[0] for cell in model.formulas}
    )
    descendants = model.dependency_graph().descendants(key)
    original = normalized_formula(model.formulas[key])
    valid: list[CounterfactualCandidate] = []
    seen: set[str] = set()
    for candidate in _all_formula_candidates(model.formulas[key], key[1]):
        normalized = normalized_formula(candidate.formula)
        if normalized == original or normalized in seen:
            continue
        try:
            node = parse_formula(candidate.formula)
        except (FormulaSyntaxError, ValueError, OverflowError):
            continue
        references = _resolved_references(node, key[0])
        if references is None or key in references:
            continue
        if any(reference[0] not in known_sheets for reference in references):
            continue
        if references & descendants:
            continue
        seen.add(normalized)
        valid.append(candidate)
    return _select_stratified_budget(valid, checked_budget)


__all__ = [
    "DEFAULT_CANDIDATE_BUDGET",
    "NUMERIC_CONSTANT",
    "OPERATOR_REPLACEMENT",
    "RANGE_BOUNDARY",
    "REFERENCE_OFFSET",
    "CounterfactualCandidate",
    "EditWitness",
    "candidate_sort_key",
    "generate_counterfactual_candidates",
    "generate_formula_candidates",
]
