"""Independent V5 structural-semantic guard candidate.

The ranker is deliberately independent of ``v4_scores``.  It combines local
template residuals with explicit header-role checks and label-free downstream
invariants.  Candidate formulas are explanations only; they never mutate the
workbook or provide a hidden V4 ranking prior.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .a1 import num_to_col, parse_address
from .formula import (
    Binary,
    Func,
    Number,
    Range,
    Ref,
    edit_cost,
    fingerprint,
    iter_refs,
    normalized_formula,
    parse_formula,
    small_edit_candidates_with_kinds,
    translate_formula,
)
from .localize import LocalizationResult
from .workbook import CellKey, WorkbookModel

MODEL_VERSION = "v5-formulaguard-silent-source-r2"
DEFAULT_RADIUS = 5
DEFAULT_PEER_MIN_SUPPORT = 2
DEFAULT_CANDIDATE_LIMIT = 24
GROUP_MIN_SIZE = 5
GROUP_REPRESENTATIVE_COUNT = 5
GROUP_MIN_ROLE_GAIN = 0.50
GROUP_MIN_FLANK_SUPPORT = 2
GROUP_SCORE_FLOOR = 0.95


@dataclass(frozen=True)
class CandidateProbe:
    formula: str
    semantic_penalty: float
    constraint_residual: float
    peer_support: int
    edit_kinds: tuple[str, ...]


@dataclass(frozen=True)
class FormulaRun:
    sheet: str
    column: int
    header_row: int
    cells: tuple[CellKey, ...]
    observed_template: str
    band_index: int
    run_index: int


@dataclass(frozen=True)
class GroupHypothesis:
    group_id: str
    run: FormulaRun
    trigger: str
    representatives: tuple[CellKey, ...]
    flank_cells: tuple[CellKey, ...]


@dataclass(frozen=True)
class GroupDecision:
    hypothesis: GroupHypothesis
    state: str
    reason: str
    candidate_formulas: tuple[tuple[CellKey, str], ...] = ()
    candidate_template: str = ""
    role_gain_min: float = 0.0
    constraint_delta: float = 0.0


def v5_structural_guard_default_parameters() -> dict[str, object]:
    return {
        "model_version": MODEL_VERSION,
        "architecture": "independent_local_template_header_semantics_constraint_attribution",
        "radius": DEFAULT_RADIUS,
        "peer_min_support": DEFAULT_PEER_MIN_SUPPORT,
        "candidate_limit": DEFAULT_CANDIDATE_LIMIT,
        "group_min_size": GROUP_MIN_SIZE,
        "group_representative_count": GROUP_REPRESENTATIVE_COUNT,
        "group_min_role_gain": GROUP_MIN_ROLE_GAIN,
        "group_min_flank_support": GROUP_MIN_FLANK_SUPPORT,
        "group_score_floor": GROUP_SCORE_FLOOR,
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


def _walk_nodes(node: object) -> Iterable[object]:
    yield node
    if isinstance(node, Binary):
        yield from _walk_nodes(node.left)
        yield from _walk_nodes(node.right)
    elif isinstance(node, Func):
        for arg in node.args:
            yield from _walk_nodes(arg)


def _unwrapped_expression(node: object) -> object:
    while isinstance(node, Func) and node.name == "ROUND" and node.args:
        node = node.args[0]
    return node


def _discount_factor_columns(node: object) -> set[int]:
    columns: set[int] = set()
    for item in _walk_nodes(node):
        if not isinstance(item, Binary) or item.op != "-":
            continue
        if not isinstance(item.left, Number) or not math.isclose(item.left.value, 1.0):
            continue
        if isinstance(item.right, Ref):
            columns.add(item.right.address.col)
    return columns


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

    expression = _unwrapped_expression(node)
    aggregate_role = any(
        _contains_func(node, name) for name in ("SUM", "SUMIF", "SUMIFS", "AVERAGE")
    )
    strict_subtraction = (
        any(token in upper for token in ("VARIANCE", "DIFFERENCE", "SPREAD"))
        and not aggregate_role
        and "TOTAL " not in upper
    )
    strict_subtraction = strict_subtraction or (
        "NET" in upper
        and "NET SALES" not in upper
        and "NET REVENUE" not in upper
        and "PER UNIT" not in upper
        and "PER SEAT" not in upper
        and not aggregate_role
    )
    if strict_subtraction and (not isinstance(expression, Binary) or expression.op != "-"):
        penalty = max(penalty, 0.88)

    if any(token in upper for token in ("CLOSING", "ENDING", "INVENTORY BALANCE")):
        sheet, _, _ = _coordinate(cell)
        header_row = _header_row(model, cell)
        headers = _headers_by_column(model, sheet, header_row) if header_row is not None else {}
        signed = _signed_direct_refs(expression)
        signed_by_column: dict[int, set[int]] = defaultdict(set)
        for ref, sign in signed:
            signed_by_column[ref.address.col].add(sign)
        positive_columns = {
            col
            for col, source_header in headers.items()
            if any(token in source_header.upper() for token in ("OPENING", "BEGINNING", "RECEIVED", "INFLOW"))
        }
        negative_columns = {
            col
            for col, source_header in headers.items()
            if any(token in source_header.upper() for token in ("SHIPPED", "OUTFLOW", "USED", "SENT", "EXPENSE"))
        }
        if positive_columns and any(1 not in signed_by_column.get(col, set()) for col in positive_columns):
            penalty = max(penalty, 0.92)
        if negative_columns and any(-1 not in signed_by_column.get(col, set()) for col in negative_columns):
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

    if upper == "MRR" or any(token in upper for token in ("NET SALES", "NET REVENUE", "TOTAL REVENUE")):
        sheet, _, _ = _coordinate(cell)
        header_row = _header_row(model, cell)
        headers = _headers_by_column(model, sheet, header_row) if header_row is not None else {}
        discount_columns = {
            col for col, source_header in headers.items() if "DISCOUNT" in source_header.upper()
        }
        if discount_columns:
            refs = {
                parse_address(address).col
                for ref_sheet, address in _direct_refs(formula, cell)
                if ref_sheet == sheet
            }
            if not (discount_columns & refs & _discount_factor_columns(node)):
                penalty = max(penalty, 0.88)
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
        if normalized_formula(formula) == normalized_formula(original):
            continue
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


def _all_formula_references(formula: str, cell: CellKey) -> list[CellKey]:
    try:
        node = parse_formula(formula)
    except ValueError:
        return []
    references: list[CellKey] = []
    for item in iter_refs(node):
        if isinstance(item, Ref):
            references.append((item.sheet or cell[0], item.address.a1.replace("$", "")))
        elif isinstance(item, Range):
            sheet = item.start.sheet or item.end.sheet or cell[0]
            references.extend((
                (sheet, item.start.address.a1.replace("$", "")),
                (sheet, item.end.address.a1.replace("$", "")),
            ))
    return references


def _row_local_formula(formula: str, cell: CellKey) -> bool:
    try:
        node = parse_formula(formula)
    except ValueError:
        return False
    _, target_row, _ = _coordinate(cell)
    for item in iter_refs(node):
        if isinstance(item, Ref):
            if not item.address.row_abs and item.address.row != target_row:
                return False
        elif isinstance(item, Range):
            if item.start.address.row != item.end.address.row:
                return False
            if not item.start.address.row_abs and item.start.address.row != target_row:
                return False
            if not item.end.address.row_abs and item.end.address.row != target_row:
                return False
    return True


def _candidate_references_valid(model: WorkbookModel, graph, cell: CellKey, formula: str) -> bool:
    try:
        parse_formula(formula)
    except ValueError:
        return False
    if not _row_local_formula(formula, cell):
        return False
    inventory = set(model.cells) | set(model.formula_cells)
    sheets = {key[0] for key in inventory}
    descendants = graph.descendants(cell)
    for reference in _all_formula_references(formula, cell):
        if reference[0] not in sheets or reference == cell or reference in descendants:
            return False
        if reference not in inventory:
            return False
    return True


def _representative_cells(cells: tuple[CellKey, ...]) -> tuple[CellKey, ...]:
    if len(cells) <= GROUP_REPRESENTATIVE_COUNT:
        return cells
    indexes = tuple(
        ((len(cells) - 1) * quarter) // (GROUP_REPRESENTATIVE_COUNT - 1)
        for quarter in range(GROUP_REPRESENTATIVE_COUNT)
    )
    return tuple(cells[index] for index in indexes)


def _formula_runs(model: WorkbookModel) -> dict[tuple[str, int, int, int], list[FormulaRun]]:
    buckets: dict[tuple[str, int, int], list[tuple[int, CellKey]]] = defaultdict(list)
    for cell in model.formula_cells:
        if not _row_local_formula(model.formulas[cell], cell):
            continue
        sheet, row, column = _coordinate(cell)
        header_row = _header_row(model, cell)
        if header_row is None:
            continue
        buckets[(sheet, column, header_row)].append((row, cell))

    result: dict[tuple[str, int, int, int], list[FormulaRun]] = {}
    for (sheet, column, header_row), rows_and_cells in sorted(buckets.items()):
        rows_and_cells.sort()
        bands: list[list[tuple[int, CellKey]]] = []
        for row_and_cell in rows_and_cells:
            if not bands or row_and_cell[0] != bands[-1][-1][0] + 1:
                bands.append([])
            bands[-1].append(row_and_cell)
        for band_index, band in enumerate(bands):
            raw_runs: list[list[CellKey]] = []
            templates: list[str] = []
            for _, cell in band:
                template = _signature(model.formulas[cell], cell[1])
                if not raw_runs or template != templates[-1]:
                    raw_runs.append([])
                    templates.append(template)
                raw_runs[-1].append(cell)
            runs = [
                FormulaRun(
                    sheet=sheet,
                    column=column,
                    header_row=header_row,
                    cells=tuple(cells),
                    observed_template=templates[run_index],
                    band_index=band_index,
                    run_index=run_index,
                )
                for run_index, cells in enumerate(raw_runs)
            ]
            result[(sheet, column, header_row, band_index)] = runs
    return result


def _group_hypotheses(model: WorkbookModel) -> list[GroupHypothesis]:
    hypotheses: list[GroupHypothesis] = []
    for runs in _formula_runs(model).values():
        for index, run in enumerate(runs):
            if len(run.cells) < GROUP_MIN_SIZE:
                continue
            representatives = _representative_cells(run.cells)
            previous = runs[index - 1] if index > 0 else None
            following = runs[index + 1] if index + 1 < len(runs) else None
            matching_flanks = (
                previous is not None
                and following is not None
                and len(previous.cells) >= GROUP_MIN_FLANK_SUPPORT
                and len(following.cells) >= GROUP_MIN_FLANK_SUPPORT
                and previous.observed_template == following.observed_template
            )
            semantic_trigger = all(
                _role_penalty(model, cell, model.formulas[cell]) >= GROUP_MIN_ROLE_GAIN
                for cell in representatives
            )
            if matching_flanks:
                trigger = "flanking_consensus"
                flank_cells = (previous.cells[-1], following.cells[0])
            elif len(runs) == 1 and semantic_trigger:
                trigger = "semantic_column"
                flank_cells = ()
            else:
                continue
            start = run.cells[0][1]
            end = run.cells[-1][1]
            hypotheses.append(GroupHypothesis(
                group_id=f"{run.sheet}!{num_to_col(run.column)}:{start}-{end}",
                run=run,
                trigger=trigger,
                representatives=representatives,
                flank_cells=flank_cells,
            ))
    return hypotheses


def _group_candidate_pool(
    model: WorkbookModel,
    hypothesis: GroupHypothesis,
    cell: CellKey,
    candidate_limit: int,
) -> dict[str, tuple[str, str, tuple[str, ...], float]]:
    original = model.formulas[cell]
    choices: list[tuple[str, str, tuple[str, ...]]] = [
        (formula, "small_edit", kinds)
        for formula, kinds in small_edit_candidates_with_kinds(original)[:candidate_limit]
    ]
    for flank in hypothesis.flank_cells:
        candidate = translate_formula(model.formulas[flank], flank[1], cell[1])
        choices.append((candidate, "flank_translation", ("flank_translation",)))

    pool: dict[str, tuple[str, str, tuple[str, ...], float]] = {}
    for formula, source, kinds in choices:
        try:
            parse_formula(formula)
        except ValueError:
            continue
        template = _signature(formula, cell[1])
        if template == hypothesis.run.observed_template:
            continue
        record = (formula, source, kinds, edit_cost(original, formula))
        previous = pool.get(template)
        if previous is None or (record[3], record[0]) < (previous[3], previous[0]):
            pool[template] = record
    return pool


def _values_differ(left: object, right: object, tolerance: float = 1e-9) -> bool:
    try:
        return not math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)
    except (TypeError, ValueError):
        return left != right


def _decision_reason(reasons: set[str]) -> str:
    for reason in (
        "invalid_reference",
        "semantic_not_improved",
        "no_behavioral_change",
        "constraint_regression",
    ):
        if reason in reasons:
            return reason
    return "representative_candidate_missing"


def _decide_group(
    model: WorkbookModel,
    graph,
    constraints: set[CellKey],
    baseline_constraints: Mapping[CellKey, float],
    hypothesis: GroupHypothesis,
    candidate_limit: int,
) -> GroupDecision:
    pools = [
        _group_candidate_pool(model, hypothesis, cell, candidate_limit)
        for cell in hypothesis.representatives
    ]
    if any(not pool for pool in pools):
        return GroupDecision(hypothesis, "abstained", "representative_candidate_missing")
    templates = set.intersection(*(set(pool) for pool in pools))
    if hypothesis.trigger == "flanking_consensus":
        flank_templates = {
            _signature(model.formulas[cell], cell[1]) for cell in hypothesis.flank_cells
        }
        templates &= flank_templates
    if not templates:
        return GroupDecision(hypothesis, "abstained", "template_disagreement")

    before_values, before_errors = model.evaluate(targets=hypothesis.representatives)
    survivors: list[tuple[str, tuple[tuple[CellKey, str], ...], float, float]] = []
    failures: set[str] = set()
    anchor = hypothesis.representatives[0]
    for template in sorted(templates):
        anchor_formula = pools[0][template][0]
        candidate_by_cell = tuple(
            (cell, translate_formula(anchor_formula, anchor[1], cell[1]))
            for cell in hypothesis.run.cells
        )
        if any(
            _signature(formula, cell[1]) != template
            or not _candidate_references_valid(model, graph, cell, formula)
            for cell, formula in candidate_by_cell
        ):
            failures.add("invalid_reference")
            continue
        gains = [
            _role_penalty(model, cell, model.formulas[cell])
            - _role_penalty(model, cell, formula)
            for cell, formula in candidate_by_cell
        ]
        role_gain_min = min(gains)
        if role_gain_min < GROUP_MIN_ROLE_GAIN:
            failures.add("semantic_not_improved")
            continue

        representative_overrides = {
            cell: formula
            for cell, formula in candidate_by_cell
            if cell in hypothesis.representatives
        }
        after_values, after_errors = model.evaluate(
            representative_overrides,
            targets=hypothesis.representatives,
        )
        changed = any(
            (cell in before_errors) != (cell in after_errors)
            or _values_differ(before_values.get(cell), after_values.get(cell))
            for cell in hypothesis.representatives
        )
        unsupported_evaluation = all(
            "Unsupported function" in before_errors.get(cell, "")
            and "Unsupported function" in after_errors.get(cell, "")
            for cell in hypothesis.representatives
        )
        if not changed and not unsupported_evaluation:
            failures.add("no_behavioral_change")
            continue

        affected = set().union(*(graph.descendants(cell) for cell in hypothesis.run.cells)) & constraints
        constraint_delta = 0.0
        if affected:
            overrides = dict(candidate_by_cell)
            after_constraints = _constraint_residuals(model, affected, overrides)
            before_mean = statistics.fmean(baseline_constraints.get(cell, 0.0) for cell in affected)
            after_mean = statistics.fmean(after_constraints.get(cell, 0.0) for cell in affected)
            constraint_delta = after_mean - before_mean
            if constraint_delta > 1e-9:
                failures.add("constraint_regression")
                continue
        survivors.append((template, candidate_by_cell, role_gain_min, constraint_delta))

    if not survivors:
        return GroupDecision(hypothesis, "abstained", _decision_reason(failures))
    if len(survivors) != 1:
        return GroupDecision(hypothesis, "abstained", "ambiguous_template")
    template, candidate_by_cell, role_gain_min, constraint_delta = survivors[0]
    return GroupDecision(
        hypothesis,
        "accepted",
        "accepted",
        candidate_formulas=candidate_by_cell,
        candidate_template=template,
        role_gain_min=role_gain_min,
        constraint_delta=constraint_delta,
    )


def _apply_group_decisions(
    model: WorkbookModel,
    results: list[LocalizationResult],
    constraints: set[CellKey],
    baseline_constraints: Mapping[CellKey, float],
    graph,
    *,
    candidate_limit: int,
) -> None:
    by_cell = {result.cell: result for result in results}
    decisions = [
        _decide_group(
            model,
            graph,
            constraints,
            baseline_constraints,
            hypothesis,
            candidate_limit,
        )
        for hypothesis in _group_hypotheses(model)
    ]
    accepted_cells: set[CellKey] = set()
    accepted_overrides: dict[CellKey, str] = {}
    for decision in decisions:
        hypothesis = decision.hypothesis
        common = {
            "group_id": hypothesis.group_id,
            "group_state": decision.state,
            "group_reason": decision.reason,
            "group_size": len(hypothesis.run.cells),
            "group_trigger": hypothesis.trigger,
            "group_representatives": ",".join(cell[1] for cell in hypothesis.representatives),
            "group_candidate_template": decision.candidate_template,
            "group_role_gain_min": decision.role_gain_min,
            "group_constraint_delta": decision.constraint_delta,
            "group_propagated": int(decision.state == "accepted"),
        }
        for cell in hypothesis.run.cells:
            by_cell[cell].evidence.update(common)
        if decision.state != "accepted":
            for cell in hypothesis.run.cells:
                result = by_cell[cell]
                result.candidate_formula = None
                result.evidence["candidate_origin"] = "abstained"
                result.evidence["candidate_abstention_reason"] = decision.reason
            continue
        for cell, formula in decision.candidate_formulas:
            result = by_cell[cell]
            result.candidate_formula = formula
            result.score = max(result.score, GROUP_SCORE_FLOOR)
            result.evidence["candidate_origin"] = "group"
            accepted_cells.add(cell)
            accepted_overrides[cell] = formula

    if accepted_overrides and constraints:
        residual_after_groups = _constraint_residuals(model, constraints, accepted_overrides)
        for result in results:
            if result.cell in accepted_cells or result.candidate_formula is None:
                continue
            evidence = result.evidence
            if evidence["local_template_residual"] > 0 or evidence["header_role_penalty"] > 0:
                continue
            affected = set(graph.descendants(result.cell)) & constraints
            if affected and all(residual_after_groups.get(cell, 0.0) <= 1e-9 for cell in affected):
                result.candidate_formula = None
                result.score = 0.0
                evidence["candidate_origin"] = "abstained"
                evidence["candidate_abstention_reason"] = "explained_by_group"
                evidence["residual_explained_by_group"] = 1


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
            "candidate_origin": "cell" if best and best_gain >= 0.20 else "none",
            "group_state": "not_applicable",
            "group_reason": "",
            "group_propagated": 0,
            "automatic_edit_applied": False,
        }
        results.append(LocalizationResult(
            cell=cell,
            score=score,
            candidate_formula=best.formula if best and best_gain >= 0.20 else None,
            evidence=evidence,
        ))
    _apply_group_decisions(
        model,
        results,
        constraints,
        baseline_constraint,
        graph,
        candidate_limit=candidate_limit,
    )
    results.sort(key=lambda item: (-item.score, item.cell))
    for rank, result in enumerate(results, 1):
        result.evidence["final_rank"] = rank
    return results


__all__ = [
    "MODEL_VERSION",
    "v5_structural_guard_default_parameters",
    "v5_structural_guard_scores",
]
