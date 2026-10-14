"""Candidate-centric FormulaGuard V5-Core.

V5-Core deliberately reuses the project's parser, workbook evaluator, and
low-level counterfactual energy functions, but it never calls ``v4_scores``.
Every formula receives a repair portfolio before cells are ranked.  The
portfolio is evaluated through four independent evidence families and either
an auditable corroboration rule or a sign-constrained linear ranker.
"""

from __future__ import annotations

import json
import math
import statistics
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .a1 import num_to_col, parse_address
from .formula import (
    Binary,
    Func,
    Range,
    Unary,
    edit_cost,
    normalized_formula,
    parse_formula,
    translate_formula,
)
from .localize import (
    LocalizationResult,
    RepairCandidate,
    _energy,
    _v4_bounded_change,
    _v4_local_energy,
    _v4_matched_controls,
    _v4_scope_weights,
    behavior_anomaly_scores,
    formula_anomaly_scores,
    graph_anomaly_scores,
)
from .v6 import (
    SemanticEvidence,
    _reference_quality,
    relative_ast_signature,
    semantic_candidates,
    semantic_peers,
)
from .workbook import CellKey, DependencyGraph, WorkbookModel


MODEL_VERSION = "v5-core-dev-r2"
DEFAULT_CANDIDATE_LIMIT = 32
DEFAULT_BASE_INTERVENTIONS = 2
DEFAULT_DEEP_CELL_LIMIT = 120
DEFAULT_DEEP_CANDIDATE_LIMIT = 8
DEFAULT_SCOPE_DEPTH = 3
DEFAULT_SCOPE_DECAY = 0.70
DEFAULT_ALARM_THRESHOLD = 0.35
DEFAULT_ALARM_MARGIN = 0.05

FEATURE_NAMES = (
    "structural_evidence",
    "causal_evidence",
    "graph_recovery_evidence",
    "replication_evidence",
    "candidate_quality",
    "formula_anomaly",
    "graph_anomaly",
    "behavior_anomaly",
    "exception_likelihood",
    "global_harm",
)
POSITIVE_FEATURES = frozenset(FEATURE_NAMES[:8])
NEGATIVE_FEATURES = frozenset(FEATURE_NAMES[8:])


@dataclass(frozen=True)
class RegimeEvidence:
    regime_id: str
    regime_type: str
    peer_directions: tuple[str, ...]
    peer_count: int
    relative_ast_signature: str
    boundary_role: str
    periodic_position: str
    exception_likelihood: float


@dataclass(frozen=True)
class PortfolioCandidate:
    candidate: RepairCandidate
    family_support: float = 0.0
    family_margin: float = 0.0
    boundary_support: float = 0.0
    boundary_margin: float = 0.0
    directions: tuple[str, ...] = ()
    source_families: tuple[str, ...] = ()


@dataclass
class CandidateEvidence:
    candidate: RepairCandidate
    structural_evidence: float
    causal_evidence: float
    graph_recovery_evidence: float
    replication_evidence: float
    counterfactual_delta: float
    irg: float
    local_harm: float
    global_harm: float
    recovered_descendants: int
    recovered_branches: int
    descendant_coverage: float
    propagation_path: tuple[str, ...]
    exception_likelihood: float
    responsibility: float
    evidence_tier: str
    controls: int
    evaluated: bool = True
    raw: dict[str, object] = field(default_factory=dict)


def v5_core_default_parameters() -> dict[str, object]:
    return {
        "model_version": MODEL_VERSION,
        "architecture": "candidate_centric_multi_evidence_responsibility",
        "candidate_limit": DEFAULT_CANDIDATE_LIMIT,
        "base_interventions": DEFAULT_BASE_INTERVENTIONS,
        "deep_cell_limit": DEFAULT_DEEP_CELL_LIMIT,
        "deep_candidate_limit": DEFAULT_DEEP_CANDIDATE_LIMIT,
        "scope_depth": DEFAULT_SCOPE_DEPTH,
        "scope_decay": DEFAULT_SCOPE_DECAY,
        "alarm_threshold": DEFAULT_ALARM_THRESHOLD,
        "alarm_margin": DEFAULT_ALARM_MARGIN,
        "feature_names": list(FEATURE_NAMES),
        "random_seed": 20260827,
    }


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _outer_class(formula: str) -> str:
    try:
        node = parse_formula(formula)
    except Exception:
        return "unsupported"
    if isinstance(node, Func):
        return "aggregate" if node.name in {"SUM", "AVERAGE", "MIN", "MAX"} else "function"
    if isinstance(node, Binary):
        return "binary"
    if isinstance(node, Unary):
        return "unary"
    return type(node).__name__.lower()


def _directional_peers(
    model: WorkbookModel,
    key: CellKey,
    *,
    radius: int = 5,
) -> dict[str, list[CellKey]]:
    anchor = parse_address(key[1])
    formula_set = set(model.formula_cells)
    directions: dict[str, list[CellKey]] = {name: [] for name in ("up", "down", "left", "right")}
    for name, drow, dcol in (
        ("up", -1, 0), ("down", 1, 0), ("left", 0, -1), ("right", 0, 1),
    ):
        for distance in range(1, radius + 1):
            row = anchor.row + drow * distance
            col = anchor.col + dcol * distance
            if row < 1 or col < 1:
                break
            peer = (key[0], f"{num_to_col(col)}{row}")
            if peer not in formula_set:
                break
            directions[name].append(peer)
    return directions


def _periodic_pattern(signatures: Sequence[str]) -> tuple[int, float]:
    if len(signatures) < 4:
        return 0, 0.0
    best_period, best_ratio = 0, 0.0
    for period in (2, 3):
        if len(signatures) < period * 2:
            continue
        # Use slot consensus instead of adjacent pair agreement.  A single
        # corrupted formula breaks two pair comparisons and used to push a
        # genuine 2-period family below the 0.80 threshold (7/9 for an
        # eleven-formula line).  Slot consensus is robust to that one outlier
        # while still requiring distinct modal signatures across the slots,
        # so a uniform copy family is not mislabeled as periodic.
        slot_modes: list[str] = []
        matched = 0
        for slot in range(period):
            values = list(signatures[slot::period])
            counts = Counter(values)
            mode, count = max(counts.items(), key=lambda item: (item[1], item[0]))
            slot_modes.append(mode)
            matched += count
        if len(set(slot_modes)) < 2:
            continue
        ratio = matched / len(signatures)
        if ratio > best_ratio:
            best_period, best_ratio = period, ratio
    return (best_period, best_ratio) if best_ratio >= 0.80 else (0, best_ratio)


def discover_formula_regimes(model: WorkbookModel) -> dict[CellKey, RegimeEvidence]:
    """Build label-free local formula regimes, including legitimate exceptions."""
    coordinates: dict[str, list[CellKey]] = defaultdict(list)
    for cell in model.formula_cells:
        coordinates[cell[0]].append(cell)
    results: dict[CellKey, RegimeEvidence] = {}
    for cell in model.formula_cells:
        peers = _directional_peers(model, cell)
        active = tuple(name for name, rows in peers.items() if rows)
        horizontal = len(peers["left"]) + len(peers["right"])
        vertical = len(peers["up"]) + len(peers["down"])
        if horizontal >= 2 and vertical >= 2:
            regime_type = "two_dimensional"
        elif horizontal >= 2:
            regime_type = "row_family"
        elif vertical >= 2:
            regime_type = "column_family"
        else:
            regime_type = "isolated"

        ordered_line: list[CellKey]
        if horizontal >= vertical:
            ordered_line = list(reversed(peers["left"])) + [cell] + peers["right"]
        else:
            ordered_line = list(reversed(peers["up"])) + [cell] + peers["down"]
        signatures = []
        for item in ordered_line:
            try:
                signatures.append(relative_ast_signature(model.formulas[item], item[1]))
            except Exception:
                signatures.append("unsupported")
        period, periodic_ratio = _periodic_pattern(signatures)
        periodic_member = False
        if period:
            regime_type = "periodic"
            cell_index = ordered_line.index(cell)
            slot = cell_index % period
            periodic_position = f"period_{period}_slot_{slot}"
            slot_signatures = signatures[slot::period]
            slot_mode = Counter(slot_signatures).most_common(1)[0][0]
            periodic_member = signatures[cell_index] == slot_mode
        else:
            periodic_position = "none"

        sheet_cells = coordinates[cell[0]]
        address = parse_address(cell[1])
        rows = [parse_address(item[1]).row for item in sheet_cells]
        cols = [parse_address(item[1]).col for item in sheet_cells]
        edge = address.row in {min(rows), max(rows)} or address.col in {min(cols), max(cols)}
        try:
            node = parse_formula(model.formulas[cell])
            aggregate = isinstance(node, Func) and node.name in {"SUM", "AVERAGE", "MIN", "MAX"}
        except Exception:
            aggregate = False
        boundary_role = "summary" if aggregate and edge else "edge" if edge else "interior"

        translated_matches = 0
        translated_total = 0
        own = normalized_formula(model.formulas[cell])
        for rows_in_direction in peers.values():
            for peer in rows_in_direction:
                try:
                    translated = normalized_formula(translate_formula(model.formulas[peer], peer[1], cell[1]))
                except Exception:
                    continue
                translated_total += 1
                translated_matches += translated == own
        consistency = translated_matches / max(1, translated_total)
        exception = 0.0
        if regime_type == "isolated":
            exception += 0.35
        if boundary_role == "summary":
            exception += 0.35
        elif boundary_role == "edge":
            exception += 0.15
        if period and periodic_member:
            # Periodicity is only evidence for a legitimate exception when
            # the current formula matches the consensus of its own slot.  A
            # blanket periodicity bonus protected the corrupted member too,
            # which is exactly the opposite of exception-aware localization.
            exception += 0.50 * periodic_ratio
        if translated_total and consistency >= 0.60:
            # A formula that is reproduced by its local copy family is a
            # legitimate member, even when alternative edits happen to reduce
            # a noisy global energy component.  This is the central V5 clean
            # control safeguard rather than a post-ranking exception patch.
            exception += 0.50
        signature = relative_ast_signature(model.formulas[cell], cell[1])
        regime_token = f"{cell[0]}:{regime_type}:{address.row if regime_type == 'row_family' else address.col}"
        results[cell] = RegimeEvidence(
            regime_id=regime_token,
            regime_type=regime_type,
            peer_directions=active,
            peer_count=sum(len(rows) for rows in peers.values()),
            relative_ast_signature=signature,
            boundary_role=boundary_role,
            periodic_position=periodic_position,
            exception_likelihood=_clamp(exception),
        )
    return results


def _source_family(source: str) -> str:
    if source.startswith("peer_") or source in {"family_consensus", "matrix_translation"}:
        return "peer_family"
    if "boundary" in source:
        return "range_boundary"
    if "cross_sheet" in source:
        return "cross_sheet"
    if source == "bounded_edit":
        return "bounded_edit"
    return source.split("_", 1)[0]


def _category(candidate: RepairCandidate) -> str:
    joined = " ".join((*candidate.edit_kinds, *candidate.sources))
    if "cross_sheet" in joined:
        return "cross_sheet"
    if "range" in joined:
        return "range"
    if "aggregate_function" in joined:
        return "family"
    if "operator" in joined:
        return "operator"
    if "peer" in joined or "family" in joined or "copy_pattern" in joined:
        return "translation"
    return "reference"


def _edit_dimension_count(candidate: RepairCandidate) -> int:
    """Count independent semantic edit dimensions, not generator aliases."""
    dimensions = set()
    joined = " ".join(candidate.edit_kinds)
    if "aggregate_function" in joined:
        dimensions.add("function")
    if "range" in joined:
        dimensions.add("range")
    if "operator" in joined:
        dimensions.add("operator")
    if any(token in joined for token in ("reference", "copy_offset", "parameter_anchor", "absolute")):
        dimensions.add("reference")
    if not dimensions:
        dimensions.add("translation")
    return len(dimensions)


def _merge_portfolio_entry(
    merged: dict[str, PortfolioCandidate],
    entry: PortfolioCandidate,
) -> None:
    norm = normalized_formula(entry.candidate.formula)
    current = merged.get(norm)
    if current is None:
        merged[norm] = entry
        return
    candidate = RepairCandidate(
        formula=current.candidate.formula,
        support=max(current.candidate.support, entry.candidate.support),
        sources=tuple(sorted(set(current.candidate.sources) | set(entry.candidate.sources))),
        edit_kinds=tuple(sorted(set(current.candidate.edit_kinds) | set(entry.candidate.edit_kinds))),
        edit_cost=min(current.candidate.edit_cost, entry.candidate.edit_cost),
        reference_quality=max(current.candidate.reference_quality, entry.candidate.reference_quality),
        quality=max(current.candidate.quality, entry.candidate.quality),
    )
    merged[norm] = PortfolioCandidate(
        candidate=candidate,
        family_support=max(current.family_support, entry.family_support),
        family_margin=max(current.family_margin, entry.family_margin),
        boundary_support=max(current.boundary_support, entry.boundary_support),
        boundary_margin=max(current.boundary_margin, entry.boundary_margin),
        directions=tuple(sorted(set(current.directions) | set(entry.directions))),
        source_families=tuple(sorted(set(current.source_families) | set(entry.source_families))),
    )


def build_candidate_portfolio(
    model: WorkbookModel,
    cell: CellKey,
    *,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    regime: RegimeEvidence | None = None,
) -> list[PortfolioCandidate]:
    """Generate the bounded V5 portfolio before any cell ranking is created."""
    if candidate_limit < 1:
        return []
    original = model.formulas[cell]
    merged: dict[str, PortfolioCandidate] = {}
    semantic = semantic_candidates(
        model,
        cell,
        base_candidate_limit=max(15, candidate_limit),
        semantic_candidate_limit=max(25, candidate_limit),
        include_boundary=True,
    )
    available_directions = tuple(sorted({direction for _, direction in semantic_peers(model, cell, radius=5)}))
    for item in semantic:
        families = tuple(sorted({_source_family(source) for source in item.candidate.sources}))
        _merge_portfolio_entry(merged, PortfolioCandidate(
            candidate=item.candidate,
            family_support=item.family_support,
            family_margin=item.family_margin,
            boundary_support=item.boundary_support,
            boundary_margin=item.boundary_margin,
            directions=available_directions[: item.direction_count],
            source_families=families,
        ))

    # A corrupted member of an alternating/periodic family must be compared
    # with peers in the same periodic slot, not with the immediately adjacent
    # (different-slot) formulas.  This is a separate label-free source: the
    # period and phase come only from surrounding relative-AST signatures.
    if regime is not None and regime.regime_type == "periodic":
        try:
            period = int(regime.periodic_position.split("_", 2)[1])
        except (IndexError, ValueError):
            period = 0
        if period in {2, 3}:
            anchor = parse_address(cell[1])
            formula_set = set(model.formula_cells)
            periodic_votes: dict[str, list[tuple[str, str]]] = defaultdict(list)
            for sign, direction in ((-1, "up"), (1, "down")):
                for multiple in range(1, 3):
                    row = anchor.row + sign * period * multiple
                    if row < 1:
                        continue
                    peer = (cell[0], f"{num_to_col(anchor.col)}{row}")
                    if peer not in formula_set:
                        continue
                    try:
                        proposal = translate_formula(model.formulas[peer], peer[1], cell[1])
                        parse_formula(proposal)
                    except Exception:
                        continue
                    if normalized_formula(proposal) == normalized_formula(original):
                        continue
                    periodic_votes[normalized_formula(proposal)].append((proposal, direction))
            vote_counts = sorted((len(rows) for rows in periodic_votes.values()), reverse=True)
            second_count = vote_counts[1] if len(vote_counts) > 1 else 0
            total_votes = sum(vote_counts)
            for rows in periodic_votes.values():
                if len(rows) < 2:
                    continue
                proposal = sorted(item[0] for item in rows)[0]
                directions = tuple(sorted({f"periodic_{item[1]}" for item in rows}))
                sources = tuple(sorted({"periodic_slot_consensus", *directions}))
                edit_kinds = ["copy_pattern"]
                if _outer_class(proposal) != _outer_class(original):
                    edit_kinds.append("aggregate_function")
                support = len(rows) / max(1, total_votes)
                margin = (len(rows) - second_count) / max(1, total_votes)
                candidate = RepairCandidate(
                    proposal,
                    len(rows),
                    sources,
                    tuple(edit_kinds),
                    edit_cost(original, proposal),
                    1.0,
                    min(1.0, 0.60 + 0.10 * len(rows) + 0.15 * support),
                )
                _merge_portfolio_entry(merged, PortfolioCandidate(
                    candidate=candidate,
                    family_support=support,
                    family_margin=max(0.0, margin),
                    directions=directions,
                    source_families=("peer_family",),
                ))

    # Two-dimensional peers supplement the row/column-only semantic generator.
    anchor = parse_address(cell[1])
    matrix_votes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for peer in model.formula_cells:
        if peer == cell or peer[0] != cell[0]:
            continue
        address = parse_address(peer[1])
        if abs(address.row - anchor.row) > 2 or abs(address.col - anchor.col) > 2:
            continue
        if address.row == anchor.row or address.col == anchor.col:
            continue
        if _outer_class(model.formulas[peer]) != _outer_class(original):
            continue
        try:
            proposal = translate_formula(model.formulas[peer], peer[1], cell[1])
            parse_formula(proposal)
        except Exception:
            continue
        if normalized_formula(proposal) != normalized_formula(original):
            matrix_votes[normalized_formula(proposal)].append((proposal, peer[1]))
    for rows in matrix_votes.values():
        if len(rows) < 2:
            continue
        proposal = sorted(item[0] for item in rows)[0]
        base = next((item for item in semantic if normalized_formula(item.candidate.formula) == normalized_formula(proposal)), None)
        quality = base.candidate.reference_quality if base else 1.0
        candidate = RepairCandidate(
            proposal, len(rows), ("matrix_translation",), ("copy_pattern",),
            edit_cost(original, proposal), quality,
            min(1.0, 0.45 + 0.10 * len(rows) + 0.25 * quality),
        )
        _merge_portfolio_entry(merged, PortfolioCandidate(
            candidate=candidate,
            family_support=min(1.0, len(rows) / 4),
            family_margin=min(1.0, len(rows) / 4),
            directions=("matrix",),
            source_families=("peer_family",),
        ))

    # Same-address formula mappings across sheets are a separate evidence source.
    cross_votes: dict[str, list[str]] = defaultdict(list)
    for peer in model.formula_cells:
        if peer[0] == cell[0] or peer[1] != cell[1]:
            continue
        try:
            proposal = translate_formula(model.formulas[peer], peer[1], cell[1])
            parse_formula(proposal)
        except Exception:
            continue
        if normalized_formula(proposal) != normalized_formula(original):
            cross_votes[normalized_formula(proposal)].append(proposal)
    for rows in cross_votes.values():
        proposal = sorted(rows)[0]
        candidate = RepairCandidate(
            proposal, len(rows), ("cross_sheet_mapping",), ("cross_sheet_reference",),
            edit_cost(original, proposal), 1.0,
            min(1.0, 0.50 + 0.15 * len(rows)),
        )
        _merge_portfolio_entry(merged, PortfolioCandidate(
            candidate=candidate,
            family_support=min(1.0, len(rows) / 3),
            family_margin=min(1.0, len(rows) / 3),
            directions=("cross_sheet",),
            source_families=("cross_sheet",),
        ))

    validated: list[PortfolioCandidate] = []
    original_normalized = normalized_formula(original)
    for item in merged.values():
        formula = item.candidate.formula
        try:
            parse_formula(formula)
        except Exception:
            continue
        if normalized_formula(formula) == original_normalized:
            continue
        reference_quality = _reference_quality(model, cell, formula)
        if reference_quality < 0.80:
            continue
        candidate = RepairCandidate(
            formula=formula,
            support=item.candidate.support,
            sources=item.candidate.sources,
            edit_kinds=item.candidate.edit_kinds,
            edit_cost=item.candidate.edit_cost,
            reference_quality=reference_quality,
            quality=min(1.0, item.candidate.quality * (0.75 + 0.25 * reference_quality)),
        )
        validated.append(PortfolioCandidate(
            candidate=candidate,
            family_support=item.family_support,
            family_margin=item.family_margin,
            boundary_support=item.boundary_support,
            boundary_margin=item.boundary_margin,
            directions=item.directions,
            source_families=item.source_families,
        ))
    ranked = sorted(validated, key=lambda item: (
        -max(item.family_support, item.boundary_support),
        -item.candidate.support,
        -item.candidate.quality,
        item.candidate.edit_cost,
        item.candidate.formula,
    ))
    quotas = {
        "translation": 8,
        "family": 5,
        "range": 7,
        "reference": 6,
        "operator": 3,
        "cross_sheet": 3,
    }
    selected: list[PortfolioCandidate] = []
    used: set[str] = set()
    for category, quota in quotas.items():
        for item in ranked:
            norm = normalized_formula(item.candidate.formula)
            if quota <= 0:
                break
            if norm in used or _category(item.candidate) != category:
                continue
            selected.append(item)
            used.add(norm)
            quota -= 1
    for item in ranked:
        if len(selected) >= candidate_limit:
            break
        norm = normalized_formula(item.candidate.formula)
        if norm not in used:
            selected.append(item)
            used.add(norm)
    # Quotas decide membership, not intervention priority. Return the chosen
    # pool in one global label-free quality order so the base budget really is
    # spent on the two strongest candidates rather than the first category.
    selected_norms = {normalized_formula(item.candidate.formula) for item in selected}
    return [
        item for item in ranked
        if normalized_formula(item.candidate.formula) in selected_norms
    ][:candidate_limit]


def _intervention_portfolio(
    portfolio: Sequence[PortfolioCandidate],
    limit: int,
    *,
    deep: bool,
    base_count: int = DEFAULT_BASE_INTERVENTIONS,
) -> list[PortfolioCandidate]:
    """Choose a quality-first, category-diverse counterfactual budget."""
    if limit <= 0:
        return []
    ordered = list(portfolio)
    if not deep or limit <= base_count:
        return ordered[:limit]
    chosen = ordered[: min(base_count, limit)]
    used = {normalized_formula(item.candidate.formula) for item in chosen}
    represented = {_category(item.candidate) for item in chosen}
    for category in ("family", "range", "translation", "reference", "operator", "cross_sheet"):
        if len(chosen) >= limit:
            break
        if category in represented:
            continue
        item = next((
            row for row in ordered
            if _category(row.candidate) == category
            and normalized_formula(row.candidate.formula) not in used
        ), None)
        if item is not None:
            chosen.append(item)
            used.add(normalized_formula(item.candidate.formula))
            represented.add(category)
    for item in ordered:
        if len(chosen) >= limit:
            break
        normalized = normalized_formula(item.candidate.formula)
        if normalized not in used:
            chosen.append(item)
            used.add(normalized)
    return chosen


def _map_value(maps: Mapping[str, Mapping[CellKey, float]], cell: CellKey) -> float:
    values = [float(mapping.get(cell, 0.0)) for mapping in maps.values()]
    return statistics.fmean(values) if values else 0.0


def _propagation_metrics(
    graph: DependencyGraph,
    source: CellKey,
    formula_cells: set[CellKey],
    before_maps: Mapping[str, Mapping[CellKey, float]],
    after_maps: Mapping[str, Mapping[CellKey, float]],
) -> tuple[float, int, int, float, float, tuple[str, ...]]:
    descendants = graph.descendants(source) & formula_cells
    if not descendants:
        return 0.0, 0, 0, 0.0, 0.0, ()
    weighted_possible = 0.0
    weighted_recovery = 0.0
    weighted_harm = 0.0
    recovered = 0
    branches: set[CellKey] = set()
    path_example: tuple[str, ...] = ()
    direct_children = set(graph.dependents.get(source, ()))
    for cell in descendants:
        depth = graph.shortest_path_length(source, cell) or 1
        weight = DEFAULT_SCOPE_DECAY ** max(0, depth - 1)
        weighted_possible += weight
        change = _map_value(before_maps, cell) - _map_value(after_maps, cell)
        if change > 0:
            weighted_recovery += weight * min(1.0, change)
            recovered += 1
            path = graph.shortest_path(source, cell) or []
            if len(path) > 1 and path[1] in direct_children:
                branches.add(path[1])
            if not path_example and len(path) > 1:
                path_example = tuple(f"{sheet}!{address}" for sheet, address in path)
        elif change < 0:
            weighted_harm += weight * min(1.0, -change)
    recovery_ratio = weighted_recovery / max(weighted_possible, 1e-9)
    harm_ratio = weighted_harm / max(weighted_possible, 1e-9)
    descendant_coverage = recovered / max(1, len(descendants))
    branch_coverage = len(branches) / max(1, len(direct_children))
    score = _clamp(0.55 * recovery_ratio + 0.25 * descendant_coverage + 0.20 * branch_coverage)
    return score, recovered, len(branches), descendant_coverage, harm_ratio, path_example


def _evaluate_candidates(
    model: WorkbookModel,
    cell: CellKey,
    portfolio: Sequence[PortfolioCandidate],
    regime: RegimeEvidence,
    *,
    formula_anomaly: float,
    graph_anomaly: float,
    behavior_anomaly: float,
    base_global_energy: float,
    base_maps: Mapping[str, Mapping[CellKey, float]],
    graph: DependencyGraph,
    limit: int,
) -> list[CandidateEvidence]:
    scope = _v4_scope_weights(model, graph, cell, max_depth=DEFAULT_SCOPE_DEPTH, decay=DEFAULT_SCOPE_DECAY)
    before, _ = _v4_local_energy(base_maps, scope)
    raw_rows: list[dict[str, object]] = []
    selected = list(portfolio[:limit])
    for entry in selected:
        candidate = entry.candidate
        global_after, _, maps_after = _energy(model, {cell: candidate.formula}, include_maps=True)
        local_after, _ = _v4_local_energy(maps_after, scope)
        local_gain, local_harm = _v4_bounded_change(before, local_after)
        _, global_harm = _v4_bounded_change(base_global_energy, global_after)
        propagation = _propagation_metrics(
            graph, cell, set(model.formula_cells), base_maps, maps_after,
        )
        delta = local_gain - 0.50 * max(local_harm, global_harm, propagation[4])
        raw_rows.append({
            "portfolio": entry,
            "candidate": candidate,
            "delta": delta,
            "local_harm": local_harm,
            "global_harm": max(global_harm, propagation[4]),
            "propagation": propagation,
        })

    results: list[CandidateEvidence] = []
    for raw in raw_rows:
        entry: PortfolioCandidate = raw["portfolio"]  # type: ignore[assignment]
        candidate: RepairCandidate = raw["candidate"]  # type: ignore[assignment]
        controls = _v4_matched_controls(candidate, raw_rows)
        positive_controls = [max(0.0, float(item["delta"])) for item in controls]
        control_median = statistics.median(positive_controls) if positive_controls else 0.0
        delta = float(raw["delta"])
        irg = max(delta, 0.0) / max(0.01, control_median)
        semantic_strength = max(entry.family_support, entry.boundary_support)
        semantic_margin = max(entry.family_margin, entry.boundary_margin)
        structural = _clamp(0.55 * semantic_strength + 0.25 * semantic_margin + 0.20 * formula_anomaly)
        # Prefer one-mechanism explanations to unnecessary compound repairs
        # when their label-free peer support is otherwise comparable.
        edit_dimensions = _edit_dimension_count(candidate)
        structural *= 1.0 if edit_dimensions == 1 else max(0.70, 1.0 - 0.15 * (edit_dimensions - 1))
        causal = math.sqrt(_clamp(max(delta, 0.0) / 0.10) * _clamp(irg / 3.0))
        propagation = raw["propagation"]
        graph_recovery = float(propagation[0])
        directions = set(entry.directions)
        source_families = set(entry.source_families) or {_source_family(item) for item in candidate.sources}
        replication = _clamp(
            0.50 * min(1.0, len(directions) / 2)
            + 0.50 * min(1.0, len(source_families) / 2)
        )
        uniqueness = semantic_margin
        exception = regime.exception_likelihood
        if uniqueness < 0.10:
            exception += 0.20
        if len(source_families) < 2:
            exception += 0.10
        exception = _clamp(exception)
        harm = _clamp(max(float(raw["local_harm"]), float(raw["global_harm"])))
        families = sorted((structural, causal, graph_recovery, replication), reverse=True)
        responsibility = math.sqrt(families[0] * families[1]) * (1.0 - exception) * (1.0 - harm)
        if families[1] >= 0.50 and harm <= 0.10:
            tier = "corroborated"
        elif families[1] >= 0.25:
            tier = "review"
        else:
            tier = "unverified"
        results.append(CandidateEvidence(
            candidate=candidate,
            structural_evidence=structural,
            causal_evidence=causal,
            graph_recovery_evidence=graph_recovery,
            replication_evidence=replication,
            counterfactual_delta=delta,
            irg=irg,
            local_harm=float(raw["local_harm"]),
            global_harm=float(raw["global_harm"]),
            recovered_descendants=int(propagation[1]),
            recovered_branches=int(propagation[2]),
            descendant_coverage=float(propagation[3]),
            propagation_path=tuple(propagation[5]),
            exception_likelihood=exception,
            responsibility=responsibility,
            evidence_tier=tier,
            controls=len(controls),
        ))
    results.sort(key=lambda item: (
        -item.responsibility,
        -sorted((item.structural_evidence, item.causal_evidence, item.graph_recovery_evidence, item.replication_evidence), reverse=True)[2],
        -item.candidate.quality,
        -item.candidate.reference_quality,
        -item.descendant_coverage,
    ))
    return results


def _default_candidate_evidence(
    portfolio: Sequence[PortfolioCandidate],
    regime: RegimeEvidence,
    formula_score: float,
) -> CandidateEvidence | None:
    if not portfolio:
        return None
    entry = portfolio[0]
    structural = _clamp(
        0.55 * max(entry.family_support, entry.boundary_support)
        + 0.25 * max(entry.family_margin, entry.boundary_margin)
        + 0.20 * formula_score
    )
    return CandidateEvidence(
        candidate=entry.candidate,
        structural_evidence=structural,
        causal_evidence=0.0,
        graph_recovery_evidence=0.0,
        replication_evidence=0.0,
        counterfactual_delta=0.0,
        irg=0.0,
        local_harm=0.0,
        global_harm=0.0,
        recovered_descendants=0,
        recovered_branches=0,
        descendant_coverage=0.0,
        propagation_path=(),
        exception_likelihood=regime.exception_likelihood,
        responsibility=0.0,
        evidence_tier="not_evaluated",
        controls=0,
        evaluated=False,
    )


def _prepare_v5_core(
    model: WorkbookModel,
    *,
    candidate_limit: int,
    base_interventions: int,
    deep_cell_limit: int,
    deep_candidate_limit: int,
) -> dict[str, object]:
    cache = getattr(model, "_fg_v5_core_cache", None)
    cache_key = (candidate_limit, base_interventions, deep_cell_limit, deep_candidate_limit)
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    started = time.perf_counter()
    regimes = discover_formula_regimes(model)
    formula_scores = formula_anomaly_scores(model)
    graph_scores = graph_anomaly_scores(model)
    behavior_scores = behavior_anomaly_scores(model)
    portfolios = {
        cell: build_candidate_portfolio(
            model,
            cell,
            candidate_limit=candidate_limit,
            regime=regimes[cell],
        )
        for cell in model.formula_cells
    }
    preliminary: dict[CellKey, float] = {}
    for cell, rows in portfolios.items():
        best_semantic = max((
            0.6 * max(row.family_support, row.boundary_support)
            + 0.4 * row.candidate.quality for row in rows
        ), default=0.0)
        preliminary[cell] = (
            0.50 * best_semantic
            + 0.20 * formula_scores.get(cell, 0.0)
            + 0.15 * graph_scores.get(cell, 0.0)
            + 0.15 * behavior_scores.get(cell, 0.0)
        )
    deep_cells = set(sorted(
        model.formula_cells,
        key=lambda cell: (-preliminary[cell], cell),
    )[: min(deep_cell_limit, len(model.formula_cells))])
    base_global_energy, _, base_maps = _energy(model, include_maps=True)
    graph = model.dependency_graph()
    evidence_by_cell: dict[CellKey, list[CandidateEvidence]] = {}
    for cell in model.formula_cells:
        is_deep = cell in deep_cells
        limit = deep_candidate_limit if is_deep else base_interventions
        intervention_portfolio = _intervention_portfolio(
            portfolios[cell], min(limit, len(portfolios[cell])), deep=is_deep,
            base_count=base_interventions,
        )
        evidence_by_cell[cell] = _evaluate_candidates(
            model,
            cell,
            intervention_portfolio,
            regimes[cell],
            formula_anomaly=formula_scores.get(cell, 0.0),
            graph_anomaly=graph_scores.get(cell, 0.0),
            behavior_anomaly=behavior_scores.get(cell, 0.0),
            base_global_energy=base_global_energy,
            base_maps=base_maps,
            graph=graph,
            limit=len(intervention_portfolio),
        )
        if not evidence_by_cell[cell]:
            fallback = _default_candidate_evidence(portfolios[cell], regimes[cell], formula_scores.get(cell, 0.0))
            evidence_by_cell[cell] = [fallback] if fallback else []
    prepared = {
        "regimes": regimes,
        "portfolios": portfolios,
        "evidence_by_cell": evidence_by_cell,
        "formula_scores": formula_scores,
        "graph_scores": graph_scores,
        "behavior_scores": behavior_scores,
        "preliminary": preliminary,
        "deep_cells": deep_cells,
        "elapsed": time.perf_counter() - started,
    }
    if cache is None:
        cache = {}
        setattr(model, "_fg_v5_core_cache", cache)
    cache[cache_key] = prepared
    return prepared


def _load_config(config: Mapping[str, object] | str | Path | None) -> dict[str, object]:
    if config is None:
        return {}
    if isinstance(config, Mapping):
        return dict(config)
    return json.loads(Path(config).read_text(encoding="utf-8"))


def _feature_vector(
    evidence: CandidateEvidence | None,
    *,
    formula_score: float,
    graph_score: float,
    behavior_score: float,
) -> dict[str, float]:
    return {
        "structural_evidence": evidence.structural_evidence if evidence else 0.0,
        "causal_evidence": evidence.causal_evidence if evidence else 0.0,
        "graph_recovery_evidence": evidence.graph_recovery_evidence if evidence else 0.0,
        "replication_evidence": evidence.replication_evidence if evidence else 0.0,
        "candidate_quality": evidence.candidate.quality if evidence else 0.0,
        "formula_anomaly": formula_score,
        "graph_anomaly": graph_score,
        "behavior_anomaly": behavior_score,
        "exception_likelihood": evidence.exception_likelihood if evidence else 1.0,
        "global_harm": evidence.global_harm if evidence else 1.0,
    }


def _learned_score(features: Mapping[str, float], config: Mapping[str, object]) -> float:
    default_weights = {name: (1.0 if name in POSITIVE_FEATURES else -1.0) for name in FEATURE_NAMES}
    weights = {**default_weights, **{str(k): float(v) for k, v in dict(config.get("feature_weights", {})).items()}}
    center = {str(k): float(v) for k, v in dict(config.get("feature_center", {})).items()}
    scale = {str(k): max(1e-9, float(v)) for k, v in dict(config.get("feature_scale", {})).items()}
    return sum(
        weights[name] * (float(features[name]) - center.get(name, 0.0)) / scale.get(name, 1.0)
        for name in FEATURE_NAMES
    )


def _score_candidate(
    evidence: CandidateEvidence,
    *,
    head: str,
    config: Mapping[str, object],
    features: Mapping[str, float],
    ablation: str | None,
) -> float:
    values = {
        "structural": evidence.structural_evidence,
        "causal": evidence.causal_evidence,
        "graph": evidence.graph_recovery_evidence,
        "replication": evidence.replication_evidence,
    }
    if ablation in {"no_structure", "no_causal", "no_graph", "no_replication"}:
        values[ablation.removeprefix("no_")] = 0.0
    exception = 0.0 if ablation in {"no_regime", "no_exception"} else evidence.exception_likelihood
    harm = 0.0 if ablation == "no_harm" else max(evidence.local_harm, evidence.global_harm)
    if ablation == "weighted_sum":
        return 0.25 * sum(values.values()) * (1.0 - exception) * (1.0 - harm)
    if head == "learned":
        adjusted = dict(features)
        adjusted.update({
            "structural_evidence": values["structural"],
            "causal_evidence": values["causal"],
            "graph_recovery_evidence": values["graph"],
            "replication_evidence": values["replication"],
            "exception_likelihood": exception,
            "global_harm": harm,
        })
        return _learned_score(adjusted, config)
    ordered = sorted(values.values(), reverse=True)
    return math.sqrt(ordered[0] * ordered[1]) * (1.0 - exception) * (1.0 - harm)


def v5_core_scores(
    model: WorkbookModel,
    *,
    head: str = "rule",
    config: Mapping[str, object] | str | Path | None = None,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    base_interventions: int = DEFAULT_BASE_INTERVENTIONS,
    deep_cell_limit: int = DEFAULT_DEEP_CELL_LIMIT,
    deep_candidate_limit: int = DEFAULT_DEEP_CANDIDATE_LIMIT,
    ablation: str | None = None,
) -> list[LocalizationResult]:
    """Return a complete, label-free V5-Core ranking."""
    normalized_head = head.lower()
    if normalized_head not in {"rule", "learned"}:
        raise ValueError("head must be 'rule' or 'learned'")
    allowed_ablations = {
        None, "no_regime", "no_exception", "no_structure", "no_causal",
        "no_graph", "no_replication", "no_harm", "weighted_sum",
    }
    if ablation not in allowed_ablations:
        raise ValueError(f"Unknown V5-Core ablation: {ablation}")
    parameters = _load_config(config)
    prepared = _prepare_v5_core(
        model,
        candidate_limit=candidate_limit,
        base_interventions=base_interventions,
        deep_cell_limit=deep_cell_limit,
        deep_candidate_limit=deep_candidate_limit,
    )
    regimes: Mapping[CellKey, RegimeEvidence] = prepared["regimes"]  # type: ignore[assignment]
    portfolios: Mapping[CellKey, Sequence[PortfolioCandidate]] = prepared["portfolios"]  # type: ignore[assignment]
    evidence_by_cell: Mapping[CellKey, Sequence[CandidateEvidence]] = prepared["evidence_by_cell"]  # type: ignore[assignment]
    formula_scores: Mapping[CellKey, float] = prepared["formula_scores"]  # type: ignore[assignment]
    graph_scores: Mapping[CellKey, float] = prepared["graph_scores"]  # type: ignore[assignment]
    behavior_scores: Mapping[CellKey, float] = prepared["behavior_scores"]  # type: ignore[assignment]

    cell_rows: list[tuple[int, CellKey, CandidateEvidence | None, float, dict[str, float]]] = []
    for stable_index, cell in enumerate(model.formula_cells):
        best: CandidateEvidence | None = None
        best_score = float("-inf")
        best_features: dict[str, float] = {}
        for evidence in evidence_by_cell[cell]:
            features = _feature_vector(
                evidence,
                formula_score=formula_scores.get(cell, 0.0),
                graph_score=graph_scores.get(cell, 0.0),
                behavior_score=behavior_scores.get(cell, 0.0),
            )
            score = _score_candidate(
                evidence, head=normalized_head, config=parameters,
                features=features, ablation=ablation,
            )
            third_evidence = sorted((
                evidence.structural_evidence,
                evidence.causal_evidence,
                evidence.graph_recovery_evidence,
                evidence.replication_evidence,
            ), reverse=True)[2]
            tie = (
                score,
                evidence.responsibility,
                third_evidence,
                evidence.candidate.quality,
                evidence.candidate.reference_quality,
                evidence.descendant_coverage,
            )
            current_tie = (
                best_score,
                best.responsibility if best else -1.0,
                sorted((
                    best.structural_evidence,
                    best.causal_evidence,
                    best.graph_recovery_evidence,
                    best.replication_evidence,
                ), reverse=True)[2] if best else -1.0,
                best.candidate.quality if best else -1.0,
                best.candidate.reference_quality if best else -1.0,
                best.descendant_coverage if best else -1.0,
            )
            if tie > current_tie:
                best, best_score, best_features = evidence, score, features
        if best is None:
            best_score = 0.0
            best_features = _feature_vector(
                None,
                formula_score=formula_scores.get(cell, 0.0),
                graph_score=graph_scores.get(cell, 0.0),
                behavior_score=behavior_scores.get(cell, 0.0),
            )
        cell_rows.append((stable_index, cell, best, best_score, best_features))

    cell_rows.sort(key=lambda row: (
        -row[3],
        -(row[2].responsibility if row[2] else 0.0),
        -(
            sorted((
                row[2].structural_evidence,
                row[2].causal_evidence,
                row[2].graph_recovery_evidence,
                row[2].replication_evidence,
            ), reverse=True)[2] if row[2] else 0.0
        ),
        -(row[2].candidate.quality if row[2] else 0.0),
        -(row[2].candidate.reference_quality if row[2] else 0.0),
        -(row[2].descendant_coverage if row[2] else 0.0),
        row[0],
    ))
    top_score = cell_rows[0][3] if cell_rows else 0.0
    second_score = cell_rows[1][3] if len(cell_rows) > 1 else 0.0
    alarm_threshold = float(parameters.get("alarm_threshold", DEFAULT_ALARM_THRESHOLD))
    alarm_margin = float(parameters.get("alarm_margin", DEFAULT_ALARM_MARGIN))
    workbook_alarm = top_score >= alarm_threshold and top_score - second_score >= alarm_margin
    elapsed = float(prepared["elapsed"])
    results: list[LocalizationResult] = []
    for rank, (_, cell, best, score, features) in enumerate(cell_rows, 1):
        regime = regimes[cell]
        portfolio = portfolios[cell]
        evaluated_candidates = []
        for candidate_evidence in evidence_by_cell[cell]:
            candidate_features = _feature_vector(
                candidate_evidence,
                formula_score=formula_scores.get(cell, 0.0),
                graph_score=graph_scores.get(cell, 0.0),
                behavior_score=behavior_scores.get(cell, 0.0),
            )
            evaluated_candidates.append({
                "formula": candidate_evidence.candidate.formula,
                "feature_vector": candidate_features,
                "responsibility": candidate_evidence.responsibility,
                "candidate_quality": candidate_evidence.candidate.quality,
                "reference_quality": candidate_evidence.candidate.reference_quality,
                "evidence_tier": candidate_evidence.evidence_tier,
            })
        evidence = {
            "model_version": MODEL_VERSION,
            "head": normalized_head,
            "rank": rank,
            "alarm_status": "alarm" if workbook_alarm else "no_alarm",
            "alarm_threshold": alarm_threshold,
            "alarm_margin": alarm_margin,
            "regime_id": regime.regime_id,
            "regime_type": regime.regime_type,
            "peer_directions": list(regime.peer_directions),
            "peer_count": regime.peer_count,
            "relative_ast_signature": regime.relative_ast_signature,
            "boundary_role": regime.boundary_role,
            "periodic_position": regime.periodic_position,
            "exception_likelihood": best.exception_likelihood if best else regime.exception_likelihood,
            "candidate_formula": best.candidate.formula if best else "",
            "candidate_sources": list(best.candidate.sources) if best else [],
            "candidate_edit_kinds": list(best.candidate.edit_kinds) if best else [],
            "reference_quality": best.candidate.reference_quality if best else 0.0,
            "candidate_quality": best.candidate.quality if best else 0.0,
            "candidate_portfolio_size": len(portfolio),
            "candidate_portfolio": [
                {
                    "formula": row.candidate.formula,
                    "sources": list(row.candidate.sources),
                    "edit_kinds": list(row.candidate.edit_kinds),
                    "reference_quality": row.candidate.reference_quality,
                    "quality": row.candidate.quality,
                }
                for row in portfolio
            ],
            "evaluated_candidate_features": evaluated_candidates,
            "structural_evidence": best.structural_evidence if best else 0.0,
            "causal_evidence": best.causal_evidence if best else 0.0,
            "graph_recovery_evidence": best.graph_recovery_evidence if best else 0.0,
            "replication_evidence": best.replication_evidence if best else 0.0,
            "counterfactual_delta": best.counterfactual_delta if best else 0.0,
            "irg": best.irg if best else 0.0,
            "local_harm": best.local_harm if best else 0.0,
            "global_harm": best.global_harm if best else 0.0,
            "recovered_descendants": best.recovered_descendants if best else 0,
            "recovered_branches": best.recovered_branches if best else 0,
            "descendant_coverage": best.descendant_coverage if best else 0.0,
            "propagation_path": list(best.propagation_path) if best else [],
            "evidence_tier": best.evidence_tier if best else "no_candidate",
            "control_count": best.controls if best else 0,
            "formula_anomaly": formula_scores.get(cell, 0.0),
            "graph_anomaly": graph_scores.get(cell, 0.0),
            "behavior_anomaly": behavior_scores.get(cell, 0.0),
            "feature_vector": features,
            "localization_seconds": elapsed,
            "ablation": ablation or "full",
        }
        results.append(LocalizationResult(
            cell=cell,
            score=float(score),
            candidate_formula=best.candidate.formula if best else None,
            evidence=evidence,
        ))
    return results


def v5_core_ablation_scores(
    model: WorkbookModel,
    ablation: str,
    *,
    head: str = "rule",
    config: Mapping[str, object] | str | Path | None = None,
) -> list[LocalizationResult]:
    return v5_core_scores(model, head=head, config=config, ablation=ablation)


def _sigmoid_negative(margin: float) -> float:
    """Return 1/(1+exp(margin)) without overflow."""
    if margin >= 0:
        exp_value = math.exp(-margin)
        return exp_value / (1.0 + exp_value)
    exp_value = math.exp(margin)
    return 1.0 / (1.0 + exp_value)


def fit_pairwise_linear_ranker(
    pairs: Sequence[tuple[Mapping[str, float], Mapping[str, float]]],
    *,
    regularization: float = 0.1,
    max_epochs: int = 800,
    learning_rate: float = 0.05,
) -> dict[str, object]:
    """Fit a deterministic sign-constrained pairwise logistic ranker.

    Each pair is ``(true_source_features, hard_negative_features)``.  The
    implementation intentionally avoids a black-box ML dependency.
    """
    if not pairs:
        raise ValueError("At least one pair is required")
    center = {
        name: statistics.fmean(
            float(row.get(name, 0.0)) for pair in pairs for row in pair
        )
        for name in FEATURE_NAMES
    }
    scale = {}
    for name in FEATURE_NAMES:
        values = [float(row.get(name, 0.0)) for pair in pairs for row in pair]
        variance = statistics.fmean((value - center[name]) ** 2 for value in values)
        scale[name] = max(1e-6, math.sqrt(variance))
    differences = [
        [
            (float(positive.get(name, 0.0)) - float(negative.get(name, 0.0))) / scale[name]
            for name in FEATURE_NAMES
        ]
        for positive, negative in pairs
    ]
    weights = [0.1 if name in POSITIVE_FEATURES else -0.1 for name in FEATURE_NAMES]
    previous_loss = float("inf")
    stable_epochs = 0
    epochs = 0
    for epoch in range(1, max_epochs + 1):
        gradient = [regularization * value for value in weights]
        loss = 0.5 * regularization * sum(value * value for value in weights)
        for difference in differences:
            margin = sum(weight * value for weight, value in zip(weights, difference))
            probability = _sigmoid_negative(margin)
            loss += math.log1p(math.exp(-abs(margin))) + max(-margin, 0.0)
            for index, value in enumerate(difference):
                gradient[index] -= probability * value
        count = max(1, len(differences))
        rate = learning_rate / math.sqrt(epoch)
        for index, name in enumerate(FEATURE_NAMES):
            weights[index] -= rate * gradient[index] / count
            if name in POSITIVE_FEATURES:
                weights[index] = max(0.0, weights[index])
            else:
                weights[index] = min(0.0, weights[index])
        loss /= count
        if previous_loss - loss < 1e-7:
            stable_epochs += 1
        else:
            stable_epochs = 0
        previous_loss = loss
        epochs = epoch
        if stable_epochs >= 20:
            break
    return {
        "model_version": MODEL_VERSION,
        "head": "learned",
        "feature_names": list(FEATURE_NAMES),
        "feature_weights": dict(zip(FEATURE_NAMES, weights)),
        "feature_center": center,
        "feature_scale": scale,
        "regularization": regularization,
        "epochs": epochs,
        "training_pairs": len(pairs),
        "random_seed": 20260827,
    }


__all__ = [
    "CandidateEvidence",
    "FEATURE_NAMES",
    "MODEL_VERSION",
    "PortfolioCandidate",
    "RegimeEvidence",
    "build_candidate_portfolio",
    "discover_formula_regimes",
    "fit_pairwise_linear_ranker",
    "v5_core_ablation_scores",
    "v5_core_default_parameters",
    "v5_core_scores",
]
