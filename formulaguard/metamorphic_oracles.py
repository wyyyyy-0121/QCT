"""Deterministic, label-free metamorphic characterizations for formulas.

The checks in this module do not compare a formula with its peers and do not
consume a defect label or an expected answer.  They first prove a narrow
applicability condition from the formula AST, then perturb numeric workbook
inputs and record the observed relation.  Unsupported, conditional, and
data-dependent nonlinear formulas are deliberately abstained from.

These relations characterize internal behavior; they are not correctness
oracles.  A formula can be correct or incorrect whether a relation holds or
breaks.  In particular, an aggregate domain or a zero residual inferred from
the workbook is not an external assertion of author intent.  Relation breaks
are therefore reported as ambiguous and never as formula violations.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass

from .a1 import iter_rect, parse_address
from .formula import Binary, FormulaSyntaxError, Func, Node, Number, Range, Ref, Unary
from .workbook import CellKey, WorkbookModel

PROTOCOL = "formulaguard_label_free_metamorphic_characterization_v2"
RELATIONS = (
    "affine_scaling",
    "aggregate_conservation",
    "redundant_path_invariance",
)
RELATION_ROLES = {
    "affine_scaling": "characterization",
    "aggregate_conservation": "characterization",
    "redundant_path_invariance": "characterization",
}


@dataclass(frozen=True)
class MetamorphicOracleConfig:
    """Fixed numeric intervention and comparison bounds."""

    scale_factor: float = 2.0
    step_fraction: float = 0.125
    minimum_step: float = 1.0
    relative_tolerance: float = 1e-9
    absolute_tolerance: float = 1e-9
    max_input_cells: int = 32
    max_aggregate_cells: int = 32
    max_redundant_path_mismatches: int = 1

    def __post_init__(self) -> None:
        numeric_fields = (
            "scale_factor",
            "step_fraction",
            "minimum_step",
            "relative_tolerance",
            "absolute_tolerance",
        )
        for name in numeric_fields:
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.scale_factor <= 0.0 or math.isclose(self.scale_factor, 1.0):
            raise ValueError("scale_factor must be positive and different from one")
        if self.step_fraction <= 0.0 or self.minimum_step <= 0.0:
            raise ValueError("intervention steps must be positive")
        if self.relative_tolerance < 0.0 or self.absolute_tolerance < 0.0:
            raise ValueError("tolerances must be non-negative")
        if self.max_input_cells < 1 or self.max_aggregate_cells < 2:
            raise ValueError("input limits are too small")
        if self.max_redundant_path_mismatches != 1:
            raise ValueError("redundant path mismatch bound is fixed at one")

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _AffineForm:
    intercept: float
    coefficients: Mapping[CellKey, float]


class _Reject(Exception):
    def __init__(self, reason: str, detail: str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class _AggregateAnchor:
    anchor_id: str
    function: str
    cells: tuple[CellKey, ...]
    occurrences: Mapping[CellKey, int]


def _label(key: CellKey) -> str:
    return f"{key[0]}!{key[1]}"


def _sorted_cells(cells: Iterable[CellKey]) -> list[CellKey]:
    def order(key: CellKey) -> tuple[str, int, int, str]:
        address = parse_address(key[1])
        return key[0], address.row, address.col, key[1]

    return sorted(cells, key=order)


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _clean_coefficients(coefficients: Mapping[CellKey, float]) -> dict[CellKey, float]:
    return {
        key: float(value)
        for key, value in coefficients.items()
        if abs(float(value)) > 1e-15
    }


def _add(left: _AffineForm, right: _AffineForm, factor: float = 1.0) -> _AffineForm:
    coefficients = dict(left.coefficients)
    for key, value in right.coefficients.items():
        coefficients[key] = coefficients.get(key, 0.0) + factor * value
    return _AffineForm(
        left.intercept + factor * right.intercept,
        _clean_coefficients(coefficients),
    )


def _scale(form: _AffineForm, factor: float) -> _AffineForm:
    return _AffineForm(
        form.intercept * factor,
        _clean_coefficients(
            {key: value * factor for key, value in form.coefficients.items()}
        ),
    )


class _AffineAnalyzer:
    """Expand a formula into an affine form over non-formula input cells."""

    def __init__(self, model: WorkbookModel):
        self.model = model
        self.cache: dict[CellKey, _AffineForm] = {}

    def cell(self, key: CellKey, stack: tuple[CellKey, ...] = ()) -> _AffineForm:
        if key not in self.model.formulas:
            return _AffineForm(0.0, {key: 1.0})
        if key in self.cache:
            return self.cache[key]
        if key in stack:
            raise _Reject("cyclic_dependency", _label(key))
        try:
            node = self.model.ast(self.model.formulas[key])
        except FormulaSyntaxError as exc:
            raise _Reject("unsupported_formula", str(exc)) from exc
        result = self.node(node, key[0], stack + (key,))
        self.cache[key] = result
        return result

    def reference(
        self, ref: Ref, current_sheet: str, stack: tuple[CellKey, ...]
    ) -> _AffineForm:
        key = (ref.sheet or current_sheet, ref.address.a1.replace("$", ""))
        return self.cell(key, stack)

    def range_items(
        self,
        item: Range,
        current_sheet: str,
        stack: tuple[CellKey, ...],
    ) -> list[_AffineForm]:
        if item.start.sheet and item.end.sheet and item.start.sheet != item.end.sheet:
            raise _Reject("cross_sheet_range_mismatch")
        sheet = item.start.sheet or item.end.sheet or current_sheet
        return [
            self.cell((sheet, address), stack)
            for address in iter_rect(item.start.address, item.end.address)
        ]

    def function_items(
        self,
        args: tuple[object, ...],
        current_sheet: str,
        stack: tuple[CellKey, ...],
    ) -> list[_AffineForm]:
        items: list[_AffineForm] = []
        for arg in args:
            if isinstance(arg, Range):
                items.extend(self.range_items(arg, current_sheet, stack))
            else:
                items.append(self.node(arg, current_sheet, stack))  # type: ignore[arg-type]
        return items

    def node(
        self, node: Node, current_sheet: str, stack: tuple[CellKey, ...]
    ) -> _AffineForm:
        if isinstance(node, Number):
            return _AffineForm(node.value, {})
        if isinstance(node, Ref):
            return self.reference(node, current_sheet, stack)
        if isinstance(node, Range):
            raise _Reject("range_outside_supported_aggregate")
        if isinstance(node, Unary):
            value = self.node(node.value, current_sheet, stack)  # type: ignore[arg-type]
            return value if node.op == "+" else _scale(value, -1.0)
        if isinstance(node, Binary):
            if node.op in {"=", "<>", "<", ">", "<=", ">="}:
                raise _Reject("comparison_formula")
            left = self.node(node.left, current_sheet, stack)  # type: ignore[arg-type]
            right = self.node(node.right, current_sheet, stack)  # type: ignore[arg-type]
            if node.op == "+":
                return _add(left, right)
            if node.op == "-":
                return _add(left, right, -1.0)
            if node.op == "*":
                if not left.coefficients:
                    return _scale(right, left.intercept)
                if not right.coefficients:
                    return _scale(left, right.intercept)
                raise _Reject("data_dependent_multiplication")
            if node.op == "/":
                if right.coefficients:
                    raise _Reject("data_dependent_division")
                if abs(right.intercept) < 1e-12:
                    raise _Reject("static_zero_divisor")
                return _scale(left, 1.0 / right.intercept)
            if node.op == "^":
                raise _Reject("power_formula")
            raise _Reject("unsupported_operator", node.op)
        if isinstance(node, Func):
            if node.name == "IF":
                raise _Reject("conditional_formula")
            if node.name not in {"SUM", "AVERAGE"}:
                reason = (
                    "nonlinear_function"
                    if node.name in {"MIN", "MAX"}
                    else "unsupported_function"
                )
                raise _Reject(reason, node.name)
            items = self.function_items(node.args, current_sheet, stack)
            if not items:
                raise _Reject("empty_aggregate")
            result = _AffineForm(0.0, {})
            for item in items:
                result = _add(result, item)
            return (
                _scale(result, 1.0 / len(items)) if node.name == "AVERAGE" else result
            )
        raise _Reject("unsupported_ast_node", type(node).__name__)


def _input_values(
    model: WorkbookModel, cells: Iterable[CellKey]
) -> dict[CellKey, float]:
    values: dict[CellKey, float] = {}
    for key in _sorted_cells(cells):
        if key not in model.cells:
            raise _Reject("missing_input_value", _label(key))
        value = _finite_number(model.cells[key])
        if value is None:
            raise _Reject("non_numeric_input", _label(key))
        values[key] = value
    return values


def _tolerance(config: MetamorphicOracleConfig, *values: float) -> float:
    scale = max((abs(value) for value in values), default=0.0)
    return config.absolute_tolerance + config.relative_tolerance * max(1.0, scale)


def _abstain(
    relation: str,
    reason: str,
    detail: str | None = None,
    witness: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "relation": relation,
        "role": RELATION_ROLES[relation],
        "applicability": False,
        "outcome": "abstain",
        "relation_holds": False,
        "ambiguous": False,
        "violation": False,
        "ambiguity_reason": None,
        "rejection_reason": reason,
        "rejection_detail": detail,
        "witness": dict(witness) if witness is not None else None,
    }


def _characterization_result(
    relation: str,
    relation_holds: bool,
    witness: Mapping[str, object],
    ambiguity_reason: str = "relation_break_without_external_assertion",
) -> dict[str, object]:
    ambiguous = not relation_holds
    return {
        "relation": relation,
        "role": RELATION_ROLES[relation],
        "applicability": True,
        "outcome": "relation_holds" if relation_holds else "ambiguous",
        "relation_holds": relation_holds,
        "ambiguous": ambiguous,
        "violation": False,
        "ambiguity_reason": ambiguity_reason if ambiguous else None,
        "rejection_reason": None,
        "rejection_detail": None,
        "witness": dict(witness),
    }


def _evaluated_output(
    model: WorkbookModel,
    target: CellKey,
    value_overrides: Mapping[CellKey, object],
) -> tuple[float | None, str | None]:
    values, errors = model.evaluate(value_overrides=value_overrides)
    if target in errors:
        return None, errors[target]
    value = _finite_number(values.get(target))
    if value is None:
        return None, "target output is not a finite number"
    return value, None


def _scaling_relation(
    model: WorkbookModel,
    target: CellKey,
    formula: str,
    affine: _AffineForm,
    baseline: float,
    config: MetamorphicOracleConfig,
) -> dict[str, object]:
    relation = "affine_scaling"
    inputs = _sorted_cells(affine.coefficients)
    if not inputs:
        return _abstain(relation, "no_effective_numeric_inputs")
    if len(inputs) > config.max_input_cells:
        return _abstain(relation, "input_budget_exceeded", str(len(inputs)))
    try:
        input_values = _input_values(model, inputs)
    except _Reject as exc:
        return _abstain(relation, exc.reason, exc.detail)
    overrides = {
        key: value * config.scale_factor
        for key, value in input_values.items()
        if value * config.scale_factor != value
    }
    if not overrides:
        return _abstain(relation, "no_effective_intervention")
    if any(not math.isfinite(float(value)) for value in overrides.values()):
        return _abstain(relation, "non_finite_intervention")
    observed, error = _evaluated_output(model, target, overrides)
    if error is not None or observed is None:
        return _abstain(relation, "intervention_evaluation_error", error)
    expected = affine.intercept + config.scale_factor * (baseline - affine.intercept)
    tolerance = _tolerance(config, baseline, expected, observed)
    witness = {
        "cell": _label(target),
        "formula": formula,
        "interpretation": "affine_relation_characterization",
        "evidence_basis": "target_formula_ast_only",
        "external_assertion_source": None,
        "can_identify_formula_error": False,
        "factor": config.scale_factor,
        "affine_intercept": affine.intercept,
        "input_values_before": {
            _label(key): value for key, value in input_values.items()
        },
        "input_values_after": {_label(key): value for key, value in overrides.items()},
        "baseline_output": baseline,
        "target_ast_predicted_output": expected,
        "observed_output": observed,
        "absolute_difference_from_target_ast_prediction": abs(observed - expected),
        "tolerance": tolerance,
        "relation_held": abs(observed - expected) <= tolerance,
    }
    if abs(observed - expected) > tolerance:
        # The expectation and intervention are derived from this same AST.  A
        # mismatch is evidence about evaluation stability, not formula intent.
        return _abstain(
            relation,
            "execution_inconsistency_not_formula_evidence",
            witness=witness,
        )
    return _characterization_result(relation, True, witness)


def _aggregate_cells(node: Func, current_sheet: str) -> tuple[CellKey, ...]:
    cells: list[CellKey] = []
    for arg in node.args:
        if isinstance(arg, Number):
            continue
        if isinstance(arg, Ref):
            cells.append((arg.sheet or current_sheet, arg.address.a1.replace("$", "")))
            continue
        if isinstance(arg, Range):
            if arg.start.sheet and arg.end.sheet and arg.start.sheet != arg.end.sheet:
                raise _Reject("cross_sheet_range_mismatch")
            sheet = arg.start.sheet or arg.end.sheet or current_sheet
            cells.extend(
                (sheet, address)
                for address in iter_rect(arg.start.address, arg.end.address)
            )
            continue
        raise _Reject("non_plain_aggregate_argument", type(arg).__name__)
    return tuple(cells)


def _aggregate_anchors(
    node: Node, current_sheet: str
) -> tuple[list[_AggregateAnchor], list[dict[str, object]]]:
    anchors: list[_AggregateAnchor] = []
    rejected: list[dict[str, object]] = []

    def visit(item: Node) -> None:
        if isinstance(item, Func) and item.name in {"SUM", "AVERAGE"}:
            anchor_id = f"aggregate_{len(anchors) + len(rejected) + 1:02d}"
            try:
                occurrences: dict[CellKey, int] = {}
                for key in _aggregate_cells(item, current_sheet):
                    occurrences[key] = occurrences.get(key, 0) + 1
                cells = tuple(_sorted_cells(occurrences))
                if len(cells) < 2:
                    raise _Reject("aggregate_domain_too_small", str(len(cells)))
                anchors.append(
                    _AggregateAnchor(anchor_id, item.name, cells, occurrences)
                )
            except _Reject as exc:
                rejected.append(
                    {
                        "anchor_id": anchor_id,
                        "function": item.name,
                        "reason": exc.reason,
                        "detail": exc.detail,
                    }
                )
            return
        if isinstance(item, Unary):
            visit(item.value)  # type: ignore[arg-type]
        elif isinstance(item, Binary):
            visit(item.left)  # type: ignore[arg-type]
            visit(item.right)  # type: ignore[arg-type]
        elif isinstance(item, Func):
            for arg in item.args:
                visit(arg)  # type: ignore[arg-type]

    visit(node)
    return anchors, rejected


def _conservation_relation(
    model: WorkbookModel,
    target: CellKey,
    formula: str,
    node: Node,
    baseline: float,
    config: MetamorphicOracleConfig,
) -> dict[str, object]:
    relation = "aggregate_conservation"
    anchors, rejected = _aggregate_anchors(node, target[0])
    if not anchors:
        if rejected:
            first = rejected[0]
            return _abstain(
                relation, str(first["reason"]), str(first.get("detail") or "") or None
            )
        return _abstain(relation, "no_explicit_aggregate")

    applicable: list[tuple[_AggregateAnchor, dict[CellKey, float]]] = []
    for anchor in anchors:
        reason: str | None = None
        detail: str | None = None
        if len(anchor.cells) > config.max_aggregate_cells:
            reason, detail = "aggregate_budget_exceeded", str(len(anchor.cells))
        elif any(key in model.formulas for key in anchor.cells):
            reason = "aggregate_contains_formula_cell"
            detail = _label(next(key for key in anchor.cells if key in model.formulas))
        else:
            try:
                values = _input_values(model, anchor.cells)
            except _Reject as exc:
                reason, detail = exc.reason, exc.detail
            else:
                applicable.append((anchor, values))
        if reason is not None:
            rejected.append(
                {
                    "anchor_id": anchor.anchor_id,
                    "function": anchor.function,
                    "reason": reason,
                    "detail": detail,
                }
            )

    if not applicable:
        first = rejected[0]
        return _abstain(
            relation, str(first["reason"]), str(first.get("detail") or "") or None
        )

    anchor_witnesses: list[dict[str, object]] = []
    for anchor, values in applicable:
        pivot = anchor.cells[0]
        magnitude = max(abs(value) for value in values.values())
        step = max(config.minimum_step, magnitude * config.step_fraction)
        probes: list[dict[str, object]] = []
        for partner in anchor.cells[1:]:
            pivot_delta = step / anchor.occurrences[pivot]
            partner_delta = -step / anchor.occurrences[partner]
            overrides = {
                pivot: values[pivot] + pivot_delta,
                partner: values[partner] + partner_delta,
            }
            if any(not math.isfinite(value) for value in overrides.values()):
                return _abstain(relation, "non_finite_intervention", anchor.anchor_id)
            observed, error = _evaluated_output(model, target, overrides)
            if error is not None or observed is None:
                return _abstain(
                    relation,
                    "intervention_evaluation_error",
                    f"{anchor.anchor_id}: {error}",
                )
            tolerance = _tolerance(config, baseline, observed)
            relation_held = abs(observed - baseline) <= tolerance
            probes.append(
                {
                    "positive_cell": _label(pivot),
                    "negative_cell": _label(partner),
                    "aggregate_numerator_transfer": step,
                    "positive_occurrences": anchor.occurrences[pivot],
                    "negative_occurrences": anchor.occurrences[partner],
                    "positive_delta": pivot_delta,
                    "negative_delta": partner_delta,
                    "input_values_before": {
                        _label(pivot): values[pivot],
                        _label(partner): values[partner],
                    },
                    "input_values_after": {
                        _label(pivot): overrides[pivot],
                        _label(partner): overrides[partner],
                    },
                    "baseline_output_reference": baseline,
                    "observed_output": observed,
                    "absolute_change_from_baseline": abs(observed - baseline),
                    "tolerance": tolerance,
                    "relation_held": relation_held,
                }
            )
        anchor_witnesses.append(
            {
                "anchor_id": anchor.anchor_id,
                "function": anchor.function,
                "input_cells": [_label(key) for key in anchor.cells],
                "input_occurrences": {
                    _label(key): anchor.occurrences[key] for key in anchor.cells
                },
                "probes": probes,
            }
        )

    relation_holds = all(
        bool(probe["relation_held"])
        for anchor in anchor_witnesses
        for probe in anchor["probes"]  # type: ignore[union-attr]
    )
    return _characterization_result(
        relation,
        relation_holds,
        {
            "cell": _label(target),
            "formula": formula,
            "evidence_basis": "target_formula_ast_only",
            "external_assertion_source": None,
            "can_identify_formula_error": False,
            "baseline_output_reference": baseline,
            "anchors": anchor_witnesses,
            "rejected_anchors": rejected,
        },
    )


def _direct_formula_reference(
    node: object,
    current_sheet: str,
    model: WorkbookModel,
) -> CellKey | None:
    if not isinstance(node, Ref):
        return None
    key = (node.sheet or current_sheet, node.address.a1.replace("$", ""))
    return key if key in model.formulas else None


def _single_plain_aggregate(
    model: WorkbookModel,
    key: CellKey,
) -> _AggregateAnchor | None:
    try:
        node = model.ast(model.formulas[key])
    except FormulaSyntaxError:
        return None
    anchors, rejected = _aggregate_anchors(node, key[0])
    if rejected or len(anchors) != 1:
        return None
    anchor = anchors[0]
    if any(cell in model.formulas for cell in anchor.cells):
        return None
    return anchor


def _is_one_cell_boundary_extension(
    left: Iterable[CellKey],
    right: Iterable[CellKey],
) -> bool:
    left_set, right_set = set(left), set(right)
    if len(left_set ^ right_set) != 1:
        return False
    union = left_set | right_set
    sheets = {key[0] for key in union}
    if len(sheets) != 1:
        return False
    coordinates = [parse_address(key[1]) for key in union]
    rows = sorted({address.row for address in coordinates})
    columns = sorted({address.col for address in coordinates})
    if len(columns) == 1:
        axis = sorted(address.row for address in coordinates)
    elif len(rows) == 1:
        axis = sorted(address.col for address in coordinates)
    else:
        return False
    if axis != list(range(axis[0], axis[-1] + 1)):
        return False
    changed = next(iter(left_set ^ right_set))
    address = parse_address(changed[1])
    coordinate = address.row if len(columns) == 1 else address.col
    return coordinate in {axis[0], axis[-1]}


def _coefficients_close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)


def _redundant_path_relation(
    model: WorkbookModel,
    target: CellKey,
    formula: str,
    node: Node,
    analyzer: _AffineAnalyzer,
    baseline_values: Mapping[CellKey, object],
    baseline: float,
    config: MetamorphicOracleConfig,
) -> dict[str, object]:
    relation = "redundant_path_invariance"
    if not isinstance(node, Binary) or node.op != "-":
        return _abstain(relation, "not_explicit_path_residual")
    left_key = _direct_formula_reference(node.left, target[0], model)
    right_key = _direct_formula_reference(node.right, target[0], model)
    if left_key is None or right_key is None or left_key == right_key:
        return _abstain(relation, "residual_operands_are_not_distinct_formula_paths")

    graph = model.dependency_graph()
    if right_key in graph.ancestors(left_key) or left_key in graph.ancestors(right_key):
        return _abstain(relation, "paths_are_not_independent")
    left_anchor = _single_plain_aggregate(model, left_key)
    right_anchor = _single_plain_aggregate(model, right_key)
    if left_anchor is None or right_anchor is None:
        return _abstain(relation, "path_without_single_plain_aggregate")
    if left_anchor.function != right_anchor.function:
        return _abstain(relation, "aggregate_function_mismatch")

    left_output = _finite_number(baseline_values.get(left_key))
    right_output = _finite_number(baseline_values.get(right_key))
    if left_output is None or right_output is None:
        return _abstain(relation, "non_numeric_path_output")
    balance_tolerance = _tolerance(config, left_output, right_output, baseline)
    if (
        abs(left_output - right_output) > balance_tolerance
        or abs(baseline) > balance_tolerance
    ):
        return _abstain(relation, "paths_not_balanced_at_baseline")

    try:
        left_affine = analyzer.cell(left_key)
        right_affine = analyzer.cell(right_key)
    except _Reject as exc:
        return _abstain(relation, exc.reason, exc.detail)
    if not _coefficients_close(left_affine.intercept, right_affine.intercept):
        return _abstain(relation, "path_intercept_mismatch")

    inputs = _sorted_cells(
        set(left_affine.coefficients) | set(right_affine.coefficients)
    )
    if len(inputs) > config.max_input_cells:
        return _abstain(relation, "input_budget_exceeded", str(len(inputs)))
    matching = [
        key
        for key in inputs
        if key in left_affine.coefficients
        and key in right_affine.coefficients
        and _coefficients_close(
            left_affine.coefficients[key], right_affine.coefficients[key]
        )
    ]
    mismatches = [
        key
        for key in inputs
        if not _coefficients_close(
            left_affine.coefficients.get(key, 0.0),
            right_affine.coefficients.get(key, 0.0),
        )
    ]
    if len(matching) < 2:
        return _abstain(
            relation, "insufficient_shared_path_sensitivity", str(len(matching))
        )
    if len(mismatches) > config.max_redundant_path_mismatches:
        return _abstain(relation, "paths_not_near_equivalent", str(len(mismatches)))

    left_domain, right_domain = set(left_anchor.cells), set(right_anchor.cells)
    if mismatches:
        domain_difference = left_domain ^ right_domain
        if (
            left_anchor.function != "SUM"
            or set(mismatches) != domain_difference
            or not _is_one_cell_boundary_extension(left_domain, right_domain)
        ):
            return _abstain(relation, "difference_is_not_single_sum_boundary")
    elif left_domain != right_domain:
        return _abstain(
            relation, "aggregate_domains_differ_without_sensitivity_evidence"
        )

    try:
        input_values = _input_values(model, inputs)
    except _Reject as exc:
        return _abstain(relation, exc.reason, exc.detail)
    probes: list[dict[str, object]] = []
    for key in inputs:
        before = input_values[key]
        step = max(config.minimum_step, abs(before) * config.step_fraction)
        after = before + step
        if not math.isfinite(after):
            return _abstain(relation, "non_finite_intervention", _label(key))
        observed, error = _evaluated_output(model, target, {key: after})
        if error is not None or observed is None:
            return _abstain(
                relation, "intervention_evaluation_error", f"{_label(key)}: {error}"
            )
        tolerance = _tolerance(config, baseline, observed)
        relation_held = abs(observed - baseline) <= tolerance
        probes.append(
            {
                "input_cell": _label(key),
                "input_before": before,
                "input_after": after,
                "step": step,
                "baseline_residual_reference": baseline,
                "observed_residual": observed,
                "absolute_change_from_baseline": abs(observed - baseline),
                "tolerance": tolerance,
                "relation_held": relation_held,
            }
        )

    relation_holds = all(bool(probe["relation_held"]) for probe in probes)
    return _characterization_result(
        relation,
        relation_holds,
        {
            "cell": _label(target),
            "formula": formula,
            "evidence_basis": "target_formula_and_baseline_only",
            "external_assertion_source": None,
            "can_identify_formula_error": False,
            "localization": "ambiguous_between_paths",
            "left_path": {
                "cell": _label(left_key),
                "formula": model.formulas[left_key],
                "aggregate_function": left_anchor.function,
                "aggregate_domain": [_label(key) for key in left_anchor.cells],
                "baseline_output": left_output,
            },
            "right_path": {
                "cell": _label(right_key),
                "formula": model.formulas[right_key],
                "aggregate_function": right_anchor.function,
                "aggregate_domain": [_label(key) for key in right_anchor.cells],
                "baseline_output": right_output,
            },
            "matching_sensitivity_cells": [_label(key) for key in matching],
            "mismatched_sensitivity_cells": [_label(key) for key in mismatches],
            "baseline_residual_reference": baseline,
            "probes": probes,
        },
    )


def audit_metamorphic_oracles(
    model: WorkbookModel,
    config: MetamorphicOracleConfig | None = None,
) -> dict[str, object]:
    """Audit every formula cell with selective, label-free metamorphic checks."""

    config = config or MetamorphicOracleConfig()
    baseline_values, baseline_errors = model.evaluate()
    analyzer = _AffineAnalyzer(model)
    records: list[dict[str, object]] = []

    for target in model.formula_cells:
        formula = model.formulas[target]
        relations: list[dict[str, object]]
        if target in baseline_errors:
            relations = [
                _abstain(relation, "baseline_evaluation_error", baseline_errors[target])
                for relation in RELATIONS
            ]
        else:
            baseline = _finite_number(baseline_values.get(target))
            if baseline is None:
                relations = [
                    _abstain(relation, "non_numeric_baseline_output")
                    for relation in RELATIONS
                ]
            else:
                try:
                    node = model.ast(formula)
                    affine = analyzer.cell(target)
                except FormulaSyntaxError as exc:
                    reason, detail = "unsupported_formula", str(exc)
                except _Reject as exc:
                    reason, detail = exc.reason, exc.detail
                else:
                    relations = [
                        _scaling_relation(
                            model, target, formula, affine, baseline, config
                        ),
                        _conservation_relation(
                            model, target, formula, node, baseline, config
                        ),
                        _redundant_path_relation(
                            model,
                            target,
                            formula,
                            node,
                            analyzer,
                            baseline_values,
                            baseline,
                            config,
                        ),
                    ]
                    reason = detail = None
                if reason is not None:
                    relations = [
                        _abstain(relation, reason, detail) for relation in RELATIONS
                    ]

        relation_holds_count = sum(
            result["relation_holds"] is True for result in relations
        )
        ambiguity_count = sum(result["ambiguous"] is True for result in relations)
        applicable_count = sum(result["applicability"] is True for result in relations)
        status = (
            "ambiguous"
            if ambiguity_count
            else ("characterized" if relation_holds_count else "abstained")
        )
        records.append(
            {
                "cell": _label(target),
                "formula": formula,
                "status": status,
                "applicable_relations": applicable_count,
                "relation_holds_count": relation_holds_count,
                "ambiguity_count": ambiguity_count,
                "violation_count": 0,
                "relations": relations,
            }
        )

    summary = {
        "formula_cells": len(records),
        "applicable_relations": sum(
            int(record["applicable_relations"]) for record in records
        ),
        "relations_holding": sum(
            int(record["relation_holds_count"]) for record in records
        ),
        "ambiguities": sum(int(record["ambiguity_count"]) for record in records),
        "violations": 0,
        "abstentions": sum(
            len(RELATIONS) - int(record["applicable_relations"]) for record in records
        ),
        "cells_characterized": sum(
            record["status"] == "characterized" for record in records
        ),
        "cells_with_ambiguities": sum(
            record["status"] == "ambiguous" for record in records
        ),
        "cells_abstained": sum(record["status"] == "abstained" for record in records),
        "cells_with_violations": 0,
    }
    return {
        "protocol": PROTOCOL,
        "label_free": True,
        "peer_comparison": False,
        "external_assertion_source": None,
        "can_identify_formula_error": False,
        "config": config.as_dict(),
        "summary": summary,
        "ambiguous_cells": [
            record["cell"] for record in records if record["status"] == "ambiguous"
        ],
        "violation_cells": [],
        "records": records,
    }


def validate_metamorphic_output(payload: Mapping[str, object]) -> list[str]:
    """Return structural audit errors for a serialized oracle result."""

    errors: list[str] = []
    if payload.get("protocol") != PROTOCOL:
        errors.append("unexpected protocol")
    if payload.get("label_free") is not True:
        errors.append("result is not marked label-free")
    if payload.get("peer_comparison") is not False:
        errors.append("peer comparison must be disabled")
    if "external_assertion_source" not in payload:
        errors.append("external assertion source must be stated")
    elif payload.get("external_assertion_source") is not None:
        errors.append("external assertion source must be absent")
    if payload.get("can_identify_formula_error") is not False:
        errors.append("formula error identifiability must be false")
    if payload.get("violation_cells") != []:
        errors.append("violation_cells must be empty for characterization output")
    records = payload.get("records")
    if not isinstance(records, list):
        return errors + ["records must be a list"]
    calculated_applicable = 0
    calculated_holding = 0
    calculated_ambiguities = 0
    calculated_abstentions = 0
    calculated_ambiguous_cells: list[object] = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            errors.append(f"record {index} is not an object")
            continue
        if record.get("violation_count") != 0:
            errors.append(f"record {index} has a nonzero violation count")
        relations = record.get("relations")
        if not isinstance(relations, list) or len(relations) != len(RELATIONS):
            errors.append(f"record {index} has an invalid relation list")
            continue
        names = tuple(
            relation.get("relation") if isinstance(relation, Mapping) else None
            for relation in relations
        )
        if names != RELATIONS:
            errors.append(f"record {index} relation order is not deterministic")
        relation_holds_count = 0
        ambiguity_count = 0
        applicable_count = 0
        for relation in relations:
            if not isinstance(relation, Mapping):
                errors.append(f"record {index} relation is not an object")
                continue
            state_names = ("applicability", "relation_holds", "ambiguous", "violation")
            if any(not isinstance(relation.get(name), bool) for name in state_names):
                errors.append(f"record {index} relation has a missing or invalid state")
            applicable = relation.get("applicability") is True
            relation_holds = relation.get("relation_holds") is True
            ambiguous = relation.get("ambiguous") is True
            violation = relation.get("violation") is True
            outcome = relation.get("outcome")
            if relation.get("role") != RELATION_ROLES.get(
                str(relation.get("relation"))
            ):
                errors.append(f"record {index} relation has an invalid role")
            if relation.get("role") != "characterization":
                errors.append(f"record {index} relation is not a characterization")
            if violation:
                errors.append(f"record {index} characterization claims a violation")
            expected_state = {
                "relation_holds": (True, True, False),
                "ambiguous": (True, False, True),
                "abstain": (False, False, False),
            }.get(str(outcome))
            if expected_state is None:
                errors.append(f"record {index} relation has an invalid outcome")
            elif (applicable, relation_holds, ambiguous) != expected_state:
                errors.append(f"record {index} relation has inconsistent outcome state")
            if relation_holds and ambiguous:
                errors.append(f"record {index} relation both holds and is ambiguous")
            ambiguity_reason = relation.get("ambiguity_reason")
            if ambiguous and (
                not isinstance(ambiguity_reason, str) or not ambiguity_reason
            ):
                errors.append(f"record {index} ambiguity lacks a reason")
            if not ambiguous and ambiguity_reason is not None:
                errors.append(f"record {index} non-ambiguity has an ambiguity reason")
            witness = relation.get("witness")
            if applicable and not isinstance(witness, Mapping):
                errors.append(f"record {index} applicable relation lacks a witness")
            if isinstance(witness, Mapping) and applicable:
                if (
                    "external_assertion_source" not in witness
                    or witness.get("external_assertion_source") is not None
                ):
                    errors.append(
                        f"record {index} witness has an external assertion source"
                    )
                if witness.get("can_identify_formula_error") is not False:
                    errors.append(
                        f"record {index} witness claims formula error identification"
                    )
            if not applicable and not relation.get("rejection_reason"):
                errors.append(f"record {index} abstention lacks a rejection reason")
            if applicable and relation.get("rejection_reason") is not None:
                errors.append(
                    f"record {index} applicable relation has a rejection reason"
                )
            applicable_count += int(applicable)
            relation_holds_count += int(relation_holds)
            ambiguity_count += int(ambiguous)

        if record.get("applicable_relations") != applicable_count:
            errors.append(f"record {index} has an inconsistent applicable count")
        if record.get("relation_holds_count") != relation_holds_count:
            errors.append(f"record {index} has an inconsistent relation-holds count")
        if record.get("ambiguity_count") != ambiguity_count:
            errors.append(f"record {index} has an inconsistent ambiguity count")
        expected_status = (
            "ambiguous"
            if ambiguity_count
            else ("characterized" if relation_holds_count else "abstained")
        )
        if record.get("status") != expected_status:
            errors.append(f"record {index} has an inconsistent status")
        calculated_applicable += applicable_count
        calculated_holding += relation_holds_count
        calculated_ambiguities += ambiguity_count
        calculated_abstentions += len(RELATIONS) - applicable_count
        if ambiguity_count:
            calculated_ambiguous_cells.append(record.get("cell"))

    if payload.get("ambiguous_cells") != calculated_ambiguous_cells:
        errors.append("ambiguous_cells does not match relation outcomes")
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        errors.append("summary must be an object")
    else:
        expected_summary = {
            "formula_cells": len(records),
            "applicable_relations": calculated_applicable,
            "relations_holding": calculated_holding,
            "ambiguities": calculated_ambiguities,
            "violations": 0,
            "abstentions": calculated_abstentions,
            "cells_characterized": sum(
                isinstance(record, Mapping)
                and record.get("status") == "characterized"
                for record in records
            ),
            "cells_with_ambiguities": len(calculated_ambiguous_cells),
            "cells_abstained": sum(
                isinstance(record, Mapping) and record.get("status") == "abstained"
                for record in records
            ),
            "cells_with_violations": 0,
        }
        for name, expected in expected_summary.items():
            if summary.get(name) != expected:
                errors.append(f"summary has an inconsistent {name}")
    return errors


def audit_workbook(
    model: WorkbookModel,
    config: MetamorphicOracleConfig | None = None,
) -> dict[str, object]:
    """Module-local convenience alias for :func:`audit_metamorphic_oracles`."""

    return audit_metamorphic_oracles(model, config)
