"""V5-Core R2: dual-null causal attribution (DNCA).

The first ranking is deliberately independent of repair-candidate coverage.
Counterfactual repair is used only as a matched placebo comparison inside an
observational uncertainty set; it cannot promote an observationally remote
formula.  This keeps source localization separate from repair generation.
"""

from __future__ import annotations

import math
import statistics
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .a1 import num_to_col, parse_address
from .formula import (
    Binary,
    Func,
    Range,
    Ref,
    Unary,
    iter_refs,
    normalized_formula,
    parse_formula,
    translate_formula,
)
from .localize import (
    LocalizationResult,
    _energy,
    behavior_anomaly_scores,
    formula_anomaly_scores,
    graph_anomaly_scores,
)
from .v5_core import (
    CandidateEvidence,
    PortfolioCandidate,
    RegimeEvidence,
    _category,
    _directional_peers,
    _evaluate_candidates,
    _periodic_pattern,
    build_candidate_portfolio,
    discover_formula_regimes,
)
from .v6 import relative_ast_signature
from .workbook import CellKey, DependencyGraph, WorkbookModel

MODEL_VERSION = "v5-core-r2-dnca-dev1"
DEFAULT_CANDIDATE_LIMIT = 24
DEFAULT_INTERVENTION_LIMIT = 4
DEFAULT_MATCHED_CONTROLS = 8
DEFAULT_UNCERTAINTY_LIMIT = 12
DEFAULT_OBS_TAIL = 0.10
DEFAULT_CF_TAIL = 0.20
DEFAULT_REVIEW_TAIL = 0.25
DEFAULT_MIN_TREATMENT = 0.03
DEFAULT_CLEAN_NULL_TAIL = 0.10


@dataclass(frozen=True)
class ObservationalEvidence:
    cell: CellKey
    raw_score: float
    empirical_tail: float
    formula_residual: float
    regime_conditioned_residual: float
    behavior_residual: float
    graph_residual: float
    propagation_potential: float
    descendant_anomaly_coverage: float
    branch_spread: float
    ancestor_penalty: float
    indegree: int
    outdegree: int
    descendant_count: int
    complexity: tuple[str, int, int]
    matched_controls: tuple[CellKey, ...] = ()
    propagation_empirical_tail: float = 1.0
    exception_release: bool = False
    alarm_regime_conditioned_residual: float = 0.0


@dataclass
class PlaceboEvidence:
    cell: CellKey
    treatment: float = 0.0
    empirical_tail: float = 1.0
    best: CandidateEvidence | None = None
    control_treatments: tuple[float, ...] = ()
    matched_controls: tuple[CellKey, ...] = ()
    candidate_coverage: bool = False
    edit_category: str = ""
    raw: dict[str, object] = field(default_factory=dict)


def v5_core_r2_default_parameters() -> dict[str, object]:
    return {
        "model_version": MODEL_VERSION,
        "architecture": "dual_null_causal_attribution",
        "candidate_limit": DEFAULT_CANDIDATE_LIMIT,
        "intervention_limit": DEFAULT_INTERVENTION_LIMIT,
        "matched_controls": DEFAULT_MATCHED_CONTROLS,
        "uncertainty_limit": DEFAULT_UNCERTAINTY_LIMIT,
        "observational_tail": DEFAULT_OBS_TAIL,
        "counterfactual_tail": DEFAULT_CF_TAIL,
        "review_tail": DEFAULT_REVIEW_TAIL,
        "minimum_treatment": DEFAULT_MIN_TREATMENT,
        "clean_null_tail": DEFAULT_CLEAN_NULL_TAIL,
        "wcn_variant": "rcr_observational",
        "ancestor_weight": 0.75,
        "observational_primary_weight": 0.55,
        "observational_secondary_weight": 0.20,
        "observational_propagation_weight": 0.25,
        "formula_rank_fusion_weight": 0.0,
        "formula_rank_fusion_method": "linear_percentile",
        "formula_rank_fusion_k": 10.0,
        "protect_pre_fusion_top1": False,
        "formula_rank_fusion_scope": "global",
        "formula_probe_limit": 2,
        "formula_probe_start_rank": 2,
        "formula_probe_minimum_residual": 0.50,
        "formula_probe_minimum_corroboration": 0.10,
        "formula_probe_allow_unique_top1": False,
        "formula_probe_top1_margin": 0.04,
        "relative_ancestor_penalty": False,
        "ancestor_dominance_margin": 0.10,
        "boundary_protection": True,
        "role_replication": True,
        "adaptive_exception_release": False,
        "exception_release_tail": 0.25,
        "wcn_protected_global_max": False,
        "safe_counterfactual_reorder": False,
        "protect_observational_top1": False,
        "structural_priority_in_uncertainty": False,
        "evidence_probe_per_signal": 0,
        "evidence_probe_small_workbook_limit": 0,
        "evidence_probe_promotion_rank": 5,
        "evidence_probe_counterfactual_tail": 0.125,
        "evidence_probe_minimum_treatment": 0.05,
        "evidence_probe_harm_limit": 0.05,
        "evidence_probe_max_promotions": 1,
        "uncertainty_rank_cap": None,
        "candidate_independent_source_ranking": True,
        "counterfactual_scope": "observational_uncertainty_set_only",
    }


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _ast_size(node: object) -> int:
    if isinstance(node, (Ref,)):
        return 1
    if isinstance(node, Range):
        return 3
    if isinstance(node, Unary):
        return 1 + _ast_size(node.value)
    if isinstance(node, Binary):
        return 1 + _ast_size(node.left) + _ast_size(node.right)
    if isinstance(node, Func):
        return 1 + sum(_ast_size(item) for item in node.args)
    return 1


def _formula_complexity(formula: str) -> tuple[str, int, int]:
    try:
        node = parse_formula(formula)
        if isinstance(node, Func):
            outer = f"func:{node.name}"
        elif isinstance(node, Binary):
            outer = f"binary:{node.op}"
        else:
            outer = type(node).__name__.lower()
        references = sum(1 for _ in iter_refs(node))
        size = _ast_size(node)
        return outer, min(8, references), min(12, size // 2)
    except Exception:  # noqa: BLE001 intentional compatibility or fallback boundary; preserve runtime behavior
        return "unsupported", 0, 0


def _orientation_residual(
    model: WorkbookModel,
    cell: CellKey,
    peers: Sequence[CellKey],
) -> tuple[float, int]:
    if len(peers) < 2:
        return 0.0, 0
    translated: list[str] = []
    for peer in peers:
        try:
            translated.append(normalized_formula(
                translate_formula(model.formulas[peer], peer[1], cell[1])
            ))
        except Exception:  # noqa: BLE001, S112 intentional compatibility or fallback boundary; preserve runtime behavior
            continue
    if len(translated) < 2:
        return 0.0, len(translated)
    counts: dict[str, int] = {}
    for formula in translated:
        counts[formula] = counts.get(formula, 0) + 1
    mode, support = max(counts.items(), key=lambda item: (item[1], item[0]))
    own = normalized_formula(model.formulas[cell])
    if support < 2 or own == mode:
        return 0.0, len(translated)
    return support / len(translated), len(translated)


def _local_block_boundary_exception(model: WorkbookModel, cell: CellKey) -> float:
    """Return label-free protection for aggregate formulas at a local block edge."""
    try:
        node = parse_formula(model.formulas[cell])
    except Exception:  # noqa: BLE001 intentional compatibility or fallback boundary; preserve runtime behavior
        return 0.0
    if not isinstance(node, Func) or node.name not in {"SUM", "AVERAGE", "MIN", "MAX"}:
        return 0.0
    address = parse_address(cell[1])
    formula_set = set(model.formula_cells)

    def exists(row: int, col: int) -> bool:
        return row >= 1 and col >= 1 and (cell[0], f"{num_to_col(col)}{row}") in formula_set

    vertical_up = sum(exists(address.row - step, address.col) for step in (1, 2, 3))
    vertical_down = sum(exists(address.row + step, address.col) for step in (1, 2, 3))
    horizontal_left = sum(exists(address.row, address.col - step) for step in (1, 2, 3))
    horizontal_right = sum(exists(address.row, address.col + step) for step in (1, 2, 3))
    vertical_edge = (vertical_up >= 2 and vertical_down == 0) or (vertical_down >= 2 and vertical_up == 0)
    horizontal_edge = (horizontal_left >= 2 and horizontal_right == 0) or (horizontal_right >= 2 and horizontal_left == 0)
    return 0.65 if vertical_edge or horizontal_edge else 0.0


def _distant_role_replication(model: WorkbookModel, cell: CellKey) -> float:
    """Protect a rare formula when the same relative role recurs far away.

    A lone MAX inside a SUM column is ambiguous.  The same relative MAX role
    repeated in another distant block is independent observational evidence
    for an intentional exception, without using a label or repair candidate.
    """
    try:
        own_node = parse_formula(model.formulas[cell])
        if not isinstance(own_node, Func) or own_node.name not in {"SUM", "AVERAGE", "MIN", "MAX"}:
            return 0.0
        own_signature = relative_ast_signature(model.formulas[cell], cell[1])
        own_address = parse_address(cell[1])
    except Exception:  # noqa: BLE001 intentional compatibility or fallback boundary; preserve runtime behavior
        return 0.0
    for other in model.formula_cells:
        if other == cell or other[0] != cell[0]:
            continue
        try:
            address = parse_address(other[1])
            if relative_ast_signature(model.formulas[other], other[1]) != own_signature:
                continue
        except Exception:  # noqa: BLE001, S112 intentional compatibility or fallback boundary; preserve runtime behavior
            continue
        same_column = address.col == own_address.col and abs(address.row - own_address.row) >= 3
        same_row = address.row == own_address.row and abs(address.col - own_address.col) >= 3
        if same_column or same_row:
            return 0.75
    return 0.0


def regime_conditioned_residuals(model: WorkbookModel) -> dict[CellKey, float]:
    """Leave-one-out residuals for linear, 2-D, and periodic formula regimes.

    A linear family follows its strongest coherent axis, while a stable
    alternating family uses same-period neighbours instead of an immediate
    majority. Boundary and repeated-role protections use no labels.
    """
    return _regime_conditioned_residuals(model)


def _regime_conditioned_residuals(
    model: WorkbookModel,
    *,
    use_boundary_protection: bool = True,
    use_role_replication: bool = True,
) -> dict[CellKey, float]:
    """Internal configurable RCR used by the preregistered ablations."""
    residuals: dict[CellKey, float] = {}
    for cell in model.formula_cells:
        peers = _directional_peers(model, cell)
        horizontal_line = list(reversed(peers["left"])) + [cell] + peers["right"]
        vertical_line = list(reversed(peers["up"])) + [cell] + peers["down"]
        line = horizontal_line if len(horizontal_line) >= len(vertical_line) else vertical_line
        signatures: list[str] = []
        for item in line:
            try:
                signatures.append(relative_ast_signature(model.formulas[item], item[1]))
            except Exception:  # noqa: BLE001 intentional compatibility or fallback boundary; preserve runtime behavior
                signatures.append("unsupported")
        period, _ = _periodic_pattern(signatures)
        if period and len(line) >= period * 2:
            index = line.index(cell)
            slot_values = signatures[index % period::period]
            counts: dict[str, int] = {}
            for signature in slot_values:
                counts[signature] = counts.get(signature, 0) + 1
            mode, support = max(counts.items(), key=lambda item: (item[1], item[0]))
            residuals[cell] = 0.0 if signatures[index] == mode else support / max(1, len(slot_values))
            continue
        horizontal, _h_total = _orientation_residual(
            model, cell, [*peers["left"], *peers["right"]],
        )
        vertical, _v_total = _orientation_residual(
            model, cell, [*peers["up"], *peers["down"]],
        )
        # The strongest coherent axis defines the local formula regime.  Requiring
        # both axes misses a vertical copy family merely because downstream
        # formulas are placed beside it.  Legitimate one-axis exceptions are
        # handled by the workbook-level clean null rather than erased here.
        residual = max(horizontal, vertical)
        boundary_protection = _local_block_boundary_exception(model, cell) if use_boundary_protection else 0.0
        role_replication = _distant_role_replication(model, cell) if use_role_replication else 0.0
        residuals[cell] = _clamp(
            residual * (1.0 - max(boundary_protection, role_replication))
        )
    return residuals


def _descendant_depths(graph: DependencyGraph, start: CellKey) -> dict[CellKey, int]:
    depths: dict[CellKey, int] = {}
    frontier = [(start, 0)]
    while frontier:
        node, depth = frontier.pop(0)
        for child in graph.dependents.get(node, ()):
            if child not in depths or depth + 1 < depths[child]:
                depths[child] = depth + 1
                frontier.append((child, depth + 1))
    depths.pop(start, None)
    return depths


def _branch_spread(
    graph: DependencyGraph,
    source: CellKey,
    descendant_signal: Mapping[CellKey, float],
) -> float:
    children = [item for item in graph.dependents.get(source, ()) if item in descendant_signal]
    if not children:
        return 0.0
    active = 0
    for child in children:
        branch = {child} | graph.descendants(child)
        if max((descendant_signal.get(item, 0.0) for item in branch), default=0.0) >= 0.25:
            active += 1
    return active / len(children)


def _propagation_potential(
    graph: DependencyGraph,
    source: CellKey,
    descendant_signal: Mapping[CellKey, float],
    formula_cells: set[CellKey],
) -> tuple[float, float, float, int]:
    depths = {
        cell: depth for cell, depth in _descendant_depths(graph, source).items()
        if cell in formula_cells
    }
    if not depths:
        return 0.0, 0.0, 0.0, 0
    weights = {cell: 0.70 ** max(0, depth - 1) for cell, depth in depths.items()}
    weighted_signal = sum(weights[cell] * descendant_signal.get(cell, 0.0) for cell in depths)
    total_weight = sum(weights.values()) or 1.0
    coverage = sum(1 for cell in depths if descendant_signal.get(cell, 0.0) >= 0.25) / len(depths)
    spread = _branch_spread(graph, source, descendant_signal)
    potential = _clamp(0.60 * weighted_signal / total_weight + 0.25 * coverage + 0.15 * spread)
    return potential, coverage, spread, len(depths)


def _ancestor_penalty(
    graph: DependencyGraph,
    cell: CellKey,
    node_signal: Mapping[CellKey, float],
    *,
    relative: bool = False,
    dominance_margin: float = 0.10,
) -> float:
    ancestors = graph.ancestors(cell)
    if not ancestors:
        return 0.0
    strongest = max((node_signal.get(item, 0.0) for item in ancestors), default=0.0)
    if not relative:
        return _clamp(strongest)
    if not 0.0 <= dominance_margin < 1.0:
        raise ValueError("ancestor dominance margin must be in [0, 1)")
    current = node_signal.get(cell, 0.0)
    return _clamp((strongest - current - dominance_margin) / (1.0 - dominance_margin))


def _control_distance(
    left: ObservationalEvidence,
    right: ObservationalEvidence,
    left_regime: RegimeEvidence,
    right_regime: RegimeEvidence,
) -> float:
    return (
        (0.0 if left_regime.regime_type == right_regime.regime_type else 2.0)
        + (0.0 if left.complexity[0] == right.complexity[0] else 1.5)
        + 0.35 * abs(left.complexity[1] - right.complexity[1])
        + 0.20 * abs(left.complexity[2] - right.complexity[2])
        + 0.35 * abs(left.indegree - right.indegree)
        + 0.35 * abs(left.outdegree - right.outdegree)
        + abs(math.log1p(left.descendant_count) - math.log1p(right.descendant_count))
    )


def _matched_cells(
    cell: CellKey,
    evidence: Mapping[CellKey, ObservationalEvidence],
    regimes: Mapping[CellKey, RegimeEvidence],
    limit: int,
) -> list[CellKey]:
    anchor = evidence[cell]
    candidates = [item for item in evidence if item != cell]
    candidates.sort(key=lambda item: (
        _control_distance(anchor, evidence[item], regimes[cell], regimes[item]),
        item,
    ))
    return candidates[: min(limit, len(candidates))]


def observational_source_evidence(
    model: WorkbookModel,
    *,
    matched_controls: int = DEFAULT_MATCHED_CONTROLS,
    use_rcr: bool = True,
    use_boundary_protection: bool = True,
    use_role_replication: bool = True,
    ancestor_weight: float = 0.75,
    observational_primary_weight: float = 0.55,
    observational_secondary_weight: float = 0.20,
    observational_propagation_weight: float = 0.25,
    relative_ancestor_penalty: bool = False,
    ancestor_dominance_margin: float = 0.10,
    adaptive_exception_release: bool = False,
    exception_release_tail: float = 0.25,
) -> tuple[dict[CellKey, ObservationalEvidence], dict[CellKey, RegimeEvidence]]:
    """Build candidate-independent source evidence and matched empirical tails."""
    if not 0.0 <= ancestor_weight <= 1.0:
        raise ValueError("ancestor_weight must be between 0 and 1")
    observational_weights = (
        float(observational_primary_weight),
        float(observational_secondary_weight),
        float(observational_propagation_weight),
    )
    if any(value < 0.0 for value in observational_weights) or not math.isclose(
        sum(observational_weights), 1.0, abs_tol=1e-9,
    ):
        raise ValueError("observational evidence weights must be non-negative and sum to 1")
    if not 0.0 <= exception_release_tail <= 1.0:
        raise ValueError("exception_release_tail must be between 0 and 1")
    cache = getattr(model, "_fg_v5_core_r2_observation_cache", None)
    cache_key = (
        matched_controls,
        use_rcr,
        use_boundary_protection,
        use_role_replication,
        round(float(ancestor_weight), 8),
        tuple(round(value, 8) for value in observational_weights),
        relative_ancestor_penalty,
        round(float(ancestor_dominance_margin), 8),
        adaptive_exception_release,
        round(float(exception_release_tail), 8),
    )
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    regimes = discover_formula_regimes(model)
    formula = formula_anomaly_scores(model)
    protected_residual = (
        _regime_conditioned_residuals(
            model,
            use_boundary_protection=use_boundary_protection,
            use_role_replication=use_role_replication,
        )
        if use_rcr else dict(formula)
    )
    unprotected_residual = (
        _regime_conditioned_residuals(
            model,
            use_boundary_protection=False,
            use_role_replication=False,
        )
        if use_rcr and adaptive_exception_release else protected_residual
    )
    behavior = behavior_anomaly_scores(model)
    graph_residual = graph_anomaly_scores(model)
    graph = model.dependency_graph()
    formula_cells = set(model.formula_cells)
    def build_provisional(residuals: Mapping[CellKey, float], *, releases: Mapping[CellKey, bool] | None = None,
                          propagation_tails: Mapping[CellKey, float] | None = None) -> dict[CellKey, ObservationalEvidence]:
        structural_signal = {
            cell: _clamp(0.80 * residuals.get(cell, 0.0) + 0.20 * formula.get(cell, 0.0))
            for cell in model.formula_cells
        }
        node_signal = {
            cell: max(structural_signal[cell], behavior.get(cell, 0.0), graph_residual.get(cell, 0.0))
            for cell in model.formula_cells
        }
        rows: dict[CellKey, ObservationalEvidence] = {}
        for cell in model.formula_cells:
            signals = sorted((
                float(structural_signal[cell]),
                float(behavior.get(cell, 0.0)),
                float(graph_residual.get(cell, 0.0)),
            ), reverse=True)
            potential, coverage, spread, descendants = _propagation_potential(
                graph, cell, behavior, formula_cells,
            )
            ancestor = _ancestor_penalty(
                graph,
                cell,
                node_signal,
                relative=relative_ancestor_penalty,
                dominance_margin=ancestor_dominance_margin,
            )
            raw = _clamp(
                (
                    observational_weights[0] * signals[0]
                    + observational_weights[1] * signals[1]
                    + observational_weights[2] * potential
                )
                * (1.0 - ancestor_weight * ancestor)
            )
            rows[cell] = ObservationalEvidence(
                cell=cell, raw_score=raw, empirical_tail=1.0,
                formula_residual=float(formula.get(cell, 0.0)),
                regime_conditioned_residual=float(residuals.get(cell, 0.0)),
                behavior_residual=float(behavior.get(cell, 0.0)),
                graph_residual=float(graph_residual.get(cell, 0.0)),
                propagation_potential=potential, descendant_anomaly_coverage=coverage,
                branch_spread=spread, ancestor_penalty=ancestor,
                indegree=len(graph.precedents.get(cell, ())),
                outdegree=len(graph.dependents.get(cell, ())),
                descendant_count=descendants, complexity=_formula_complexity(model.formulas[cell]),
                propagation_empirical_tail=(propagation_tails or {}).get(cell, 1.0),
                exception_release=(releases or {}).get(cell, False),
                alarm_regime_conditioned_residual=float(protected_residual.get(cell, 0.0)),
            )
        return rows

    provisional = build_provisional(protected_residual)
    if adaptive_exception_release:
        propagation_tails: dict[CellKey, float] = {}
        releases: dict[CellKey, bool] = {}
        for cell, row in provisional.items():
            controls = _matched_cells(cell, provisional, regimes, matched_controls)
            tail = (1 + sum(
                provisional[item].propagation_potential >= row.propagation_potential for item in controls
            )) / (1 + len(controls))
            propagation_tails[cell] = tail
            releases[cell] = (
                unprotected_residual.get(cell, 0.0) > protected_residual.get(cell, 0.0)
                and tail <= exception_release_tail
            )
        effective_residual = {
            cell: unprotected_residual[cell] if releases[cell] else protected_residual[cell]
            for cell in model.formula_cells
        }
        provisional = build_provisional(
            effective_residual, releases=releases, propagation_tails=propagation_tails,
        )
    completed: dict[CellKey, ObservationalEvidence] = {}
    for cell, row in provisional.items():
        controls = _matched_cells(cell, provisional, regimes, matched_controls)
        tail = (1 + sum(provisional[item].raw_score >= row.raw_score for item in controls)) / (1 + len(controls))
        completed[cell] = ObservationalEvidence(
            **{**row.__dict__, "empirical_tail": tail, "matched_controls": tuple(controls)}
        )
    result = (completed, regimes)
    if cache is None:
        cache = {}
        model._fg_v5_core_r2_observation_cache = cache
    cache[cache_key] = result
    return result


def observational_ranking(
    evidence: Mapping[CellKey, ObservationalEvidence],
    *,
    formula_rank_fusion_weight: float = 0.0,
    formula_rank_fusion_method: str = "linear_percentile",
    formula_rank_fusion_k: float = 10.0,
    protect_pre_fusion_top1: bool = False,
    formula_rank_fusion_scope: str = "global",
    formula_probe_limit: int = 2,
    formula_probe_start_rank: int = 2,
    formula_probe_minimum_residual: float = 0.50,
    formula_probe_minimum_corroboration: float = 0.10,
    formula_probe_allow_unique_top1: bool = False,
    formula_probe_top1_margin: float = 0.04,
) -> list[CellKey]:
    if not 0.0 <= formula_rank_fusion_weight <= 1.0:
        raise ValueError("formula rank fusion weight must be between 0 and 1")
    if formula_rank_fusion_method not in {"linear_percentile", "reciprocal_rank"}:
        raise ValueError("unknown formula rank fusion method")
    if formula_rank_fusion_k <= 0.0:
        raise ValueError("formula rank fusion k must be positive")
    if formula_rank_fusion_scope not in {"global", "bounded_probe"}:
        raise ValueError("unknown formula rank fusion scope")
    stable = {cell: index for index, cell in enumerate(sorted(evidence))}
    baseline = sorted(evidence, key=lambda cell: (
        evidence[cell].empirical_tail,
        -evidence[cell].raw_score,
        stable[cell],
    ))
    if formula_rank_fusion_weight == 0.0 or len(baseline) <= 1:
        return baseline
    count = len(baseline)
    observational_rank: dict[CellKey, int] = {}
    formula_rank: dict[CellKey, int] = {}
    for cell in baseline:
        row = evidence[cell]
        obs_better = sum(
            other.empirical_tail < row.empirical_tail
            or (
                math.isclose(other.empirical_tail, row.empirical_tail, abs_tol=1e-12)
                and other.raw_score > row.raw_score
            )
            for other in evidence.values()
        )
        formula_better = sum(
            other.formula_residual > row.formula_residual for other in evidence.values()
        )
        observational_rank[cell] = 1 + obs_better
        formula_rank[cell] = 1 + formula_better
    weight = formula_rank_fusion_weight
    baseline_rank = {cell: index for index, cell in enumerate(baseline)}
    if formula_rank_fusion_method == "reciprocal_rank":
        fused = {
            cell: (
                (1.0 - weight) / (formula_rank_fusion_k + observational_rank[cell])
                + weight / (formula_rank_fusion_k + formula_rank[cell])
            )
            for cell in baseline
        }
    else:
        fused = {
            cell: (
                (1.0 - weight) * (1.0 - (observational_rank[cell] - 1) / (count - 1))
                + weight * (1.0 - (formula_rank[cell] - 1) / (count - 1))
            )
            for cell in baseline
        }
    result = sorted(baseline, key=lambda cell: (
        -fused[cell],
        baseline_rank[cell],
    ))
    if formula_rank_fusion_scope == "bounded_probe":
        if formula_probe_limit <= 0 or formula_probe_start_rank < 2:
            return baseline
        formula_values = sorted(
            ((row.formula_residual, cell) for cell, row in evidence.items() if row.formula_residual > 0.0),
            key=lambda item: -item[0],
        )
        selected: set[CellKey] = set()
        if len(formula_values) <= formula_probe_limit:
            selected.update(cell for _, cell in formula_values)
        elif formula_values:
            cutoff = formula_values[formula_probe_limit - 1][0]
            above = [cell for value, cell in formula_values if value > cutoff]
            tied = [cell for value, cell in formula_values if math.isclose(value, cutoff, abs_tol=1e-12)]
            selected.update(above)
            if len(above) + len(tied) <= formula_probe_limit:
                selected.update(tied)
        selected = {
            cell for cell in selected
            if evidence[cell].formula_residual >= formula_probe_minimum_residual
            and max(
                evidence[cell].regime_conditioned_residual,
                evidence[cell].behavior_residual,
                evidence[cell].graph_residual,
                evidence[cell].propagation_potential,
            ) >= formula_probe_minimum_corroboration
        }
        top_formula_margin = (
            formula_values[0][0] - formula_values[1][0]
            if len(formula_values) > 1 else (formula_values[0][0] if formula_values else 0.0)
        )
        effective_start_rank = (
            1 if formula_probe_allow_unique_top1 and top_formula_margin >= formula_probe_top1_margin
            else formula_probe_start_rank
        )
        fused_rank = {cell: index for index, cell in enumerate(result)}
        ordered_probe = sorted(
            (
                cell for cell in selected
                if effective_start_rank == 1 or cell != baseline[0]
            ),
            key=lambda cell: (-evidence[cell].formula_residual, fused_rank[cell]),
        )
        bounded = list(baseline)
        for offset, cell in enumerate(ordered_probe[:formula_probe_limit]):
            target = min(effective_start_rank - 1 + offset, len(bounded) - 1)
            current = bounded.index(cell)
            if current <= target:
                continue
            bounded.remove(cell)
            bounded.insert(target, cell)
        return bounded
    if protect_pre_fusion_top1 and result[0] != baseline[0]:
        result.remove(baseline[0])
        result.insert(0, baseline[0])
    return result


def observational_uncertainty_set(
    ranking: Sequence[CellKey],
    evidence: Mapping[CellKey, ObservationalEvidence],
    *,
    limit: int = DEFAULT_UNCERTAINTY_LIMIT,
    rank_cap: int | None = None,
    empirical_tie_rank_cap: int = 0,
) -> list[CellKey]:
    if not ranking or limit <= 0:
        return []
    raw_values = [evidence[cell].raw_score for cell in ranking]
    median = statistics.median(raw_values)
    mad = statistics.median(abs(value - median) for value in raw_values)
    band = max(0.05, 1.4826 * mad)
    best = evidence[ranking[0]]
    tail_limit = max(0.25, best.empirical_tail + 0.10)
    considered = list(ranking if rank_cap is None else ranking[:max(1, rank_cap)])
    selected = [
        cell for cell in considered
        if evidence[cell].empirical_tail <= tail_limit
        and evidence[cell].raw_score >= best.raw_score - band
    ]
    if empirical_tie_rank_cap > 0:
        tied = {
            cell for cell in ranking[:empirical_tie_rank_cap]
            if math.isclose(
                evidence[cell].empirical_tail,
                best.empirical_tail,
                abs_tol=1e-12,
            )
        }
        selected = [cell for cell in ranking if cell in set(selected) | tied]
    return selected[:limit] or [ranking[0]]


_PROBE_COMPONENTS = (
    "formula_residual",
    "regime_conditioned_residual",
    "behavior_residual",
    "graph_residual",
    "propagation_potential",
)


def observational_probe_set(
    ranking: Sequence[CellKey],
    evidence: Mapping[CellKey, ObservationalEvidence],
    *,
    per_signal: int = 0,
    small_workbook_limit: int = 0,
) -> list[CellKey]:
    """Select a bounded candidate-independent intervention probe set.

    The selector never sees repair candidates or labels.  At a cutoff tie it
    refuses to choose by cell address: only values strictly above the tied
    boundary are retained.  Small workbooks may be exhaustively probed because
    that is a compute-budget decision rather than an anomaly ranking decision.
    """
    if not ranking or per_signal <= 0:
        return []
    if small_workbook_limit > 0 and len(ranking) <= small_workbook_limit:
        return list(ranking)
    selected: set[CellKey] = set()
    for component in _PROBE_COMPONENTS:
        values = [
            (float(getattr(evidence[cell], component)), cell)
            for cell in ranking
            if float(getattr(evidence[cell], component)) > 0.0
        ]
        values.sort(key=lambda item: -item[0])
        if len(values) <= per_signal:
            selected.update(cell for _, cell in values)
            continue
        cutoff = values[per_signal - 1][0]
        above = [cell for value, cell in values if value > cutoff]
        tied = [cell for value, cell in values if math.isclose(value, cutoff, abs_tol=1e-12)]
        selected.update(above)
        if len(above) + len(tied) <= per_signal:
            selected.update(tied)
    return [cell for cell in ranking if cell in selected]


def _treatment(evidence: CandidateEvidence | None, *, mode: str = "directional") -> float:
    if evidence is None:
        return 0.0
    harm = max(evidence.local_harm, evidence.global_harm)
    if mode == "additive":
        return (
            max(0.0, evidence.counterfactual_delta) * (1.0 - _clamp(harm))
            + 0.25 * evidence.graph_recovery_evidence
        )
    if mode != "directional":
        raise ValueError(f"Unknown treatment mode: {mode}")
    # Require both local causal improvement and directed downstream recovery.
    # Their geometric mean prevents either a local clean-up or a large fan-out
    # from being sufficient on its own.
    local_causal = _clamp(max(0.0, evidence.counterfactual_delta) / 0.10)
    downstream = _clamp(evidence.graph_recovery_evidence / 0.10)
    return math.sqrt(local_causal * downstream) * (1.0 - _clamp(harm))


def _candidate_source_family(source: str) -> str:
    """Collapse correlated candidate generators into independent evidence families."""
    if source.startswith("peer_") or source in {"family_consensus", "matrix_translation"}:
        return "peer_family"
    if "boundary" in source:
        return "range_boundary"
    if "cross_sheet" in source:
        return "cross_sheet"
    if source == "bounded_edit":
        return "bounded_edit"
    return source.split("_", 1)[0]


def _independent_candidate_support(row: PlaceboEvidence | None) -> int:
    if row is None or row.best is None:
        return 0
    candidate = getattr(row.best, "candidate", None)
    sources = getattr(candidate, "sources", ()) if candidate is not None else ()
    return len({_candidate_source_family(str(source)) for source in sources})


def _evaluate_cell(
    model: WorkbookModel,
    cell: CellKey,
    regime: RegimeEvidence,
    *,
    formula_score: float,
    graph_score: float,
    behavior_score: float,
    base_global_energy: float,
    base_maps: Mapping[str, Mapping[CellKey, float]],
    graph: DependencyGraph,
    candidate_limit: int,
    intervention_limit: int,
    preferred_category: str | None = None,
) -> tuple[list[PortfolioCandidate], list[CandidateEvidence]]:
    portfolio = build_candidate_portfolio(
        model, cell, candidate_limit=candidate_limit, regime=regime,
    )
    selected = list(portfolio)
    if preferred_category:
        matching = [item for item in selected if _category(item.candidate) == preferred_category]
        other = [item for item in selected if _category(item.candidate) != preferred_category]
        selected = matching + other
    selected = selected[: min(intervention_limit, len(selected))]
    rows = _evaluate_candidates(
        model,
        cell,
        selected,
        regime,
        formula_anomaly=formula_score,
        graph_anomaly=graph_score,
        behavior_anomaly=behavior_score,
        base_global_energy=base_global_energy,
        base_maps=base_maps,
        graph=graph,
        limit=len(selected),
    ) if selected else []
    return portfolio, rows


def matched_placebo_evidence(
    model: WorkbookModel,
    uncertainty: Sequence[CellKey],
    observations: Mapping[CellKey, ObservationalEvidence],
    regimes: Mapping[CellKey, RegimeEvidence],
    *,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    intervention_limit: int = DEFAULT_INTERVENTION_LIMIT,
    matched_controls: int = DEFAULT_MATCHED_CONTROLS,
    treatment_mode: str = "directional",
    candidate_keep_fraction: float = 1.0,
    with_placebo: bool = True,
) -> dict[CellKey, PlaceboEvidence]:
    """Compare formula intervention recovery with matched-formula placebos."""
    if treatment_mode not in {"directional", "additive"}:
        raise ValueError("treatment_mode must be 'directional' or 'additive'")
    if not 0.0 <= candidate_keep_fraction <= 1.0:
        raise ValueError("candidate_keep_fraction must be between 0 and 1")
    context = getattr(model, "_fg_v5_core_r2_intervention_context", None)
    if context is None:
        context = {
            "formula": formula_anomaly_scores(model),
            "behavior": behavior_anomaly_scores(model),
            "graph_scores": graph_anomaly_scores(model),
            "graph": model.dependency_graph(),
        }
        base_global_energy, _, base_maps = _energy(model, include_maps=True)
        context["base_global_energy"] = base_global_energy
        context["base_maps"] = base_maps
        context["evaluation_cache"] = {}
        model._fg_v5_core_r2_intervention_context = context
    formula = context["formula"]
    behavior = context["behavior"]
    graph_scores = context["graph_scores"]
    graph = context["graph"]
    base_global_energy = context["base_global_energy"]
    base_maps = context["base_maps"]
    cache = context["evaluation_cache"]
    effective_limit = (
        0 if candidate_keep_fraction == 0.0
        else max(1, math.ceil(intervention_limit * candidate_keep_fraction))
    )

    def evaluate(cell: CellKey, preferred: str | None = None):
        key = (cell, preferred, candidate_limit, effective_limit)
        if key not in cache:
            cache[key] = _evaluate_cell(
                model,
                cell,
                regimes[cell],
                formula_score=formula.get(cell, 0.0),
                graph_score=graph_scores.get(cell, 0.0),
                behavior_score=behavior.get(cell, 0.0),
                base_global_energy=base_global_energy,
                base_maps=base_maps,
                graph=graph,
                candidate_limit=candidate_limit,
                intervention_limit=effective_limit,
                preferred_category=preferred,
            )
        return cache[key]

    results: dict[CellKey, PlaceboEvidence] = {}
    for cell in uncertainty:
        portfolio, rows = evaluate(cell)
        best = max(rows, key=lambda row: _treatment(row, mode=treatment_mode), default=None)
        treatment = _treatment(best, mode=treatment_mode)
        category = _category(best.candidate) if best else ""
        controls = _matched_cells(cell, observations, regimes, matched_controls) if with_placebo else []
        control_treatments: list[float] = []
        used_controls: list[CellKey] = []
        for control in controls:
            _, control_rows = evaluate(control, category or None)
            control_best = max(
                control_rows,
                key=lambda row: _treatment(row, mode=treatment_mode),
                default=None,
            )
            control_treatments.append(_treatment(control_best, mode=treatment_mode))
            used_controls.append(control)
        tail = (1 + sum(item >= treatment for item in control_treatments)) / (1 + len(control_treatments))
        results[cell] = PlaceboEvidence(
            cell=cell,
            treatment=treatment,
            empirical_tail=tail,
            best=best,
            control_treatments=tuple(control_treatments),
            matched_controls=tuple(used_controls),
            candidate_coverage=bool(rows),
            edit_category=category,
            raw={
                "portfolio_size": len(portfolio),
                "evaluated_candidates": len(rows),
                "candidate_keep_fraction": candidate_keep_fraction,
                "treatment_mode": treatment_mode,
                "with_placebo": with_placebo,
            },
        )
    return results


def _rerank_uncertainty(
    observational: Sequence[CellKey],
    uncertainty: Sequence[CellKey],
    placebo: Mapping[CellKey, PlaceboEvidence],
    observations: Mapping[CellKey, ObservationalEvidence],
    *,
    safe_counterfactual_reorder: bool = False,
    minimum_treatment: float = DEFAULT_MIN_TREATMENT,
    counterfactual_tail: float = DEFAULT_CF_TAIL,
    protect_observational_top1: bool = False,
    independent_support_tiebreak: bool = False,
    release_tied_top1_with_dcf: bool = False,
    minimum_independent_support: int = 2,
    structural_priority_in_uncertainty: bool = False,
) -> list[CellKey]:
    uncertain = set(uncertainty)
    slots = [index for index, cell in enumerate(observational) if cell in uncertain]
    def independent_support(cell: CellKey) -> int:
        return _independent_candidate_support(placebo.get(cell)) if independent_support_tiebreak else 0

    def eligible(cell: CellKey) -> bool:
        row = placebo.get(cell, PlaceboEvidence(cell))
        return bool(
            row.candidate_coverage
            and row.treatment >= minimum_treatment
            and row.empirical_tail <= counterfactual_tail
        )

    def ordinary_key(cell: CellKey) -> tuple[float, int, float, float, float, int]:
        row = placebo.get(cell, PlaceboEvidence(cell))
        return (
            row.empirical_tail,
            -independent_support(cell),
            -row.treatment,
            observations[cell].empirical_tail,
            -observations[cell].raw_score,
            observational.index(cell),
        )
    ordered = sorted(uncertainty, key=ordinary_key)
    if safe_counterfactual_reorder:
        eligible_cells = [cell for cell in ordered if eligible(cell)]
        if not eligible_cells:
            return list(observational)
        if structural_priority_in_uncertainty:
            # Candidate interventions may resolve an observational tie, but they
            # must not overrule stronger candidate-independent regime evidence.
            # DCF therefore orders cells only after the structural residual.
            ordered = sorted(uncertainty, key=lambda cell: (
                -observations[cell].regime_conditioned_residual,
                0 if eligible(cell) else 1,
                *ordinary_key(cell),
            ))
        else:
            eligible_set = set(eligible_cells)
            ineligible = [cell for cell in uncertainty if cell not in eligible_set]
            ineligible.sort(key=observational.index)
            ordered = eligible_cells + ineligible
    result = list(observational)
    for slot, cell in zip(slots, ordered):
        result[slot] = cell
    if protect_observational_top1 and result and result[0] != observational[0]:
        challenger, leader = result[0], observational[0]
        challenger_row = placebo.get(challenger, PlaceboEvidence(challenger))
        leader_row = placebo.get(leader, PlaceboEvidence(leader))
        challenger_harm = (
            max(challenger_row.best.local_harm, challenger_row.best.global_harm)
            if challenger_row.best else 1.0
        )
        challenger_eligible = (
            challenger_row.candidate_coverage
            and challenger_row.treatment >= minimum_treatment
            and challenger_row.empirical_tail <= counterfactual_tail
            and challenger_harm <= 0.05
        )
        leader_eligible = (
            leader_row.candidate_coverage
            and leader_row.treatment >= minimum_treatment
            and leader_row.empirical_tail <= counterfactual_tail
        )
        release = (
            release_tied_top1_with_dcf
            and challenger_eligible
            and independent_support(challenger) >= minimum_independent_support
            and math.isclose(
                observations[challenger].empirical_tail,
                observations[leader].empirical_tail,
                abs_tol=1e-12,
            )
            and (
                not leader_eligible
                or independent_support(challenger) > independent_support(leader)
            )
        )
        if not release:
            result.remove(leader)
            result.insert(0, leader)
    return result


def _promote_probe_candidate(
    ranking: Sequence[CellKey],
    probe_cells: Sequence[CellKey],
    placebo: Mapping[CellKey, PlaceboEvidence],
    observations: Mapping[CellKey, ObservationalEvidence],
    *,
    promotion_rank: int = 5,
    counterfactual_tail: float = 0.125,
    minimum_treatment: float = 0.05,
    harm_limit: float = 0.05,
    max_promotions: int = 1,
) -> tuple[list[CellKey], tuple[CellKey, ...]]:
    """Promote at most a few independently probed cells under strict DCF gates."""
    if promotion_rank < 2:
        raise ValueError("probe promotion rank must be at least 2")
    if max_promotions <= 0 or not ranking:
        return list(ranking), ()

    def harm(cell: CellKey) -> float:
        row = placebo.get(cell)
        return max(row.best.local_harm, row.best.global_harm) if row and row.best else 1.0

    eligible = [
        cell for cell in probe_cells
        if cell in placebo
        and placebo[cell].candidate_coverage
        and placebo[cell].treatment >= minimum_treatment
        and placebo[cell].empirical_tail <= counterfactual_tail
        and harm(cell) <= harm_limit
        and ranking.index(cell) + 1 > promotion_rank
    ]
    eligible.sort(key=lambda cell: (
        placebo[cell].empirical_tail,
        -placebo[cell].treatment,
        harm(cell),
        observations[cell].empirical_tail,
        -observations[cell].raw_score,
        ranking.index(cell),
    ))
    if len(eligible) > 1:
        first, second = eligible[:2]
        first_signature = (
            placebo[first].empirical_tail,
            placebo[first].treatment,
            harm(first),
            observations[first].empirical_tail,
            observations[first].raw_score,
        )
        second_signature = (
            placebo[second].empirical_tail,
            placebo[second].treatment,
            harm(second),
            observations[second].empirical_tail,
            observations[second].raw_score,
        )
        if all(math.isclose(a, b, abs_tol=1e-12) for a, b in zip(first_signature, second_signature)):
            return list(ranking), ()

    result = list(ranking)
    promoted: list[CellKey] = []
    for cell in eligible[:max_promotions]:
        if cell not in result or result.index(cell) + 1 <= promotion_rank:
            continue
        result.remove(cell)
        result.insert(min(promotion_rank - 1, len(result)), cell)
        promoted.append(cell)
    return result, tuple(promoted)


def _diagnostic_status(
    ranking: Sequence[CellKey],
    observations: Mapping[CellKey, ObservationalEvidence],
    placebo: Mapping[CellKey, PlaceboEvidence],
    *,
    observational_tail: float,
    counterfactual_tail: float,
    review_tail: float,
    minimum_treatment: float,
    cross_workbook_tail: float | None,
    clean_null_tail: float,
) -> str:
    if not ranking:
        return "unsupported_coverage"
    top = ranking[0]
    obs = observations[top]
    cf = placebo.get(top)
    if cross_workbook_tail is not None and cross_workbook_tail > clean_null_tail:
        return "abstain_ambiguous"
    if cf is not None and not cf.candidate_coverage:
        return "unsupported_coverage"
    if obs.empirical_tail > review_tail:
        return "abstain_ambiguous"
    if cf is None:
        return "review"
    tied = sum(
        math.isclose(row.empirical_tail, cf.empirical_tail, abs_tol=1e-12)
        and math.isclose(row.treatment, cf.treatment, abs_tol=1e-12)
        for row in placebo.values()
    ) > 1
    harm = max(cf.best.local_harm, cf.best.global_harm) if cf.best else 1.0
    if (
        obs.empirical_tail <= observational_tail
        and cf.empirical_tail <= counterfactual_tail
        and cf.treatment >= minimum_treatment
        and harm <= 0.10
        and not tied
    ):
        return "localized"
    if tied and obs.empirical_tail > observational_tail:
        return "abstain_ambiguous"
    return "review"


def _workbook_null_statistic(
    cell: CellKey,
    observations: Mapping[CellKey, ObservationalEvidence],
    placebo: Mapping[CellKey, PlaceboEvidence],
    *,
    variant: str,
    use_alarm_residual: bool = False,
) -> float:
    row = observations[cell]
    residual = (
        row.alarm_regime_conditioned_residual
        if use_alarm_residual else row.regime_conditioned_residual
    )
    if variant == "rcr":
        return _clamp(residual)
    if variant == "rcr_observational":
        return _clamp(0.80 * residual + 0.20 * row.raw_score)
    if variant == "rcr_directional":
        directional = placebo.get(cell, PlaceboEvidence(cell)).treatment
        return _clamp(0.70 * residual + 0.30 * directional)
    raise ValueError(f"Unknown WCN variant: {variant}")


def _empirical_cross_workbook_tail(value: float, clean_null_scores: Sequence[float]) -> float:
    return (1 + sum(float(item) >= value for item in clean_null_scores)) / (1 + len(clean_null_scores))


def v5_core_r2_scores(
    model: WorkbookModel,
    *,
    stage: str = "full",
    config: Mapping[str, object] | None = None,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    intervention_limit: int = DEFAULT_INTERVENTION_LIMIT,
    matched_controls: int = DEFAULT_MATCHED_CONTROLS,
    uncertainty_limit: int = DEFAULT_UNCERTAINTY_LIMIT,
    ablation: str | None = None,
    candidate_keep_fraction: float = 1.0,
) -> list[LocalizationResult]:
    """Return the complete, label-free DNCA ranking.

    ``stage='source'`` produces the candidate-independent ranking;
    ``stage='placebo'`` records interventions without changing that ranking;
    ``stage='full'`` permits reordering only inside the uncertainty set.
    """
    if stage not in {"source", "placebo", "full"}:
        raise ValueError("stage must be 'source', 'placebo', or 'full'")
    allowed_ablations = {
        None,
        "no_rcr",
        "no_boundary",
        "no_role_replication",
        "no_ancestor",
        "additive_dcf",
        "no_placebo",
        "unrestricted_rerank",
        "no_boundary_no_role",
        "no_formula_probe",
    }
    if ablation not in allowed_ablations:
        raise ValueError(f"Unknown V5-Core R2 ablation: {ablation}")
    if not 0.0 <= candidate_keep_fraction <= 1.0:
        raise ValueError("candidate_keep_fraction must be between 0 and 1")
    parameters = {**v5_core_r2_default_parameters(), **dict(config or {})}
    if parameters.get("uncertainty_rank_cap") is not None and int(parameters["uncertainty_rank_cap"]) < 1:
        raise ValueError("uncertainty_rank_cap must be positive or null")
    if int(parameters.get("evidence_probe_per_signal", 0)) < 0:
        raise ValueError("evidence probe per signal must be non-negative")
    if int(parameters.get("evidence_probe_small_workbook_limit", 0)) < 0:
        raise ValueError("evidence probe small workbook limit must be non-negative")
    use_boundary_protection = bool(parameters.get("boundary_protection", True))
    use_role_replication = bool(parameters.get("role_replication", True))
    if ablation in {"no_boundary", "no_boundary_no_role"}:
        use_boundary_protection = False
    if ablation in {"no_role_replication", "no_boundary_no_role"}:
        use_role_replication = False
    started = time.perf_counter()
    observations, regimes = observational_source_evidence(
        model,
        matched_controls=matched_controls,
        use_rcr=ablation != "no_rcr",
        use_boundary_protection=use_boundary_protection,
        use_role_replication=use_role_replication,
        ancestor_weight=(
            0.0 if ablation == "no_ancestor"
            else float(parameters.get("ancestor_weight", 0.75))
        ),
        observational_primary_weight=float(parameters.get("observational_primary_weight", 0.55)),
        observational_secondary_weight=float(parameters.get("observational_secondary_weight", 0.20)),
        observational_propagation_weight=float(parameters.get("observational_propagation_weight", 0.25)),
        relative_ancestor_penalty=bool(parameters.get("relative_ancestor_penalty", False)),
        ancestor_dominance_margin=float(parameters.get("ancestor_dominance_margin", 0.10)),
        adaptive_exception_release=bool(parameters.get("adaptive_exception_release", False)),
        exception_release_tail=float(parameters.get("exception_release_tail", 0.25)),
    )
    source_ranking = observational_ranking(
        observations,
        formula_rank_fusion_weight=(
            0.0 if ablation == "no_formula_probe"
            else float(parameters.get("formula_rank_fusion_weight", 0.0))
        ),
        formula_rank_fusion_method=str(parameters.get("formula_rank_fusion_method", "linear_percentile")),
        formula_rank_fusion_k=float(parameters.get("formula_rank_fusion_k", 10.0)),
        protect_pre_fusion_top1=bool(parameters.get("protect_pre_fusion_top1", False)),
        formula_rank_fusion_scope=str(parameters.get("formula_rank_fusion_scope", "global")),
        formula_probe_limit=int(parameters.get("formula_probe_limit", 2)),
        formula_probe_start_rank=int(parameters.get("formula_probe_start_rank", 2)),
        formula_probe_minimum_residual=float(parameters.get("formula_probe_minimum_residual", 0.50)),
        formula_probe_minimum_corroboration=float(parameters.get("formula_probe_minimum_corroboration", 0.10)),
        formula_probe_allow_unique_top1=bool(parameters.get("formula_probe_allow_unique_top1", False)),
        formula_probe_top1_margin=float(parameters.get("formula_probe_top1_margin", 0.04)),
    )
    uncertainty = observational_uncertainty_set(
        source_ranking,
        observations,
        limit=uncertainty_limit,
        rank_cap=(
            int(parameters["uncertainty_rank_cap"])
            if parameters.get("uncertainty_rank_cap") is not None else None
        ),
        empirical_tie_rank_cap=int(parameters.get("empirical_tie_rank_cap", 0)),
    )
    probe = observational_probe_set(
        source_ranking,
        observations,
        per_signal=int(parameters.get("evidence_probe_per_signal", 0)),
        small_workbook_limit=int(parameters.get("evidence_probe_small_workbook_limit", 0)),
    )
    uncertainty_set = set(uncertainty)
    probe_only = [cell for cell in probe if cell not in uncertainty_set]
    intervention_cells = list(uncertainty) + probe_only
    rerank_cells = list(uncertainty)
    if ablation == "unrestricted_rerank":
        # Budget-matched unsafe comparison: counterfactual evidence may act
        # outside the statistical uncertainty band, but is still capped so
        # the ablation remains computationally comparable.
        expanded = min(len(source_ranking), max(24, uncertainty_limit * 2))
        intervention_cells = list(source_ranking[:expanded])
        rerank_cells = list(intervention_cells)
    placebo: dict[CellKey, PlaceboEvidence] = {}
    if stage in {"placebo", "full"} and intervention_cells:
        placebo = matched_placebo_evidence(
            model,
            intervention_cells,
            observations,
            regimes,
            candidate_limit=candidate_limit,
            intervention_limit=intervention_limit,
            matched_controls=matched_controls,
            treatment_mode="additive" if ablation == "additive_dcf" else "directional",
            candidate_keep_fraction=candidate_keep_fraction,
            with_placebo=ablation != "no_placebo",
        )
    ranking = (
        _rerank_uncertainty(
            source_ranking,
            rerank_cells,
            placebo,
            observations,
            safe_counterfactual_reorder=bool(parameters.get("safe_counterfactual_reorder", False)),
            minimum_treatment=float(parameters["minimum_treatment"]),
            counterfactual_tail=float(parameters["counterfactual_tail"]),
            protect_observational_top1=bool(parameters.get("protect_observational_top1", False)),
            independent_support_tiebreak=bool(parameters.get("independent_support_tiebreak", False)),
            release_tied_top1_with_dcf=bool(parameters.get("release_tied_top1_with_dcf", False)),
            minimum_independent_support=int(parameters.get("minimum_independent_support", 2)),
            structural_priority_in_uncertainty=bool(
                parameters.get("structural_priority_in_uncertainty", False)
            ),
        )
        if stage == "full" else list(source_ranking)
    )
    promoted_probe_cells: tuple[CellKey, ...] = ()
    if stage == "full" and probe_only and ablation != "unrestricted_rerank":
        ranking, promoted_probe_cells = _promote_probe_candidate(
            ranking,
            probe_only,
            placebo,
            observations,
            promotion_rank=int(parameters.get("evidence_probe_promotion_rank", 5)),
            counterfactual_tail=float(parameters.get("evidence_probe_counterfactual_tail", 0.125)),
            minimum_treatment=float(parameters.get("evidence_probe_minimum_treatment", 0.05)),
            harm_limit=float(parameters.get("evidence_probe_harm_limit", 0.05)),
            max_promotions=int(parameters.get("evidence_probe_max_promotions", 1)),
        )
    wcn_variant = str(parameters.get("wcn_variant", "rcr_observational"))
    wcn_protected_global_max = bool(parameters.get("wcn_protected_global_max", False))
    workbook_statistic = (
        max(
            _workbook_null_statistic(
                cell, observations, placebo, variant=wcn_variant,
                use_alarm_residual=wcn_protected_global_max,
            )
            for cell in ranking
        ) if wcn_protected_global_max and ranking else (
            _workbook_null_statistic(
                ranking[0], observations, placebo, variant=wcn_variant,
            ) if ranking else 0.0
        )
    )
    clean_null_scores = [float(item) for item in parameters.get("clean_null_scores", [])]
    cross_workbook_tail = (
        _empirical_cross_workbook_tail(workbook_statistic, clean_null_scores)
        if clean_null_scores else None
    )
    status = _diagnostic_status(
        ranking,
        observations,
        placebo,
        observational_tail=float(parameters["observational_tail"]),
        counterfactual_tail=float(parameters["counterfactual_tail"]),
        review_tail=float(parameters["review_tail"]),
        minimum_treatment=float(parameters["minimum_treatment"]),
        cross_workbook_tail=cross_workbook_tail,
        clean_null_tail=float(parameters["clean_null_tail"]),
    )
    source_rank = {cell: index for index, cell in enumerate(source_ranking, 1)}
    intervention_set = set(intervention_cells)
    probe_set = set(probe)
    promoted_probe_set = set(promoted_probe_cells)
    elapsed = time.perf_counter() - started
    total = max(1, len(ranking))
    results: list[LocalizationResult] = []
    for rank, cell in enumerate(ranking, 1):
        obs = observations[cell]
        cf = placebo.get(cell)
        best = cf.best if cf else None
        evidence = {
            "model_version": str(parameters["model_version"]),
            "architecture": "dual_null_causal_attribution",
            "stage": stage,
            "rank": rank,
            "observational_rank": source_rank[cell],
            "diagnostic_status": status,
            "workbook_null_statistic": workbook_statistic,
            "wcn_variant": wcn_variant,
            "wcn_protected_global_max": wcn_protected_global_max,
            "cross_workbook_clean_tail": cross_workbook_tail if cross_workbook_tail is not None else -1.0,
            "clean_null_calibrated": bool(clean_null_scores),
            "candidate_independent_source_ranking": True,
            "in_uncertainty_set": cell in uncertainty_set,
            "in_evidence_probe_set": cell in probe_set,
            "probe_promotion": cell in promoted_probe_set,
            "in_intervention_set": cell in intervention_set,
            "uncertainty_set_size": len(uncertainty),
            "evidence_probe_set_size": len(probe),
            "evidence_probe_only_size": len(probe_only),
            "evidence_probe_per_signal": int(parameters.get("evidence_probe_per_signal", 0)),
            "evidence_probe_small_workbook_limit": int(parameters.get("evidence_probe_small_workbook_limit", 0)),
            "evidence_probe_promotion_rank": int(parameters.get("evidence_probe_promotion_rank", 5)),
            "evidence_probe_counterfactual_tail": float(parameters.get("evidence_probe_counterfactual_tail", 0.125)),
            "evidence_probe_minimum_treatment": float(parameters.get("evidence_probe_minimum_treatment", 0.05)),
            "evidence_probe_harm_limit": float(parameters.get("evidence_probe_harm_limit", 0.05)),
            "uncertainty_rank_cap": parameters.get("uncertainty_rank_cap"),
            "empirical_tie_rank_cap": int(parameters.get("empirical_tie_rank_cap", 0)),
            "safe_counterfactual_reorder": bool(parameters.get("safe_counterfactual_reorder", False)),
            "protect_observational_top1": bool(parameters.get("protect_observational_top1", False)),
            "independent_support_tiebreak": bool(parameters.get("independent_support_tiebreak", False)),
            "release_tied_top1_with_dcf": bool(parameters.get("release_tied_top1_with_dcf", False)),
            "minimum_independent_support": int(parameters.get("minimum_independent_support", 2)),
            "structural_priority_in_uncertainty": bool(
                parameters.get("structural_priority_in_uncertainty", False)
            ),
            "relative_ancestor_penalty": bool(parameters.get("relative_ancestor_penalty", False)),
            "ancestor_dominance_margin": float(parameters.get("ancestor_dominance_margin", 0.10)),
            "observational_primary_weight": float(parameters.get("observational_primary_weight", 0.55)),
            "observational_secondary_weight": float(parameters.get("observational_secondary_weight", 0.20)),
            "observational_propagation_weight": float(parameters.get("observational_propagation_weight", 0.25)),
            "formula_rank_fusion_weight": float(parameters.get("formula_rank_fusion_weight", 0.0)),
            "formula_rank_fusion_method": str(parameters.get("formula_rank_fusion_method", "linear_percentile")),
            "formula_rank_fusion_k": float(parameters.get("formula_rank_fusion_k", 10.0)),
            "protect_pre_fusion_top1": bool(parameters.get("protect_pre_fusion_top1", False)),
            "formula_rank_fusion_scope": str(parameters.get("formula_rank_fusion_scope", "global")),
            "formula_probe_limit": int(parameters.get("formula_probe_limit", 2)),
            "formula_probe_start_rank": int(parameters.get("formula_probe_start_rank", 2)),
            "formula_probe_allow_unique_top1": bool(parameters.get("formula_probe_allow_unique_top1", False)),
            "formula_probe_top1_margin": float(parameters.get("formula_probe_top1_margin", 0.04)),
            "observational_raw_score": obs.raw_score,
            "observational_empirical_tail": obs.empirical_tail,
            "observational_controls": [f"{s}!{a}" for s, a in obs.matched_controls],
            "formula_residual": obs.formula_residual,
            "regime_conditioned_residual": obs.regime_conditioned_residual,
            "behavior_residual": obs.behavior_residual,
            "graph_residual": obs.graph_residual,
            "propagation_potential": obs.propagation_potential,
            "descendant_anomaly_coverage": obs.descendant_anomaly_coverage,
            "branch_spread": obs.branch_spread,
            "ancestor_penalty": obs.ancestor_penalty,
            "indegree": obs.indegree,
            "outdegree": obs.outdegree,
            "descendant_count": obs.descendant_count,
            "regime_id": regimes[cell].regime_id,
            "regime_type": regimes[cell].regime_type,
            "counterfactual_empirical_tail": cf.empirical_tail if cf else 1.0,
            "placebo_treatment": cf.treatment if cf else 0.0,
            "directional_causal_footprint": cf.treatment if cf else 0.0,
            "placebo_control_treatments": list(cf.control_treatments) if cf else [],
            "placebo_controls": [f"{s}!{a}" for s, a in cf.matched_controls] if cf else [],
            "candidate_coverage": bool(cf and cf.candidate_coverage),
            "candidate_keep_fraction": candidate_keep_fraction,
            "candidate_formula": best.candidate.formula if best else "",
            "candidate_sources": list(best.candidate.sources) if best else [],
            "candidate_edit_kinds": list(best.candidate.edit_kinds) if best else [],
            "counterfactual_delta": best.counterfactual_delta if best else 0.0,
            "irg": best.irg if best else 0.0,
            "local_harm": best.local_harm if best else 0.0,
            "global_harm": best.global_harm if best else 0.0,
            "graph_recovery_evidence": best.graph_recovery_evidence if best else 0.0,
            "propagation_path": list(best.propagation_path) if best else [],
            "localization_seconds": elapsed,
            "ablation": ablation or "full",
            "boundary_protection": use_boundary_protection,
            "role_replication": use_role_replication,
            "adaptive_exception_release": bool(parameters.get("adaptive_exception_release", False)),
            "exception_release_tail": float(parameters.get("exception_release_tail", 0.25)),
            "propagation_empirical_tail": obs.propagation_empirical_tail,
            "exception_release": obs.exception_release,
            "alarm_regime_conditioned_residual": obs.alarm_regime_conditioned_residual,
        }
        results.append(LocalizationResult(
            cell=cell,
            score=(total - rank + 1) / total,
            candidate_formula=best.candidate.formula if best else None,
            evidence=evidence,
        ))
    return results


__all__ = [
    "MODEL_VERSION",
    "ObservationalEvidence",
    "PlaceboEvidence",
    "matched_placebo_evidence",
    "observational_probe_set",
    "observational_ranking",
    "observational_source_evidence",
    "observational_uncertainty_set",
    "v5_core_r2_default_parameters",
    "v5_core_r2_scores",
]
