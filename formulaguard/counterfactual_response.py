"""Deterministic label-free response signatures from numeric input probes.

The mechanism perturbs numeric leaf ancestors of one formula cell in memory.
It records two-sided finite differences at a full and half step for the target
and its formula descendants.  The result is evidence about local workbook
behaviour, not a correctness verdict: a structurally connected input may be
locally inactive because of a branch, a minimum/maximum, or cancellation.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from .a1 import parse_address
from .workbook import CellKey, DependencyGraph, WorkbookModel

PROTOCOL = "formulaguard_counterfactual_response_v1"


def _cell_label(cell: CellKey) -> str:
    return f"{cell[0]}!{cell[1]}"


def _cell_sort(cell: CellKey) -> tuple[str, int, int, str]:
    address = parse_address(cell[1])
    return cell[0], address.row, address.col, cell[1]


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _direction(value: float, tolerance: float) -> int:
    if value > tolerance:
        return 1
    if value < -tolerance:
        return -1
    return 0


@dataclass(frozen=True)
class CounterfactualResponseConfig:
    """Frozen numerical policy for a local response signature."""

    relative_step: float = 0.05
    half_step_ratio: float = 0.5
    normalization_floor: float = 1.0
    minimum_step: float = 1e-6
    response_tolerance: float = 1e-9
    max_inputs: int = 32
    max_downstream: int = 64

    def validate(self) -> None:
        finite_positive = {
            "relative_step": self.relative_step,
            "half_step_ratio": self.half_step_ratio,
            "normalization_floor": self.normalization_floor,
            "minimum_step": self.minimum_step,
            "response_tolerance": self.response_tolerance,
        }
        for name, value in finite_positive.items():
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if self.relative_step >= 1.0:
            raise ValueError("relative_step must be less than one")
        if self.half_step_ratio >= 1.0:
            raise ValueError("half_step_ratio must be less than one")
        if (
            not isinstance(self.max_inputs, int)
            or isinstance(self.max_inputs, bool)
            or self.max_inputs < 1
        ):
            raise ValueError("max_inputs must be a positive integer")
        if (
            not isinstance(self.max_downstream, int)
            or isinstance(self.max_downstream, bool)
            or self.max_downstream < 0
        ):
            raise ValueError("max_downstream must be a nonnegative integer")

    def as_dict(self) -> dict[str, object]:
        return {
            "relative_step": self.relative_step,
            "half_step_ratio": self.half_step_ratio,
            "normalization_floor": self.normalization_floor,
            "minimum_step": self.minimum_step,
            "response_tolerance": self.response_tolerance,
            "max_inputs": self.max_inputs,
            "max_downstream": self.max_downstream,
        }


@dataclass(frozen=True)
class ResponseRejection:
    """A deterministic exclusion from the response surface."""

    reason: str
    cell: CellKey
    detail: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "reason": self.reason,
            "cell": _cell_label(self.cell),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class EvaluationIssue:
    """A failed or nonnumeric evaluation at one perturbation stage."""

    stage: str
    response_cell: CellKey
    input_cell: CellKey | None
    reason: str
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "response_cell": _cell_label(self.response_cell),
            "input_cell": _cell_label(self.input_cell) if self.input_cell else None,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class FiniteDifferenceResponse:
    """Two-sided local response of one formula cell to one numeric input."""

    cell: CellKey
    role: str
    path: tuple[CellKey, ...]
    base_value: float
    positive_value: float
    negative_value: float
    half_positive_value: float | None
    half_negative_value: float | None
    positive_direction: int
    negative_direction: int
    direction: int
    positive_normalized_magnitude: float
    negative_normalized_magnitude: float
    normalized_magnitude: float
    central_normalized_difference: float
    symmetry_residual: float
    nonlinearity_residual: float | None
    active: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "cell": _cell_label(self.cell),
            "role": self.role,
            "path": [_cell_label(cell) for cell in self.path],
            "base_value": self.base_value,
            "positive_value": self.positive_value,
            "negative_value": self.negative_value,
            "half_positive_value": self.half_positive_value,
            "half_negative_value": self.half_negative_value,
            "positive_direction": self.positive_direction,
            "negative_direction": self.negative_direction,
            "direction": self.direction,
            "positive_normalized_magnitude": self.positive_normalized_magnitude,
            "negative_normalized_magnitude": self.negative_normalized_magnitude,
            "normalized_magnitude": self.normalized_magnitude,
            "central_normalized_difference": self.central_normalized_difference,
            "symmetry_residual": self.symmetry_residual,
            "nonlinearity_residual": self.nonlinearity_residual,
            "active": self.active,
        }


@dataclass(frozen=True)
class ResponseWitness:
    """The strongest auditable path, or an explicit local-inactivity witness."""

    kind: str
    input_cell: CellKey
    response_cell: CellKey
    path: tuple[CellKey, ...]
    direction: int
    normalized_magnitude: float
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "input_cell": _cell_label(self.input_cell),
            "response_cell": _cell_label(self.response_cell),
            "path": [_cell_label(cell) for cell in self.path],
            "direction": self.direction,
            "normalized_magnitude": self.normalized_magnitude,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class InputResponseProbe:
    """All target and downstream responses for one selected input."""

    input_cell: CellKey
    base_value: float
    input_scale: float
    step: float
    path_to_target: tuple[CellKey, ...]
    status: str
    rejection_reason: str | None
    target_response: FiniteDifferenceResponse | None
    downstream_responses: tuple[FiniteDifferenceResponse, ...]
    evaluable_downstream_count: int
    responsive_downstream_count: int
    propagation_coverage: float
    issues: tuple[EvaluationIssue, ...]
    witness: ResponseWitness

    def as_dict(self) -> dict[str, object]:
        return {
            "input_cell": _cell_label(self.input_cell),
            "base_value": self.base_value,
            "input_scale": self.input_scale,
            "step": self.step,
            "path_to_target": [_cell_label(cell) for cell in self.path_to_target],
            "status": self.status,
            "rejection_reason": self.rejection_reason,
            "target_response": self.target_response.as_dict()
            if self.target_response
            else None,
            "downstream_responses": [
                row.as_dict() for row in self.downstream_responses
            ],
            "evaluable_downstream_count": self.evaluable_downstream_count,
            "responsive_downstream_count": self.responsive_downstream_count,
            "propagation_coverage": self.propagation_coverage,
            "issues": [row.as_dict() for row in self.issues],
            "witness": self.witness.as_dict(),
        }


@dataclass(frozen=True)
class CounterfactualResponseSignature:
    """Label-free numerical response evidence for one target formula."""

    target: CellKey
    eligible: bool
    rejection_reason: str | None
    base_target_value: float | None
    selected_inputs: tuple[CellKey, ...]
    downstream_cells: tuple[CellKey, ...]
    probes: tuple[InputResponseProbe, ...]
    propagation_coverage: float
    responsive_downstream_pairs: int
    evaluable_downstream_pairs: int
    rejections: tuple[ResponseRejection, ...]
    errors: tuple[EvaluationIssue, ...]
    witness: ResponseWitness | None
    config: CounterfactualResponseConfig
    protocol: str = PROTOCOL

    def as_dict(self) -> dict[str, object]:
        return {
            "protocol": self.protocol,
            "target": _cell_label(self.target),
            "eligible": self.eligible,
            "rejection_reason": self.rejection_reason,
            "base_target_value": self.base_target_value,
            "selected_inputs": [_cell_label(cell) for cell in self.selected_inputs],
            "downstream_cells": [_cell_label(cell) for cell in self.downstream_cells],
            "probes": [probe.as_dict() for probe in self.probes],
            "propagation_coverage": self.propagation_coverage,
            "responsive_downstream_pairs": self.responsive_downstream_pairs,
            "evaluable_downstream_pairs": self.evaluable_downstream_pairs,
            "rejections": [row.as_dict() for row in self.rejections],
            "errors": [row.as_dict() for row in self.errors],
            "witness": self.witness.as_dict() if self.witness else None,
            "config": self.config.as_dict(),
        }


@dataclass(frozen=True)
class _Evaluation:
    values: Mapping[CellKey, object]
    errors: Mapping[CellKey, str]
    exception: str | None = None


def _run_evaluation(
    model: WorkbookModel, input_cell: CellKey, value: float
) -> _Evaluation:
    try:
        values, errors = model.evaluate(value_overrides={input_cell: value})
    except Exception as exc:  # noqa: BLE001 - probe failures are evidence, not run failures.
        return _Evaluation({}, {}, f"{type(exc).__name__}: {exc}")
    return _Evaluation(values, errors)


def _stage_value(
    evaluation: _Evaluation,
    *,
    stage: str,
    response_cell: CellKey,
    input_cell: CellKey,
) -> tuple[float | None, EvaluationIssue | None]:
    if evaluation.exception is not None:
        return None, EvaluationIssue(
            stage,
            response_cell,
            input_cell,
            "evaluation_exception",
            evaluation.exception,
        )
    if response_cell in evaluation.errors:
        return None, EvaluationIssue(
            stage,
            response_cell,
            input_cell,
            "evaluation_error",
            evaluation.errors[response_cell],
        )
    value = _finite_number(evaluation.values.get(response_cell))
    if value is None:
        return None, EvaluationIssue(
            stage,
            response_cell,
            input_cell,
            "nonnumeric_result",
            repr(evaluation.values.get(response_cell)),
        )
    return value, None


def _response_path(
    graph: DependencyGraph,
    input_path: tuple[CellKey, ...],
    target: CellKey,
    response_cell: CellKey,
) -> tuple[CellKey, ...]:
    if response_cell == target:
        return input_path
    suffix = graph.shortest_path(target, response_cell)
    if suffix is None:
        return (*input_path, response_cell)
    return (*input_path[:-1], *suffix)


def _measure_response(
    *,
    graph: DependencyGraph,
    input_cell: CellKey,
    input_path: tuple[CellKey, ...],
    target: CellKey,
    response_cell: CellKey,
    base_value: float,
    input_scale: float,
    step: float,
    config: CounterfactualResponseConfig,
    evaluations: Mapping[str, _Evaluation],
) -> tuple[FiniteDifferenceResponse | None, tuple[EvaluationIssue, ...]]:
    stage_values: dict[str, float | None] = {}
    issues: list[EvaluationIssue] = []
    for stage in ("positive", "negative", "half_positive", "half_negative"):
        value, issue = _stage_value(
            evaluations[stage],
            stage=stage,
            response_cell=response_cell,
            input_cell=input_cell,
        )
        stage_values[stage] = value
        if issue is not None:
            issues.append(issue)

    positive = stage_values["positive"]
    negative = stage_values["negative"]
    if positive is None or negative is None:
        return None, tuple(issues)

    output_scale = max(abs(base_value), config.normalization_floor)
    scale_ratio = input_scale / output_scale
    positive_difference = ((positive - base_value) / step) * scale_ratio
    negative_difference = ((base_value - negative) / step) * scale_ratio
    central_difference = positive_difference / 2.0 + negative_difference / 2.0
    if not all(
        math.isfinite(value)
        for value in (
            positive_difference,
            negative_difference,
            central_difference,
        )
    ):
        issues.append(
            EvaluationIssue(
                "finite_difference",
                response_cell,
                input_cell,
                "nonfinite_finite_difference",
                "normalized difference overflowed",
            )
        )
        return None, tuple(issues)
    positive_magnitude = abs(positive_difference)
    negative_magnitude = abs(negative_difference)
    normalized_magnitude = positive_magnitude / 2.0 + negative_magnitude / 2.0
    symmetry_scale = max(
        positive_magnitude,
        negative_magnitude,
        config.response_tolerance,
    )
    scaled_positive = positive_difference / symmetry_scale
    scaled_negative = negative_difference / symmetry_scale
    symmetry_residual = abs(scaled_positive - scaled_negative) / max(
        abs(scaled_positive) + abs(scaled_negative),
        config.response_tolerance / symmetry_scale,
    )

    half_positive = stage_values["half_positive"]
    half_negative = stage_values["half_negative"]
    nonlinearity_residual: float | None = None
    if half_positive is not None and half_negative is not None:
        half_step = step * config.half_step_ratio
        half_forward = ((half_positive - base_value) / half_step) * scale_ratio
        half_backward = ((base_value - half_negative) / half_step) * scale_ratio
        half_central = half_forward / 2.0 + half_backward / 2.0
        if all(
            math.isfinite(value)
            for value in (half_forward, half_backward, half_central)
        ):
            nonlinearity_scale = max(
                abs(central_difference),
                abs(half_central),
                config.response_tolerance,
            )
            scaled_full = central_difference / nonlinearity_scale
            scaled_half = half_central / nonlinearity_scale
            nonlinearity_residual = abs(scaled_full - scaled_half) / max(
                abs(scaled_full) + abs(scaled_half),
                config.response_tolerance / nonlinearity_scale,
            )
        else:
            issues.append(
                EvaluationIssue(
                    "half_finite_difference",
                    response_cell,
                    input_cell,
                    "nonfinite_finite_difference",
                    "half-step normalized difference overflowed",
                )
            )

    role = "target" if response_cell == target else "downstream"
    response = FiniteDifferenceResponse(
        cell=response_cell,
        role=role,
        path=_response_path(graph, input_path, target, response_cell),
        base_value=base_value,
        positive_value=positive,
        negative_value=negative,
        half_positive_value=half_positive,
        half_negative_value=half_negative,
        positive_direction=_direction(positive_difference, config.response_tolerance),
        negative_direction=_direction(negative_difference, config.response_tolerance),
        direction=_direction(central_difference, config.response_tolerance),
        positive_normalized_magnitude=positive_magnitude,
        negative_normalized_magnitude=negative_magnitude,
        normalized_magnitude=normalized_magnitude,
        central_normalized_difference=central_difference,
        symmetry_residual=symmetry_residual,
        nonlinearity_residual=nonlinearity_residual,
        active=normalized_magnitude > config.response_tolerance,
    )
    return response, tuple(issues)


def _probe_witness(
    input_cell: CellKey,
    input_path: tuple[CellKey, ...],
    target: CellKey,
    target_response: FiniteDifferenceResponse | None,
    downstream_responses: tuple[FiniteDifferenceResponse, ...],
) -> ResponseWitness:
    responses = tuple(
        response
        for response in (target_response, *downstream_responses)
        if response is not None
    )
    active = [response for response in responses if response.active]
    if active:
        strongest = min(
            active,
            key=lambda row: (
                -row.normalized_magnitude,
                0 if row.role == "target" else 1,
                _cell_sort(row.cell),
            ),
        )
        return ResponseWitness(
            kind="strongest_response",
            input_cell=input_cell,
            response_cell=strongest.cell,
            path=strongest.path,
            direction=strongest.direction,
            normalized_magnitude=strongest.normalized_magnitude,
            detail="largest_normalized_response",
        )
    if target_response is not None:
        return ResponseWitness(
            kind="locally_inactive",
            input_cell=input_cell,
            response_cell=target,
            path=target_response.path,
            direction=target_response.direction,
            normalized_magnitude=target_response.normalized_magnitude,
            detail="dependency_path_present_but_no_local_numeric_response",
        )
    return ResponseWitness(
        kind="probe_rejected",
        input_cell=input_cell,
        response_cell=target,
        path=input_path,
        direction=0,
        normalized_magnitude=0.0,
        detail="target_response_unavailable",
    )


def _empty_signature(
    *,
    target: CellKey,
    reason: str,
    config: CounterfactualResponseConfig,
    base_target_value: float | None = None,
    downstream_cells: tuple[CellKey, ...] = (),
    rejections: tuple[ResponseRejection, ...] = (),
    errors: tuple[EvaluationIssue, ...] = (),
) -> CounterfactualResponseSignature:
    return CounterfactualResponseSignature(
        target=target,
        eligible=False,
        rejection_reason=reason,
        base_target_value=base_target_value,
        selected_inputs=(),
        downstream_cells=downstream_cells,
        probes=(),
        propagation_coverage=0.0,
        responsive_downstream_pairs=0,
        evaluable_downstream_pairs=0,
        rejections=rejections,
        errors=errors,
        witness=None,
        config=config,
    )


def build_counterfactual_response_signature(
    model: WorkbookModel,
    target: CellKey,
    *,
    config: CounterfactualResponseConfig | None = None,
    graph: DependencyGraph | None = None,
) -> CounterfactualResponseSignature:
    """Build one deterministic, label-free upstream response signature.

    Numeric leaf ancestors are ordered by dependency depth and cell position.
    For each selected input, the workbook is evaluated at ``x +/- h`` and
    ``x +/- half_step`` through ``WorkbookModel.evaluate(value_overrides=...)``.
    No workbook state is mutated and no expected formula or error label enters
    the computation.
    """

    resolved = config or CounterfactualResponseConfig()
    resolved.validate()
    if target not in model.formulas:
        return _empty_signature(
            target=target,
            reason="target_not_formula",
            config=resolved,
            rejections=(ResponseRejection("target_not_formula", target),),
        )

    dependency_graph = graph or model.dependency_graph()
    formula_cells = set(model.formulas)
    downstream = sorted(
        dependency_graph.descendants(target) & formula_cells,
        key=lambda cell: (
            dependency_graph.shortest_path_length(target, cell) or 0,
            _cell_sort(cell),
        ),
    )
    rejections: list[ResponseRejection] = []
    for cell in downstream[resolved.max_downstream :]:
        rejections.append(ResponseRejection("downstream_budget_exceeded", cell))
    downstream_cells = tuple(downstream[: resolved.max_downstream])

    base_values, base_errors = model.evaluate()
    if target in base_errors:
        issue = EvaluationIssue(
            "base", target, None, "evaluation_error", base_errors[target]
        )
        return _empty_signature(
            target=target,
            reason="target_base_evaluation_error",
            config=resolved,
            downstream_cells=downstream_cells,
            rejections=tuple(rejections),
            errors=(issue,),
        )
    base_target = _finite_number(base_values.get(target))
    if base_target is None:
        issue = EvaluationIssue(
            "base",
            target,
            None,
            "nonnumeric_result",
            repr(base_values.get(target)),
        )
        return _empty_signature(
            target=target,
            reason="target_base_nonnumeric",
            config=resolved,
            downstream_cells=downstream_cells,
            rejections=tuple(rejections),
            errors=(issue,),
        )

    base_response_values: dict[CellKey, float] = {target: base_target}
    for cell in downstream_cells:
        if cell in base_errors:
            rejections.append(
                ResponseRejection(
                    "downstream_base_evaluation_error",
                    cell,
                    base_errors[cell],
                )
            )
            continue
        value = _finite_number(base_values.get(cell))
        if value is None:
            rejections.append(
                ResponseRejection(
                    "downstream_base_nonnumeric",
                    cell,
                    repr(base_values.get(cell)),
                )
            )
            continue
        base_response_values[cell] = value

    candidates: list[tuple[int, tuple[str, int, int, str], CellKey, float]] = []
    ancestors = dependency_graph.ancestors(target)
    for cell in sorted(ancestors - formula_cells, key=_cell_sort):
        if cell not in model.cells:
            rejections.append(ResponseRejection("missing_input_value", cell))
            continue
        raw_value = model.cells[cell]
        value = _finite_number(raw_value)
        if value is None:
            reason = (
                "boolean_input"
                if isinstance(raw_value, bool)
                else (
                    "nonfinite_input"
                    if isinstance(raw_value, (int, float))
                    else "nonnumeric_input"
                )
            )
            rejections.append(ResponseRejection(reason, cell, repr(raw_value)))
            continue
        depth = dependency_graph.shortest_path_length(cell, target)
        if depth is None:
            rejections.append(ResponseRejection("missing_dependency_path", cell))
            continue
        candidates.append((depth, _cell_sort(cell), cell, value))
    candidates.sort()
    for _, _, cell, _ in candidates[resolved.max_inputs :]:
        rejections.append(ResponseRejection("input_budget_exceeded", cell))
    selected = candidates[: resolved.max_inputs]
    if not selected:
        return _empty_signature(
            target=target,
            reason="no_numeric_upstream_inputs",
            config=resolved,
            base_target_value=base_target,
            downstream_cells=downstream_cells,
            rejections=tuple(rejections),
        )

    probes: list[InputResponseProbe] = []
    all_issues: list[EvaluationIssue] = []
    evaluable_downstream = tuple(
        cell for cell in downstream_cells if cell in base_response_values
    )
    for _, _, input_cell, input_value in selected:
        input_scale = max(abs(input_value), resolved.normalization_floor)
        step = max(resolved.minimum_step, resolved.relative_step * input_scale)
        half_step = step * resolved.half_step_ratio
        perturbed_values = {
            "positive": input_value + step,
            "negative": input_value - step,
            "half_positive": input_value + half_step,
            "half_negative": input_value - half_step,
        }
        input_path_list = dependency_graph.shortest_path(input_cell, target)
        input_path = tuple(input_path_list or (input_cell, target))
        if not all(math.isfinite(value) for value in perturbed_values.values()):
            issue = EvaluationIssue(
                "setup",
                target,
                input_cell,
                "nonfinite_perturbation",
                repr(perturbed_values),
            )
            all_issues.append(issue)
            witness = ResponseWitness(
                "probe_rejected",
                input_cell,
                target,
                input_path,
                0,
                0.0,
                "nonfinite_perturbation",
            )
            probes.append(
                InputResponseProbe(
                    input_cell=input_cell,
                    base_value=input_value,
                    input_scale=input_scale,
                    step=step,
                    path_to_target=input_path,
                    status="rejected",
                    rejection_reason="nonfinite_perturbation",
                    target_response=None,
                    downstream_responses=(),
                    evaluable_downstream_count=len(evaluable_downstream),
                    responsive_downstream_count=0,
                    propagation_coverage=0.0,
                    issues=(issue,),
                    witness=witness,
                )
            )
            continue

        evaluations = {
            stage: _run_evaluation(model, input_cell, value)
            for stage, value in perturbed_values.items()
        }
        target_response, target_issues = _measure_response(
            graph=dependency_graph,
            input_cell=input_cell,
            input_path=input_path,
            target=target,
            response_cell=target,
            base_value=base_target,
            input_scale=input_scale,
            step=step,
            config=resolved,
            evaluations=evaluations,
        )
        probe_issues = list(target_issues)
        downstream_responses: list[FiniteDifferenceResponse] = []
        for response_cell in evaluable_downstream:
            response, issues = _measure_response(
                graph=dependency_graph,
                input_cell=input_cell,
                input_path=input_path,
                target=target,
                response_cell=response_cell,
                base_value=base_response_values[response_cell],
                input_scale=input_scale,
                step=step,
                config=resolved,
                evaluations=evaluations,
            )
            probe_issues.extend(issues)
            if response is not None:
                downstream_responses.append(response)
        downstream_tuple = tuple(downstream_responses)
        responsive_downstream = sum(response.active for response in downstream_tuple)
        propagation_coverage = (
            responsive_downstream / len(evaluable_downstream)
            if evaluable_downstream
            else 0.0
        )
        witness = _probe_witness(
            input_cell,
            input_path,
            target,
            target_response,
            downstream_tuple,
        )
        if target_response is None:
            status = "rejected"
            rejection_reason = "target_response_unavailable"
        elif probe_issues or len(downstream_tuple) != len(evaluable_downstream):
            status = "partial"
            rejection_reason = "incomplete_response_probe"
        else:
            status = "ok"
            rejection_reason = None
        issue_tuple = tuple(probe_issues)
        all_issues.extend(issue_tuple)
        probes.append(
            InputResponseProbe(
                input_cell=input_cell,
                base_value=input_value,
                input_scale=input_scale,
                step=step,
                path_to_target=input_path,
                status=status,
                rejection_reason=rejection_reason,
                target_response=target_response,
                downstream_responses=downstream_tuple,
                evaluable_downstream_count=len(evaluable_downstream),
                responsive_downstream_count=responsive_downstream,
                propagation_coverage=propagation_coverage,
                issues=issue_tuple,
                witness=witness,
            )
        )

    responsive_pairs = sum(probe.responsive_downstream_count for probe in probes)
    evaluable_pairs = sum(probe.evaluable_downstream_count for probe in probes)
    aggregate_coverage = responsive_pairs / evaluable_pairs if evaluable_pairs else 0.0
    eligible_probes = [probe for probe in probes if probe.target_response is not None]
    witness: ResponseWitness | None = None
    if probes:
        witness = min(
            (probe.witness for probe in probes),
            key=lambda row: (
                0 if row.kind == "strongest_response" else 1,
                -row.normalized_magnitude,
                _cell_sort(row.input_cell),
                _cell_sort(row.response_cell),
            ),
        )
    return CounterfactualResponseSignature(
        target=target,
        eligible=bool(eligible_probes),
        rejection_reason=None if eligible_probes else "all_input_probes_rejected",
        base_target_value=base_target,
        selected_inputs=tuple(cell for _, _, cell, _ in selected),
        downstream_cells=downstream_cells,
        probes=tuple(probes),
        propagation_coverage=aggregate_coverage,
        responsive_downstream_pairs=responsive_pairs,
        evaluable_downstream_pairs=evaluable_pairs,
        rejections=tuple(rejections),
        errors=tuple(all_issues),
        witness=witness,
        config=resolved,
    )


def build_response_signature(
    model: WorkbookModel,
    target: CellKey,
    *,
    config: CounterfactualResponseConfig | None = None,
    graph: DependencyGraph | None = None,
) -> CounterfactualResponseSignature:
    """Concise alias for :func:`build_counterfactual_response_signature`."""

    return build_counterfactual_response_signature(
        model,
        target,
        config=config,
        graph=graph,
    )
