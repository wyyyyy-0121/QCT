"""Peer-aligned consistency over counterfactual response signatures.

Unlike formula fingerprints, this module compares what nearby formulas do
under numeric interventions. Inputs are expressed relative to each target, so
algebraically different formulas such as ``=A1*2`` and ``=A1+A1`` can have the
same behavioral role. A score is emitted only when the peer responses are
coherent without consulting the target response.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field

from .a1 import parse_address
from .counterfactual_response import (
    CounterfactualResponseConfig,
    CounterfactualResponseSignature,
    build_response_signature,
)
from .workbook import CellKey, DependencyGraph, WorkbookModel

PROTOCOL = "formulaguard_behavioral_consistency_v2"


def _label(cell: CellKey) -> str:
    return f"{cell[0]}!{cell[1]}"


def _cell_sort(cell: CellKey) -> tuple[str, int, int, str]:
    address = parse_address(cell[1])
    return cell[0], address.row, address.col, cell[1]


def _coordinate(cell: CellKey) -> tuple[int, int]:
    address = parse_address(cell[1])
    return address.row, address.col


def _format_class(model: WorkbookModel, cell: CellKey) -> str:
    value = model.number_format(cell).upper()
    if "%" in value:
        return "percent"
    if any(token in value for token in ("YY", "DD", "MM", "H", "SS")):
        return "date_or_time"
    if value in {"GENERAL", "@"}:
        return value.lower()
    return "numeric_format"


@dataclass(frozen=True)
class BehavioralConsistencyConfig:
    """Fixed engineering bounds for the response-neighborhood audit."""

    axis_radius: int = 8
    min_peers: int = 3
    max_peers: int = 8
    max_peer_coherence: float = 0.35
    minimum_excess: float = 0.01
    response_config: CounterfactualResponseConfig = field(
        default_factory=lambda: CounterfactualResponseConfig(
            max_inputs=8,
            max_downstream=0,
        )
    )

    def validate(self) -> None:
        for name in ("axis_radius", "min_peers", "max_peers"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_peers < self.min_peers:
            raise ValueError("max_peers must be at least min_peers")
        for name in ("max_peer_coherence", "minimum_excess"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0.0 <= value < 1.0:
                raise ValueError(f"{name} must be finite and in [0, 1)")
        self.response_config.validate()

    def as_dict(self) -> dict[str, object]:
        return {
            "axis_radius": self.axis_radius,
            "min_peers": self.min_peers,
            "max_peers": self.max_peers,
            "max_peer_coherence": self.max_peer_coherence,
            "minimum_excess": self.minimum_excess,
            "response_config": self.response_config.as_dict(),
        }


@dataclass(frozen=True)
class CanonicalInfluence:
    """One input effect represented relative to its target formula."""

    row_offset: int
    column_offset: int
    path_length: int
    slope: float
    elasticity: float
    direction: int
    symmetry_residual: float
    nonlinearity_residual: float | None

    @property
    def key(self) -> tuple[int, int]:
        """Return the behavioral input key; path length is diagnostic only."""

        return self.row_offset, self.column_offset

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CanonicalResponse:
    target: CellKey
    eligible: bool
    reason: str | None
    influences: tuple[CanonicalInfluence, ...]
    ignored_cross_sheet_inputs: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "target": _label(self.target),
            "eligible": self.eligible,
            "reason": self.reason,
            "ignored_cross_sheet_inputs": self.ignored_cross_sheet_inputs,
            "influences": [item.as_dict() for item in self.influences],
        }


def canonical_response(signature: CounterfactualResponseSignature) -> CanonicalResponse:
    """Project a response signature into a translation-invariant input map."""

    if not signature.eligible:
        return CanonicalResponse(
            target=signature.target,
            eligible=False,
            reason=signature.rejection_reason or "ineligible_response_signature",
            influences=(),
        )
    target_row, target_col = _coordinate(signature.target)
    influences: list[CanonicalInfluence] = []
    ignored_cross_sheet = 0
    for probe in signature.probes:
        response = probe.target_response
        if response is None:
            continue
        if probe.input_cell[0] != signature.target[0]:
            ignored_cross_sheet += 1
            continue
        input_row, input_col = _coordinate(probe.input_cell)
        forward_slope = (response.positive_value - response.base_value) / probe.step
        backward_slope = (response.base_value - response.negative_value) / probe.step
        slope = (forward_slope + backward_slope) / 2.0
        if not math.isfinite(slope):
            continue
        influences.append(
            CanonicalInfluence(
                row_offset=input_row - target_row,
                column_offset=input_col - target_col,
                path_length=max(0, len(response.path) - 1),
                slope=slope,
                elasticity=response.central_normalized_difference,
                direction=response.direction,
                symmetry_residual=response.symmetry_residual,
                nonlinearity_residual=response.nonlinearity_residual,
            )
        )
    influences.sort(key=lambda item: item.key)
    if not influences:
        return CanonicalResponse(
            target=signature.target,
            eligible=False,
            reason=(
                "cross_sheet_inputs_only"
                if ignored_cross_sheet
                else "no_evaluable_target_responses"
            ),
            influences=(),
            ignored_cross_sheet_inputs=ignored_cross_sheet,
        )
    keys = [item.key for item in influences]
    if len(keys) != len(set(keys)):
        return CanonicalResponse(
            target=signature.target,
            eligible=False,
            reason="ambiguous_relative_input_keys",
            influences=(),
            ignored_cross_sheet_inputs=ignored_cross_sheet,
        )
    return CanonicalResponse(
        target=signature.target,
        eligible=True,
        reason=None,
        influences=tuple(influences),
        ignored_cross_sheet_inputs=ignored_cross_sheet,
    )


def _bounded_log_distance(left: float, right: float) -> float:
    distance = abs(math.log1p(abs(left)) - math.log1p(abs(right)))
    return min(1.0, distance / math.log(10.0))


def _bounded_relative_distance(left: float, right: float) -> float:
    return min(1.0, abs(left - right) / max(0.25, abs(left), abs(right)))


def response_distance(left: CanonicalResponse, right: CanonicalResponse) -> float:
    """Return a bounded distance between two eligible response roles."""

    if not left.eligible or not right.eligible:
        raise ValueError("response distance requires two eligible signatures")
    left_map = {item.key: item for item in left.influences}
    right_map = {item.key: item for item in right.influences}
    union = set(left_map) | set(right_map)
    if not union:
        raise ValueError("response distance requires at least one influence")
    common = set(left_map) & set(right_map)
    support_distance = 1.0 - len(common) / len(union)
    comparisons: list[float] = []
    for key in sorted(common):
        first, second = left_map[key], right_map[key]
        direction_distance = float(first.direction != second.direction)
        slope_distance = _bounded_log_distance(first.slope, second.slope)
        elasticity_distance = _bounded_relative_distance(
            first.elasticity, second.elasticity
        )
        first_nonlinearity = first.nonlinearity_residual or 0.0
        second_nonlinearity = second.nonlinearity_residual or 0.0
        shape_distance = min(
            1.0,
            0.5 * abs(first.symmetry_residual - second.symmetry_residual)
            + 0.5 * abs(first_nonlinearity - second_nonlinearity),
        )
        comparisons.append(
            0.40 * direction_distance
            + 0.30 * slope_distance
            + 0.20 * elasticity_distance
            + 0.10 * shape_distance
        )
    common_distance = statistics.fmean(comparisons) if comparisons else 1.0
    return min(1.0, max(0.0, 0.45 * support_distance + 0.55 * common_distance))


def _nearby_cells(
    model: WorkbookModel,
    target: CellKey,
    axis: str,
    config: BehavioralConsistencyConfig,
) -> list[CellKey]:
    target_row, target_col = _coordinate(target)
    target_format = _format_class(model, target)
    candidates: list[tuple[int, tuple[str, int, int, str], CellKey]] = []
    lookup = {
        (row, col): cell
        for cell in model.formula_cells
        if cell[0] == target[0]
        for row, col in (_coordinate(cell),)
    }
    for direction in (-1, 1):
        for distance in range(1, config.axis_radius + 1):
            row = target_row if axis == "row" else target_row + direction * distance
            col = target_col + direction * distance if axis == "row" else target_col
            cell = lookup.get((row, col))
            # A blank or differently formatted formula marks a role boundary.
            if cell is None or _format_class(model, cell) != target_format:
                break
            candidates.append((distance, _cell_sort(cell), cell))
    candidates.sort()
    return [item[2] for item in candidates]


def _frozen_peer_neighborhoods(
    model: WorkbookModel,
    targets: Sequence[CellKey],
    config: BehavioralConsistencyConfig,
    graph: DependencyGraph,
) -> dict[CellKey, dict[str, tuple[CellKey, ...]]]:
    """Select peers once from the observed graph, excluding dependency chains."""

    neighborhoods: dict[CellKey, dict[str, tuple[CellKey, ...]]] = {}
    for target in targets:
        related = graph.ancestors(target) | graph.descendants(target)
        neighborhoods[target] = {
            axis: tuple(
                cell
                for cell in _nearby_cells(model, target, axis, config)
                if cell not in related
            )
            for axis in ("column", "row")
        }
    return neighborhoods


def _pairwise_median(
    peers: Sequence[CellKey],
    signatures: Mapping[CellKey, CanonicalResponse],
) -> float:
    distances = [
        response_distance(signatures[left], signatures[right])
        for index, left in enumerate(peers)
        for right in peers[index + 1 :]
    ]
    return statistics.median(distances) if distances else 1.0


def _record(
    target: CellKey,
    signatures: Mapping[CellKey, CanonicalResponse],
    config: BehavioralConsistencyConfig,
    peer_neighborhood: Mapping[str, Sequence[CellKey]],
) -> dict[str, object]:
    signature = signatures[target]
    if not signature.eligible:
        return {
            "cell": _label(target),
            "status": "abstained",
            "reason": signature.reason,
            "score": 0.0,
            "signature": signature.as_dict(),
            "witness": None,
        }
    axes: list[tuple[float, int, int, str, list[CellKey]]] = []
    for axis_index, axis in enumerate(("column", "row")):
        peers = [
            cell
            for cell in peer_neighborhood[axis]
            if cell in signatures and signatures[cell].eligible
        ][: config.max_peers]
        if len(peers) < config.min_peers:
            continue
        coherence = _pairwise_median(peers, signatures)
        if coherence <= config.max_peer_coherence:
            axes.append((coherence, -len(peers), axis_index, axis, peers))
    if not axes:
        return {
            "cell": _label(target),
            "status": "abstained",
            "reason": "no_coherent_peer_axis",
            "score": 0.0,
            "signature": signature.as_dict(),
            "witness": None,
        }
    coherence, _, _, axis, peers = min(axes)
    distances = [response_distance(signature, signatures[peer]) for peer in peers]
    target_distance = statistics.median(distances)
    threshold = min(1.0, coherence + config.minimum_excess)
    score = (
        max(0.0, target_distance - threshold) / max(1e-12, 1.0 - threshold)
        if threshold < 1.0
        else 0.0
    )
    return {
        "cell": _label(target),
        "status": "behavioral_outlier" if score > 0.0 else "consistent",
        "reason": None,
        "score": round(score, 12),
        "signature": signature.as_dict(),
        "witness": {
            "axis": axis,
            "peers": [_label(peer) for peer in peers],
            "peer_coherence": round(coherence, 12),
            "target_peer_distances": [round(value, 12) for value in distances],
            "target_distance": round(target_distance, 12),
            "minimum_excess": config.minimum_excess,
        },
    }


def audit_behavioral_consistency(
    model: WorkbookModel,
    *,
    targets: Sequence[CellKey] | None = None,
    config: BehavioralConsistencyConfig | None = None,
) -> dict[str, object]:
    """Audit selected cells using response-coherent row or column peers."""

    resolved = config or BehavioralConsistencyConfig()
    resolved.validate()
    selected = tuple(sorted(targets or model.formula_cells, key=_cell_sort))
    if len(selected) != len(set(selected)):
        raise ValueError("targets contain duplicates")
    missing = [cell for cell in selected if cell not in model.formulas]
    if missing:
        raise KeyError(f"formula target not found: {_label(missing[0])}")
    graph = model.dependency_graph()
    neighborhoods = _frozen_peer_neighborhoods(model, selected, resolved, graph)
    needed = set(selected)
    for target in selected:
        for axis in ("column", "row"):
            needed.update(neighborhoods[target][axis])
    signatures = {
        cell: canonical_response(
            build_response_signature(
                model,
                cell,
                config=resolved.response_config,
                graph=graph,
            )
        )
        for cell in sorted(needed, key=_cell_sort)
    }
    records = [
        _record(target, signatures, resolved, neighborhoods[target])
        for target in selected
    ]
    return {
        "protocol": PROTOCOL,
        "label_free": True,
        "config": resolved.as_dict(),
        "summary": {
            "targets": len(records),
            "eligible": sum(row["status"] != "abstained" for row in records),
            "abstained": sum(row["status"] == "abstained" for row in records),
            "behavioral_outliers": sum(
                row["status"] == "behavioral_outlier" for row in records
            ),
        },
        "records": records,
    }


def _clone_with_formula(
    model: WorkbookModel, target: CellKey, formula: str
) -> WorkbookModel:
    formulas = dict(model.formulas)
    formulas[target] = formula
    return WorkbookModel(
        model.cells,
        formulas,
        source="",
        cell_visibility=model.cell_visibility,
        number_formats=model.number_formats,
        sheet_visibility=model.sheet_visibility,
    )


def _witness_payload(value: object) -> object:
    if hasattr(value, "_asdict"):
        return dict(value._asdict())  # type: ignore[union-attr]
    if hasattr(value, "as_dict"):
        return value.as_dict()  # type: ignore[union-attr]
    return repr(value)


def rank_behavioral_candidates(
    model: WorkbookModel,
    target: CellKey,
    candidates: Sequence[object],
    *,
    config: BehavioralConsistencyConfig | None = None,
) -> dict[str, object]:
    """Rank candidate formulas by reduction in behavioral inconsistency."""

    resolved = config or BehavioralConsistencyConfig()
    resolved.validate()
    if target not in model.formulas:
        raise KeyError(f"formula target not found: {_label(target)}")

    observed_graph = model.dependency_graph()
    neighborhoods = _frozen_peer_neighborhoods(
        model,
        (target,),
        resolved,
        observed_graph,
    )
    peer_cells = set(neighborhoods[target]["column"]) | set(
        neighborhoods[target]["row"]
    )
    observed_signatures = {
        cell: canonical_response(
            build_response_signature(
                model,
                cell,
                config=resolved.response_config,
                graph=observed_graph,
            )
        )
        for cell in sorted({target, *peer_cells}, key=_cell_sort)
    }
    observed = _record(
        target,
        observed_signatures,
        resolved,
        neighborhoods[target],
    )
    observed_applicable = observed["status"] != "abstained"
    frozen_peer_signatures = {
        cell: signature
        for cell, signature in observed_signatures.items()
        if cell != target
    }
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for candidate in candidates:
        formula = getattr(candidate, "formula", None)
        if (
            not isinstance(formula, str)
            or not formula.startswith("=")
            or formula in seen
        ):
            continue
        seen.add(formula)
        candidate_model = _clone_with_formula(model, target, formula)
        candidate_graph = candidate_model.dependency_graph()
        candidate_signature = canonical_response(
            build_response_signature(
                candidate_model,
                target,
                config=resolved.response_config,
                graph=candidate_graph,
            )
        )
        candidate_signatures = dict(frozen_peer_signatures)
        candidate_signatures[target] = candidate_signature
        record = _record(
            target,
            candidate_signatures,
            resolved,
            neighborhoods[target],
        )
        applicable = observed_applicable and record["status"] != "abstained"
        candidate_score = float(record["score"])
        improvement = float(observed["score"]) - candidate_score if applicable else None
        rows.append(
            {
                "formula": formula,
                "edit_kind": str(getattr(candidate, "edit_kind", "unknown")),
                "edit_witness": _witness_payload(getattr(candidate, "witness", None)),
                "applicable": applicable,
                "candidate_status": record["status"],
                "candidate_score": candidate_score,
                "improvement": improvement,
                "behavior_witness": record["witness"],
            }
        )
    rows.sort(
        key=lambda row: (
            not bool(row["applicable"]),
            -float(row["improvement"]) if row["improvement"] is not None else 0.0,
            float(row["candidate_score"]),
            str(row["formula"]),
        )
    )
    return {
        "protocol": PROTOCOL,
        "target": _label(target),
        "observed_status": observed["status"],
        "observed_score": float(observed["score"]),
        "observed_witness": observed["witness"],
        "candidates": rows,
    }


__all__ = [
    "PROTOCOL",
    "BehavioralConsistencyConfig",
    "CanonicalInfluence",
    "CanonicalResponse",
    "audit_behavioral_consistency",
    "canonical_response",
    "rank_behavioral_candidates",
    "response_distance",
]
