"""Mechanism helpers for expected-output residual localization."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from .a1 import parse_address
from .workbook import CellKey, WorkbookModel


PROTOCOL = "formulaguard_eorl_v1"
D0_PROTOCOL = "formulaguard_eorl_d0_v1"
RELATIVE_TOLERANCE = 1e-9


def cell_label(cell: CellKey) -> str:
    return f"{cell[0]}!{cell[1]}"


def parse_cell_label(value: str) -> CellKey:
    if "!" not in value:
        raise ValueError(f"invalid cell label: {value!r}")
    sheet, address = value.rsplit("!", 1)
    if not sheet:
        raise ValueError(f"invalid cell label: {value!r}")
    parse_address(address)
    return sheet, address


def finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def residual(actual: float, expected: float) -> float:
    return abs(float(actual) - float(expected)) / max(1.0, abs(float(expected)))


def values_match(left: float, right: float) -> bool:
    return residual(left, right) <= RELATIVE_TOLERANCE


def _cell_sort(cell: CellKey) -> tuple[str, int, int, str]:
    address = parse_address(cell[1])
    return cell[0], address.row, address.col, cell[1]


def source_formula_descendants(
    model: WorkbookModel,
    source_formula_cells: Sequence[CellKey],
) -> dict[str, object]:
    """Summarize formula descendants of recorded source formulas."""

    formula_set = set(model.formula_cells)
    missing = [cell_label(cell) for cell in source_formula_cells if cell not in formula_set]
    if missing:
        raise ValueError(f"recorded sources are not formulas: {missing}")
    graph = model.dependency_graph()
    by_source: dict[str, list[str]] = {}
    combined: set[CellKey] = set()
    for source in source_formula_cells:
        descendants = graph.descendants(source) & formula_set
        combined.update(descendants)
        by_source[cell_label(source)] = [
            cell_label(cell) for cell in sorted(descendants, key=_cell_sort)
        ]
    return {
        "source_formula_count": len(source_formula_cells),
        "sources_with_formula_descendants": sum(bool(cells) for cells in by_source.values()),
        "formula_descendant_count": len(combined),
        "formula_descendants": [cell_label(cell) for cell in sorted(combined, key=_cell_sort)],
        "formula_descendants_by_source": by_source,
    }


def select_output_task(
    observed: WorkbookModel,
    reference: WorkbookModel,
    *,
    case_kind: str,
    source_formula_cells: Sequence[CellKey],
) -> dict[str, object]:
    """Select the frozen public proxy for a user-provided output contract."""

    if case_kind not in {"error", "control"}:
        raise ValueError(f"unsupported case kind: {case_kind!r}")
    if case_kind == "error" and not source_formula_cells:
        raise ValueError("error task requires at least one source formula cell")
    observed_values, observed_errors = observed.evaluate()
    reference_values, reference_errors = reference.evaluate()
    graph = observed.dependency_graph()
    formula_set = set(observed.formula_cells)
    reference_formula_set = set(reference.formula_cells)
    sinks = set(graph.sinks(formula_set))
    candidates: list[tuple[int, tuple[str, int, int, str], CellKey, float, float]] = []
    rejection_counts = {
        "not_shared_formula": 0,
        "not_visible": 0,
        "not_source_descendant": 0,
        "evaluation_error": 0,
        "nonnumeric": 0,
        "residual_contract_mismatch": 0,
    }
    descendants = set()
    if case_kind == "error":
        for source in source_formula_cells:
            descendants.update(graph.descendants(source))
    for output in sorted(sinks, key=_cell_sort):
        if output not in reference_formula_set:
            rejection_counts["not_shared_formula"] += 1
            continue
        if not observed.is_visible(output) or not reference.is_visible(output):
            rejection_counts["not_visible"] += 1
            continue
        if case_kind == "error" and output not in descendants:
            rejection_counts["not_source_descendant"] += 1
            continue
        if output in observed_errors or output in reference_errors:
            rejection_counts["evaluation_error"] += 1
            continue
        actual = finite_number(observed_values.get(output))
        expected = finite_number(reference_values.get(output))
        if actual is None or expected is None:
            rejection_counts["nonnumeric"] += 1
            continue
        matches = values_match(actual, expected)
        if (case_kind == "error" and matches) or (case_kind == "control" and not matches):
            rejection_counts["residual_contract_mismatch"] += 1
            continue
        cone = (graph.ancestors(output) | {output}) & formula_set
        candidates.append((-len(cone), _cell_sort(output), output, actual, expected))
    if not candidates:
        return {
            "eligible": False,
            "reason": "no_output_satisfies_frozen_contract",
            "formula_sink_count": len(sinks),
            "rejection_counts": rejection_counts,
        }
    candidates.sort()
    negative_cone_size, _, output, actual, expected = candidates[0]
    return {
        "eligible": True,
        "selection_rule": "largest_ancestor_cone_then_sheet_row_column",
        "eligible_output_count": len(candidates),
        "formula_sink_count": len(sinks),
        "output_cell": cell_label(output),
        "actual_value": actual,
        "expected_value": expected,
        "base_residual": residual(actual, expected),
        "cone_formula_count": -negative_cone_size,
        "rejection_counts": rejection_counts,
    }


def source_repair_recoverability(
    observed: WorkbookModel,
    *,
    output_cell: CellKey,
    expected_value: float,
    source_formula_cells: Sequence[CellKey],
    records_by_cell: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Measure the D0 oracle ceiling using frozen peer repairs only at sources."""

    base_values, base_errors = observed.evaluate()
    actual = finite_number(base_values.get(output_cell))
    if output_cell in base_errors or actual is None:
        raise ValueError("selected output is not internally evaluable")
    base_residual = residual(actual, expected_value)
    evaluated = 0
    finite = 0
    positive = 0
    source_with_hypothesis = 0
    best: dict[str, object] | None = None
    for source in source_formula_cells:
        record = records_by_cell.get(cell_label(source), {})
        hypotheses = record.get("repair_hypotheses", [])
        if not isinstance(hypotheses, list):
            raise ValueError(f"malformed repair hypotheses for {cell_label(source)}")
        if hypotheses:
            source_with_hypothesis += 1
        for hypothesis_index, hypothesis in enumerate(hypotheses, 1):
            if not isinstance(hypothesis, Mapping) or not isinstance(hypothesis.get("formula"), str):
                raise ValueError(f"malformed repair hypothesis for {cell_label(source)}")
            formula = str(hypothesis["formula"])
            evaluated += 1
            values, errors = observed.evaluate({source: formula})
            repaired_value = finite_number(values.get(output_cell))
            if output_cell in errors or repaired_value is None:
                continue
            finite += 1
            repaired_residual = residual(repaired_value, expected_value)
            gain = base_residual - repaired_residual
            if gain > RELATIVE_TOLERANCE:
                positive += 1
            candidate = {
                "source_cell": cell_label(source),
                "hypothesis_index": hypothesis_index,
                "formula": formula,
                "support_count": int(hypothesis.get("support_count", 0)),
                "actual_value": repaired_value,
                "residual": repaired_residual,
                "absolute_residual_gain": gain,
                "positive_gain": gain > RELATIVE_TOLERANCE,
            }
            if best is None or (
                float(candidate["residual"]),
                -int(candidate["support_count"]),
                str(candidate["source_cell"]),
                int(candidate["hypothesis_index"]),
            ) < (
                float(best["residual"]),
                -int(best["support_count"]),
                str(best["source_cell"]),
                int(best["hypothesis_index"]),
            ):
                best = candidate
    return {
        "base_actual_value": actual,
        "expected_value": float(expected_value),
        "base_residual": base_residual,
        "source_formula_count": len(source_formula_cells),
        "sources_with_hypothesis": source_with_hypothesis,
        "hypotheses_evaluated": evaluated,
        "finite_hypotheses": finite,
        "positive_hypotheses": positive,
        "residually_recoverable": bool(best and best["positive_gain"] is True),
        "best": best,
    }


__all__ = [
    "D0_PROTOCOL",
    "PROTOCOL",
    "RELATIVE_TOLERANCE",
    "cell_label",
    "finite_number",
    "parse_cell_label",
    "residual",
    "select_output_task",
    "source_repair_recoverability",
    "values_match",
]
