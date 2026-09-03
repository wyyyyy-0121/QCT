"""Independent V5 structural-semantic guard candidate.

The ranker is deliberately independent of ``v4_scores``.  It combines local
template residuals with explicit header-role checks and label-free downstream
invariants.  Candidate formulas are explanations only; they never mutate the
workbook or provide a hidden V4 ranking prior.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .a1 import num_to_col, parse_address
from .formula import (
    Binary,
    Func,
    Range,
    Ref,
    fingerprint,
    iter_refs,
    normalized_formula,
    parse_formula,
    small_edit_candidates_with_kinds,
    translate_formula,
)
from .localize import LocalizationResult
from .workbook import CellKey, WorkbookModel

MODEL_VERSION = "v5-formulaguard-silent-source-r1"
DEFAULT_RADIUS = 5
DEFAULT_PEER_MIN_SUPPORT = 2
DEFAULT_CANDIDATE_LIMIT = 24


@dataclass(frozen=True)
class CandidateProbe:
    formula: str
    semantic_penalty: float
    constraint_residual: float
    peer_support: int
    edit_kinds: tuple[str, ...]


def v5_structural_guard_default_parameters() -> dict[str, object]:
    return {
        "model_version": MODEL_VERSION,
        "architecture": "independent_local_template_header_semantics_constraint_attribution",
        "radius": DEFAULT_RADIUS,
        "peer_min_support": DEFAULT_PEER_MIN_SUPPORT,
        "candidate_limit": DEFAULT_CANDIDATE_LIMIT,
        "uses_v4_scores": False,
        "labels_at_localization": False,
        "automatic_edit_applied": False,
        "semantic_roles": [
            "highest_max",
            "lowest_min",
            "average_average",
            "net_subtraction",
            "variance_subtraction",
            "closing_outflow_sign",
            "per_unit_denominator",
            "net_sales_input_coverage",
        ],
    }


def _coordinate(cell: CellKey) -> tuple[str, int, int]:
    address = parse_address(cell[1])
    return cell[0], address.row, address.col


def _signature(formula: str, address: str) -> str:
    try:
        return fingerprint(parse_formula(formula), parse_address(address))
    except ValueError:
        return "UNSUPPORTED:" + normalized_formula(formula)


def _header(model: WorkbookModel, cell: CellKey) -> str:
    row = _header_row(model, cell)
    if row is None:
        return ""
    _, _, col = _coordinate(cell)
    value = model.cells.get((cell[0], f"{num_to_col(col)}{row}"))
    return value.strip().lower() if isinstance(value, str) else ""


def _header_row(model: WorkbookModel, cell: CellKey) -> int | None:
    sheet, row, col = _coordinate(cell)
    for header_row in range(row - 1, 0, -1):
        key = (sheet, f"{num_to_col(col)}{header_row}")
        value = model.cells.get(key)
        if isinstance(value, str) and value.strip() and not value.startswith("="):
            return header_row
    return None


def _headers_by_column(model: WorkbookModel, sheet: str, row: int) -> dict[int, str]:
    result: dict[int, str] = {}
    for col in range(1, 40):
        value = model.cells.get((sheet, f"{num_to_col(col)}{row}"))
        if isinstance(value, str) and value.strip() and not value.startswith("="):
            result[col] = value.strip().lower()
    return result


def _direct_refs(formula: str, cell: CellKey) -> list[CellKey]:
    try:
        node = parse_formula(formula)
    except ValueError:
        return []
    refs: list[CellKey] = []
    for item in iter_refs(node):
        if isinstance(item, Ref):
            refs.append((item.sheet or cell[0], item.address.a1.replace("$", "")))
        elif isinstance(item, Range):
            # A range is evidence of coverage, not an expansion into every cell.
            refs.append((item.start.sheet or item.end.sheet or cell[0], item.start.address.a1.replace("$", "")))
    return refs


def _signed_direct_refs(node: object, sign: int = 1) -> list[tuple[Ref, int]]:
    if isinstance(node, Ref):
        return [(node, sign)]
    if isinstance(node, Binary) and node.op in {"+", "-"}:
        right_sign = sign if node.op == "+" else -sign
        return _signed_direct_refs(node.left, sign) + _signed_direct_refs(node.right, right_sign)
    return []


def _contains_func(node: object, name: str) -> bool:
    if isinstance(node, Func):
        return node.name == name or any(_contains_func(arg, name) for arg in node.args)
    if isinstance(node, Binary):
        return _contains_func(node.left, name) or _contains_func(node.right, name)
    return False


def _single_range(node: object) -> Range | None:
    if isinstance(node, Func) and len(node.args) == 1 and isinstance(node.args[0], Range):
        return node.args[0]
    if isinstance(node, Func):
        for arg in node.args:
            found = _single_range(arg)
            if found is not None:
                return found
    return None


def _role_penalty(model: WorkbookModel, cell: CellKey, formula: str) -> float:
    header = _header(model, cell)
    if not header:
        return 0.0
    try:
        node = parse_formula(formula)
    except ValueError:
        return 0.0
    penalty = 0.0
    upper = header.upper()
    if any(token in upper for token in ("HIGHEST", "MAXIMUM")):
        penalty = max(penalty, 0.98 if not _contains_func(node, "MAX") else 0.0)
    if any(token in upper for token in ("LOWEST", "MINIMUM")):
        penalty = max(penalty, 0.98 if not _contains_func(node, "MIN") else 0.0)
    if "AVERAGE" in upper or "MEAN" in upper:
        penalty = max(penalty, 0.90 if not _contains_func(node, "AVERAGE") else 0.0)

    aggregate_range = _single_range(node)
    if aggregate_range is not None and any(token in upper for token in ("AVERAGE", "SUBTOTAL")):
        _, _, target_col = _coordinate(cell)
        if aggregate_range.end.address.col < target_col - 1:
            penalty = max(penalty, 0.90)

    if any(token in upper for token in ("NET", "VARIANCE", "DIFFERENCE", "SPREAD")) and isinstance(node, Binary) and node.op == "+":
        penalty = max(penalty, 0.88)

    if any(token in upper for token in ("CLOSING", "ENDING", "INVENTORY BALANCE")):
        sheet, _, _ = _coordinate(cell)
        header_row = _header_row(model, cell)
        headers = _headers_by_column(model, sheet, header_row) if header_row is not None else {}
        signed = _signed_direct_refs(node)
        for ref, sign in signed:
            ref_col = ref.address.col
            source_header = headers.get(ref_col, "").upper()
            if sign > 0 and any(token in source_header for token in ("SHIPPED", "OUT", "USED", "SENT", "EXPENSE")):
                penalty = max(penalty, 0.92)

    if "PER UNIT" in upper or "PER SEAT" in upper:
        refs = _direct_refs(formula, cell)
        sheet, _, _ = _coordinate(cell)
        header_row = _header_row(model, cell)
        headers = _headers_by_column(model, sheet, header_row) if header_row is not None else {}
        denominator_ok = False
        for ref_sheet, address in refs:
            if ref_sheet != sheet:
                continue
            source_header = headers.get(parse_address(address).col, "").upper()
            if any(token in source_header for token in ("QUANTITY", "SEATS", "UNITS", "COUNT")):
                denominator_ok = True
        if isinstance(node, Binary) and node.op == "/" and not denominator_ok:
            penalty = max(penalty, 0.90)

    # Input-coverage checks apply to explicit aggregate sales/revenue roles;
    # derived roles such as "MRR per seat" legitimately use only a subset.
    if any(token in upper for token in ("NET SALES", "NET REVENUE", "TOTAL REVENUE")):
        sheet, _, _ = _coordinate(cell)
        header_row = _header_row(model, cell)
        headers = _headers_by_column(model, sheet, header_row) if header_row is not None else {}
        refs = {
            parse_address(address).col
            for ref_sheet, address in _direct_refs(formula, cell)
            if ref_sheet == sheet
        }
        required = set()
        for col, source_header in headers.items():
            source_header = source_header.upper()
            if any(token in source_header for token in ("QUANTITY", "SEATS")):
                required.add(col)
            if "PRICE" in source_header:
                required.add(col)
            if "DISCOUNT" in source_header:
                required.add(col)
        if required and not required <= refs:
            penalty = max(penalty, 0.86)
    return min(1.0, penalty)


def _peer_translations(model: WorkbookModel, cell: CellKey, radius: int) -> Counter[str]:
    _, row, col = _coordinate(cell)
    formulas = set(model.formula_cells)
    translated: Counter[str] = Counter()
    for distance in range(1, radius + 1):
        for peer_row in (row - distance, row + distance):
            if peer_row < 1:
                continue
            peer = (cell[0], f"{num_to_col(col)}{peer_row}")
            if peer not in formulas:
                continue
            try:
                candidate = translate_formula(model.formulas[peer], peer[1], cell[1])
            except ValueError:
                candidate = None
            if candidate is None:
                continue
            translated[normalized_formula(candidate)] += 1
    return translated


def _local_residual(model: WorkbookModel, cell: CellKey, radius: int) -> tuple[float, int]:
    translations = _peer_translations(model, cell, radius)
    if not translations:
        return 0.0, 0
    mode, support = translations.most_common(1)[0]
    own = normalized_formula(model.formulas[cell])
    if own == mode or support < 2:
        return 0.0, support
    return min(1.0, 0.55 + 0.45 * support / sum(translations.values())), support


def _constraint_cells(model: WorkbookModel) -> set[CellKey]:
    return {
        cell
        for cell in model.formula_cells
        if any(token in _header(model, cell).upper() for token in ("CHECK", "BALANCE", "SPREAD"))
    }


def _constraint_residuals(model: WorkbookModel, cells: Iterable[CellKey], overrides: Mapping[CellKey, str] | None = None) -> dict[CellKey, float]:
    selected = tuple(cells)
    if not selected:
        return {}
    values, errors = model.evaluate(overrides, targets=selected)
    result: dict[CellKey, float] = {}
    for cell in selected:
        header = _header(model, cell).upper()
        if cell in errors:
            result[cell] = 1.0
            continue
        value = values.get(cell)
        try:
            number = float(value)
        except (TypeError, ValueError):
            result[cell] = 0.0
            continue
        if "SPREAD" in header:
            result[cell] = 1.0 if number <= 0 else 0.0
            continue
        refs = _direct_refs(model.formulas[cell], cell)
        scale_values = []
        for ref in refs:
            if ref in values:
                try:
                    scale_values.append(abs(float(values[ref])))
                except (TypeError, ValueError):
                    continue
        scale = max(1.0, statistics.median(scale_values) if scale_values else 1.0)
        result[cell] = min(1.0, abs(number) / scale)
    return result


def _constraint_attribution_weight(model: WorkbookModel, source: CellKey, target: CellKey) -> float:
    source_header = _header(model, source).upper()
    target_header = _header(model, target).upper()
    if "SPREAD" in target_header:
        if any(token in source_header for token in ("HIGHEST", "MAXIMUM")):
            return 1.0
        if any(token in source_header for token in ("LOWEST", "MINIMUM")):
            return 0.10
    if any(token in target_header for token in ("CHECK", "BALANCE")):
        if any(token in source_header for token in ("CLOSING", "ENDING", "BALANCE")):
            return 1.0
        return 0.20
    return 1.0


def _candidate_probes(
    model: WorkbookModel,
    cell: CellKey,
    baseline_constraints: Mapping[CellKey, float],
    graph,
    *,
    radius: int,
    peer_min_support: int,
    candidate_limit: int,
) -> list[CandidateProbe]:
    original = model.formulas[cell]
    peer_counts = _peer_translations(model, cell, radius)
    candidates: dict[str, tuple[tuple[str, ...], int]] = {}
    for formula, kinds in small_edit_candidates_with_kinds(original):
        candidates[formula] = (kinds, peer_counts.get(normalized_formula(formula), 0))
    _, row, col = _coordinate(cell)
    for distance in range(1, radius + 1):
        for peer_row in (row - distance, row + distance):
            if peer_row < 1:
                continue
            source = (cell[0], f"{num_to_col(col)}{peer_row}")
            if source not in model.formulas:
                continue
            try:
                candidate = translate_formula(model.formulas[source], source[1], cell[1])
            except ValueError:
                candidate = None
            if candidate is None:
                continue
            support = peer_counts.get(normalized_formula(candidate), 0)
            if support >= peer_min_support:
                candidates.setdefault(candidate, (("peer_translation",), support))
    probes: list[CandidateProbe] = []
    affected = tuple(sorted(set(graph.descendants(cell)) & set(baseline_constraints)))
    for formula, (kinds, support) in sorted(candidates.items(), key=lambda item: (item[1][1] < peer_min_support, item[0]))[:candidate_limit]:
        residual = 0.0
        if affected:
            after = _constraint_residuals(model, affected, {cell: formula})
            weights = [_constraint_attribution_weight(model, cell, target) for target in affected]
            residual = sum(weight * after.get(target, 0.0) for weight, target in zip(weights, affected, strict=True)) / len(affected)
        probes.append(CandidateProbe(
            formula=formula,
            semantic_penalty=_role_penalty(model, cell, formula),
            constraint_residual=residual,
            peer_support=support,
            edit_kinds=kinds,
        ))
    return probes


def v5_structural_guard_scores(
    model: WorkbookModel,
    *,
    radius: int = DEFAULT_RADIUS,
    peer_min_support: int = DEFAULT_PEER_MIN_SUPPORT,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> list[LocalizationResult]:
    """Return a complete ranking without calling any V4 ranker."""
    constraints = _constraint_cells(model)
    baseline_constraint = _constraint_residuals(model, constraints)
    graph = model.dependency_graph()
    results: list[LocalizationResult] = []
    for cell in model.formula_cells:
        local, peer_support = _local_residual(model, cell, radius)
        semantic = _role_penalty(model, cell, model.formulas[cell])
        affected = tuple(sorted(set(graph.descendants(cell)) & constraints))
        if affected:
            weights = [_constraint_attribution_weight(model, cell, target) for target in affected]
            downstream = sum(weight * baseline_constraint.get(target, 0.0) for weight, target in zip(weights, affected, strict=True)) / len(affected)
        else:
            downstream = 0.0
        probes = _candidate_probes(
            model,
            cell,
            baseline_constraint,
            graph,
            radius=radius,
            peer_min_support=peer_min_support,
            candidate_limit=candidate_limit,
        ) if local > 0 or semantic > 0 or downstream > 0 else []
        best: CandidateProbe | None = None
        best_gain = 0.0
        for probe in probes:
            gain = (
                semantic - probe.semantic_penalty
                + downstream - probe.constraint_residual
                + 0.25 * (probe.peer_support / max(1, peer_support))
            )
            if gain > best_gain:
                best, best_gain = probe, gain
        score = min(1.0, 0.26 * local + 0.34 * semantic + 0.25 * downstream + 0.60 * max(0.0, best_gain))
        evidence = {
            "model_version": MODEL_VERSION,
            "uses_v4_scores": False,
            "local_template_residual": local,
            "peer_support": peer_support,
            "header_role_penalty": semantic,
            "downstream_constraint_residual": downstream,
            "affected_constraint_count": len(affected),
            "candidate_gain": max(0.0, best_gain),
            "candidate_peer_support": best.peer_support if best else 0,
            "candidate_edit_kinds": ",".join(best.edit_kinds) if best else "",
            "automatic_edit_applied": False,
        }
        results.append(LocalizationResult(
            cell=cell,
            score=score,
            candidate_formula=best.formula if best and best_gain >= 0.20 else None,
            evidence=evidence,
        ))
    results.sort(key=lambda item: (-item.score, item.cell))
    for rank, result in enumerate(results, 1):
        result.evidence["final_rank"] = rank
    return results


__all__ = [
    "MODEL_VERSION",
    "v5_structural_guard_default_parameters",
    "v5_structural_guard_scores",
]
