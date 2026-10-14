"""FormulaGuard V6 semantic-consistency ranker.

V6 deliberately wraps the frozen V4 ranker.  It never mutates V4 output and
only performs one stable, auditable promotion when formula-family or range
semantics and a counterfactual intervention agree.
"""

from __future__ import annotations

import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .a1 import iter_rect, parse_address
from .formula import (
    Binary,
    Func,
    Range,
    Ref,
    Unary,
    edit_cost,
    fingerprint,
    iter_refs,
    normalized_formula,
    parse_formula,
    render,
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
    generate_candidates,
    v4_scores,
)
from .workbook import CellKey, WorkbookModel


V6_MODEL_VERSION = "v6-semantic-r1"
V6_AGGREGATES = ("SUM", "AVERAGE", "MIN", "MAX")


def v6_default_parameters() -> dict[str, object]:
    """Exact preregistered V6 parameter contract."""
    return {
        "model_version": V6_MODEL_VERSION,
        "base_candidate_limit": 15,
        "semantic_candidate_limit": 25,
        "peer_radius": 5,
        "reference_quality_min": 0.80,
        "strong_support_min": 3,
        "strong_semantic_min": 0.60,
        "strong_margin_min": 0.20,
        "strong_source_categories_min": 2,
        "strong_delta_min": 0.05,
        "strong_irg_min": 2.0,
        "strong_global_harm_max": 0.05,
        "strong_insert_rank": 3,
        "moderate_support_min": 2,
        "moderate_semantic_min": 0.50,
        "moderate_margin_min": 0.10,
        "moderate_delta_min": 0.02,
        "moderate_irg_min": 1.0,
        "moderate_global_harm_max": 0.05,
        "moderate_insert_rank": 5,
        "scope_depth": 3,
        "scope_decay": 0.70,
        "side_effect_weight": 0.50,
        "semantic_energy_weight": 0.10,
        "promotion_limit_per_workbook": 1,
    }


@dataclass(frozen=True)
class SemanticEvidence:
    candidate: RepairCandidate
    family_support: float
    family_margin: float
    boundary_support: float
    boundary_margin: float
    direction_count: int
    support_count: int
    family_count: int = 0
    family_direction_count: int = 0
    boundary_count: int = 0
    boundary_direction_count: int = 0


def _walk(node: object) -> Iterable[object]:
    yield node
    if isinstance(node, Unary):
        yield from _walk(node.value)
    elif isinstance(node, Binary):
        yield from _walk(node.left)
        yield from _walk(node.right)
    elif isinstance(node, Func):
        for arg in node.args:
            yield from _walk(arg)


def relative_ast_signature(formula: str, anchor: str) -> str:
    """Return the relative AST signature used for formula-family auditing."""
    return fingerprint(parse_formula(formula), parse_address(anchor))


def _outer_family(formula: str, anchor: str) -> tuple[str, int, str]:
    node = parse_formula(formula)
    if isinstance(node, Func):
        outer = f"FUNC:{node.name}"
        argc = len(node.args)
    elif isinstance(node, Binary):
        outer = f"OP:{node.op}"
        argc = 2
    elif isinstance(node, Unary):
        outer = f"UNARY:{node.op}"
        argc = 1
    else:
        outer = type(node).__name__.upper()
        argc = 0
    return outer, argc, relative_ast_signature(formula, anchor)


def _family_class(formula: str) -> tuple[str, int]:
    node = parse_formula(formula)
    if isinstance(node, Func):
        return ("AGGREGATE" if node.name in V6_AGGREGATES else "FUNCTION", len(node.args))
    if isinstance(node, Binary):
        return ("BINARY", 2)
    if isinstance(node, Unary):
        return ("UNARY", 1)
    return (type(node).__name__.upper(), 0)


def _single_aggregate_range(formula: str) -> tuple[str, Range] | None:
    try:
        node = parse_formula(formula)
    except Exception:
        return None
    if (
        isinstance(node, Func)
        and node.name in V6_AGGREGATES
        and len(node.args) == 1
        and isinstance(node.args[0], Range)
    ):
        return node.name, node.args[0]
    return None


def _direction(target: CellKey, peer: CellKey) -> str:
    ta, pa = parse_address(target[1]), parse_address(peer[1])
    if ta.col == pa.col:
        return "up" if pa.row < ta.row else "down"
    return "left" if pa.col < ta.col else "right"


def semantic_peers(model: WorkbookModel, key: CellKey, radius: int = 5) -> list[tuple[CellKey, str]]:
    """Contiguous same-row/column formula peers, with an auditable direction."""
    target = parse_address(key[1])
    try:
        target_family = _family_class(model.formulas[key])
    except Exception:
        return []
    formula_set = set(model.formula_cells)
    peers: list[tuple[CellKey, str]] = []
    for drow, dcol, label in ((-1, 0, "up"), (1, 0, "down"), (0, -1, "left"), (0, 1, "right")):
        for distance in range(1, radius + 1):
            row, col = target.row + drow * distance, target.col + dcol * distance
            if row < 1 or col < 1:
                break
            from .a1 import num_to_col
            candidate = (key[0], f"{num_to_col(col)}{row}")
            if candidate not in formula_set:
                break
            try:
                if _family_class(model.formulas[candidate]) == target_family:
                    peers.append((candidate, label))
            except Exception:
                continue
    return peers


def _reference_quality(model: WorkbookModel, key: CellKey, formula: str) -> float:
    try:
        refs: list[CellKey] = []
        for item in iter_refs(parse_formula(formula)):
            if isinstance(item, Ref):
                refs.append((item.sheet or key[0], item.address.a1.replace("$", "")))
            elif isinstance(item, Range):
                sheet = item.start.sheet or item.end.sheet or key[0]
                refs.extend((sheet, address) for address in iter_rect(item.start.address, item.end.address))
        if not refs:
            return 1.0
        return sum(ref in model.cells or ref in model.formulas for ref in refs) / len(refs)
    except Exception:
        return 0.0


def _candidate_category(kinds: Sequence[str], sources: Sequence[str]) -> str:
    joined = " ".join((*kinds, *sources))
    if "range" in joined:
        return "range"
    if "aggregate_function" in joined:
        return "aggregate_function"
    if "operator" in joined:
        return "operator"
    if "peer" in joined or "family" in joined:
        return "peer_family"
    return "reference"


def semantic_candidates(
    model: WorkbookModel,
    key: CellKey,
    *,
    base_candidate_limit: int = 15,
    semantic_candidate_limit: int = 25,
    include_boundary: bool = True,
) -> list[SemanticEvidence]:
    """Merge frozen V4 repairs with peer-translated semantic proposals."""
    original = model.formulas[key]
    peers = semantic_peers(model, key, radius=5)
    translated: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for peer, direction in peers:
        try:
            candidate = translate_formula(model.formulas[peer], peer[1], key[1])
            parse_formula(candidate)
        except Exception:
            continue
        if normalized_formula(candidate) == normalized_formula(original):
            continue
        translated[normalized_formula(candidate)].append((candidate, direction, peer[0] + "!" + peer[1]))

    total_peers = max(1, len(peers))
    counts = Counter({norm: len(rows) for norm, rows in translated.items()})
    ordered_counts = sorted(counts.values(), reverse=True)
    second_count = ordered_counts[1] if len(ordered_counts) > 1 else 0
    boundary_counts: Counter[tuple[object, ...]] = Counter()
    boundary_by_norm: dict[str, tuple[object, ...]] = {}
    boundary_directions: dict[tuple[object, ...], set[str]] = defaultdict(set)
    boundary_ranges: dict[tuple[object, ...], Range] = {}
    for norm, rows in translated.items():
        parsed = _single_aggregate_range(rows[0][0])
        if not parsed:
            continue
        _, area = parsed
        key_tuple = (
            area.start.sheet, area.start.address.a1,
            area.end.sheet, area.end.address.a1,
            abs(area.end.address.row - area.start.address.row) + 1,
            abs(area.end.address.col - area.start.address.col) + 1,
        )
        boundary_by_norm[norm] = key_tuple
        boundary_ranges[key_tuple] = area
        boundary_counts[key_tuple] += len(rows)
        boundary_directions[key_tuple].update(row[1] for row in rows)
    boundary_total = sum(boundary_counts.values())
    ordered_boundary = sorted(boundary_counts.values(), reverse=True)
    second_boundary_count = ordered_boundary[1] if len(ordered_boundary) > 1 else 0

    merged: dict[str, dict[str, object]] = {}
    for item in generate_candidates(model, key, limit=base_candidate_limit):
        norm = normalized_formula(item.formula)
        merged[norm] = {
            "formula": item.formula,
            "support": item.support,
            "sources": set(item.sources),
            "kinds": set(item.edit_kinds),
            "quality": item.quality,
            "directions": set(),
            "family_directions": set(),
            "boundary_directions": set(),
            "family_support": 0.0,
            "family_margin": 0.0,
            "boundary_support": 0.0,
            "boundary_margin": 0.0,
            "boundary_count": 0,
        }

    original_range = _single_aggregate_range(original)
    if include_boundary and original_range and boundary_counts:
        modal_boundary, modal_count = max(boundary_counts.items(), key=lambda item: (item[1], str(item[0])))
        old_name, old_area = original_range
        modal_area = boundary_ranges[modal_boundary]
        boundary_formula = "=" + render(Func(old_name, (modal_area,)))
        if modal_count >= 3 and normalized_formula(boundary_formula) != normalized_formula(original):
            norm = normalized_formula(boundary_formula)
            merged[norm] = {
                "formula": boundary_formula,
                "support": 0,
                "sources": {"boundary_consensus", "boundary_semantic"},
                "kinds": {"range_boundary"},
                "quality": 0.0,
                "directions": set(boundary_directions[modal_boundary]),
                "family_directions": set(),
                "boundary_directions": set(boundary_directions[modal_boundary]),
                "family_support": counts.get(norm, 0) / total_peers,
                "family_margin": max(0.0, (counts.get(norm, 0) - second_count) / total_peers),
                "boundary_support": modal_count / max(1, boundary_total),
                "boundary_margin": max(0.0, (modal_count - second_boundary_count) / max(1, boundary_total)),
                "boundary_count": modal_count,
            }
    for norm, rows in translated.items():
        formula = sorted(row[0] for row in rows)[0]
        directions = {row[1] for row in rows}
        support = len(rows)
        entry = merged.setdefault(norm, {
            "formula": formula,
            "support": 0,
            "sources": set(),
            "kinds": set(),
            "quality": 0.0,
            "directions": set(),
            "family_directions": set(),
            "boundary_directions": set(),
            "family_support": 0.0,
            "family_margin": 0.0,
            "boundary_support": 0.0,
            "boundary_margin": 0.0,
            "boundary_count": 0,
        })
        entry["support"] = max(int(entry["support"]), support)
        entry["directions"].update(directions)
        entry["family_directions"].update(directions)
        entry["sources"].add("peer_translation")
        for direction in directions:
            entry["sources"].add(f"peer_{direction}")
        entry["kinds"].add("copy_pattern")
        entry["family_support"] = support / total_peers
        entry["family_margin"] = max(0.0, (support - second_count) / total_peers)
        try:
            candidate_range = _single_aggregate_range(formula)
            original_outer = _outer_family(original, key[1])[0]
            candidate_outer = _outer_family(formula, key[1])[0]
            if candidate_outer != original_outer:
                entry["kinds"].add("aggregate_function")
                entry["sources"].add("family_consensus")
            if include_boundary and original_range and candidate_range:
                old_name, old_range = original_range
                new_name, new_range = candidate_range
                boundary_vote = boundary_counts.get(boundary_by_norm.get(norm, ()), 0)
                if old_range != new_range and boundary_vote >= 3 and boundary_total:
                    entry["kinds"].add("range_boundary")
                    entry["sources"].add("boundary_consensus")
                    entry["boundary_support"] = boundary_vote / boundary_total
                    entry["boundary_margin"] = max(0.0, (boundary_vote - second_boundary_count) / boundary_total)
                    entry["boundary_count"] = boundary_vote
                    current_boundary_directions = boundary_directions.get(boundary_by_norm.get(norm, ()), set())
                    entry["directions"].update(current_boundary_directions)
                    entry["boundary_directions"].update(current_boundary_directions)
                if old_name != new_name:
                    entry["kinds"].add("aggregate_function")
        except Exception:
            pass

    ranked: list[SemanticEvidence] = []
    for entry in merged.values():
        formula = str(entry["formula"])
        ref_quality = _reference_quality(model, key, formula)
        if ref_quality < 0.80 or normalized_formula(formula) == normalized_formula(original):
            continue
        try:
            parse_formula(formula)
        except Exception:
            continue
        support = max(int(entry["support"]), int(entry["boundary_count"]))
        sources = tuple(sorted(entry["sources"]))
        kinds = tuple(sorted(entry["kinds"]))
        semantic = max(float(entry["family_support"]), float(entry["boundary_support"]))
        quality = min(1.0, 0.35 * semantic + 0.25 * ref_quality + 0.20 * min(1.0, support / 3) + 0.20 / (1 + edit_cost(original, formula)))
        candidate = RepairCandidate(
            formula=formula,
            support=support,
            sources=sources,
            edit_kinds=kinds,
            edit_cost=edit_cost(original, formula),
            reference_quality=ref_quality,
            quality=max(float(entry["quality"]), quality),
        )
        ranked.append(SemanticEvidence(
            candidate=candidate,
            family_support=float(entry["family_support"]),
            family_margin=float(entry["family_margin"]),
            boundary_support=float(entry["boundary_support"]),
            boundary_margin=float(entry["boundary_margin"]),
            direction_count=len(entry["directions"]),
            support_count=support,
            family_count=int(entry["support"]),
            family_direction_count=len(entry["family_directions"]),
            boundary_count=int(entry["boundary_count"]),
            boundary_direction_count=len(entry["boundary_directions"]),
        ))

    ranked.sort(key=lambda item: (
        -max(item.family_support, item.boundary_support),
        -item.support_count,
        -item.candidate.quality,
        item.candidate.edit_cost,
        item.candidate.formula,
    ))

    quotas = {
        "peer_family": 5,
        "aggregate_function": 4,
        "range": 8,
        "operator": 3,
        "reference": 5,
    }
    selected: list[SemanticEvidence] = []
    used: set[str] = set()
    for category, quota in quotas.items():
        for item in ranked:
            norm = normalized_formula(item.candidate.formula)
            if quota <= 0:
                break
            if norm in used or _candidate_category(item.candidate.edit_kinds, item.candidate.sources) != category:
                continue
            selected.append(item)
            used.add(norm)
            quota -= 1
    for item in ranked:
        if len(selected) >= semantic_candidate_limit:
            break
        norm = normalized_formula(item.candidate.formula)
        if norm not in used:
            selected.append(item)
            used.add(norm)
    return selected[:semantic_candidate_limit]


def _propagation_path(model: WorkbookModel, cell: CellKey) -> list[str]:
    graph = model.dependency_graph()
    for sink in graph.sinks(model.formula_cells):
        path = graph.shortest_path(cell, sink)
        if path and len(path) > 1:
            return [f"{sheet}!{address}" for sheet, address in path]
    return []


def _evaluate_cell(
    model: WorkbookModel,
    cell: CellKey,
    semantic: Sequence[SemanticEvidence],
    *,
    base_global_energy: float,
    base_maps: Mapping[str, Mapping[CellKey, float]],
) -> list[dict[str, object]]:
    graph = model.dependency_graph()
    scope = _v4_scope_weights(model, graph, cell, max_depth=3, decay=0.70)
    before, _ = _v4_local_energy(base_maps, scope)
    raw: list[dict[str, object]] = []
    for evidence in semantic:
        candidate = evidence.candidate
        global_after, _, maps_after = _energy(model, {cell: candidate.formula}, include_maps=True)
        local_after, _ = _v4_local_energy(maps_after, scope)
        gain, local_harm = _v4_bounded_change(before, local_after)
        _, global_harm = _v4_bounded_change(base_global_energy, global_after)
        raw.append({
            "semantic": evidence,
            "candidate": candidate,
            "local_after": local_after,
            "local_gain": gain,
            "local_harm": local_harm,
            "global_harm": global_harm,
        })
    return raw


def _effective_rows(
    raw: Sequence[Mapping[str, object]],
    variant: str,
    ablation: str | None,
) -> list[dict[str, object]]:
    calibrated: list[dict[str, object]] = []
    for original in raw:
        row = dict(original)
        semantic: SemanticEvidence = row["semantic"]  # type: ignore[assignment]
        candidate: RepairCandidate = row["candidate"]  # type: ignore[assignment]
        family_enabled = ablation != "no_ffc"
        boundary_eligible = (
            "boundary_semantic" in candidate.sources
            or "aggregate_function" not in candidate.edit_kinds
        )
        boundary_enabled = variant in {"b", "c"} and ablation != "no_bss" and boundary_eligible
        family_support = semantic.family_support if family_enabled else 0.0
        family_margin = semantic.family_margin if family_enabled and ablation != "no_uniqueness" else 0.0
        boundary_support = semantic.boundary_support if boundary_enabled else 0.0
        boundary_margin = semantic.boundary_margin if boundary_enabled and ablation != "no_uniqueness" else 0.0
        semantic_gain = 0.10 * max(
            family_support * family_margin,
            boundary_support * boundary_margin,
        )
        harm = max(float(row["local_harm"]), float(row["global_harm"]))
        delta = float(row["local_gain"]) + semantic_gain
        if ablation != "no_side_effect":
            delta -= 0.50 * harm
        row.update({
            "effective_family_support": family_support,
            "effective_family_margin": family_margin,
            "effective_boundary_support": boundary_support,
            "effective_boundary_margin": boundary_margin,
            "effective_semantic_strength": max(family_support, boundary_support),
            "effective_semantic_margin": max(family_margin, boundary_margin),
            "effective_support_count": max(
                semantic.family_count if family_enabled else 0,
                semantic.boundary_count if boundary_enabled else 0,
            ),
            "effective_direction_count": max(
                semantic.family_direction_count if family_enabled else 0,
                semantic.boundary_direction_count if boundary_enabled else 0,
            ),
            "semantic_energy_gain": semantic_gain,
            "delta": delta,
        })
        calibrated.append(row)
    for row in calibrated:
        controls = _v4_matched_controls(row["candidate"], calibrated)
        values = [float(item["delta"]) for item in controls]
        median = statistics.median(values) if values else 0.0
        mad = statistics.median(abs(value - median) for value in values) if values else 0.0
        row["control_count"] = len(controls)
        row["control_median"] = median
        row["control_mad"] = mad
        row["irg"] = (float(row["delta"]) - median) / max(0.01, 1.4826 * mad) if controls else 0.0
    return calibrated


def _classify(row: Mapping[str, object], variant: str, ablation: str | None = None) -> tuple[str, int]:
    candidate: RepairCandidate = row["candidate"]  # type: ignore[assignment]
    margin = float(row["effective_semantic_margin"])
    strength = float(row["effective_semantic_strength"])
    support_count = int(row["effective_support_count"])
    direction_count = int(row["effective_direction_count"])
    sources = {source.split("_")[0] if source.startswith("peer_") else source for source in candidate.sources}
    effective_delta = float(row["delta"])
    margin_strong_ok = margin >= 0.20 or ablation == "no_uniqueness"
    margin_moderate_ok = margin >= 0.10 or ablation == "no_uniqueness"
    harm_ok = float(row["global_harm"]) <= 0.05 or ablation == "no_side_effect"
    delta_strong_ok = effective_delta >= 0.05 or ablation in {"no_d", "semantics_only"}
    delta_moderate_ok = effective_delta >= 0.02 or ablation in {"no_d", "semantics_only"}
    irg_strong_ok = float(row["irg"]) >= 2.0 or ablation in {"no_irg", "semantics_only"}
    irg_moderate_ok = float(row["irg"]) >= 1.0 or ablation in {"no_irg", "semantics_only"}
    c_safe = (
        len(sources) >= 2
        and margin_strong_ok
        and harm_ok
    )
    strong = (
        support_count >= 3
        and strength >= 0.60
        and len(sources) >= 2
        and margin_strong_ok
        and delta_strong_ok
        and irg_strong_ok
        and harm_ok
        and (variant != "c" or c_safe)
    )
    directional_support_ok = support_count >= 3 or (
        support_count >= 2 and direction_count >= 2
    )
    moderate = (
        support_count >= 2
        and directional_support_ok
        and strength >= 0.50
        and margin_moderate_ok
        and delta_moderate_ok
        and irg_moderate_ok
        and harm_ok
        and (variant != "c" or len(sources) >= 2)
    )
    if strong:
        return "strong", 3
    if moderate:
        return "moderate", 5
    return "none", 0


def _promotion_key(
    row: Mapping[str, object], tier: str, v4_rank: int, ablation: str | None = None,
) -> tuple[object, ...]:
    candidate: RepairCandidate = row["candidate"]  # type: ignore[assignment]
    return (
        2 if tier == "strong" else 1,
        int(row["effective_support_count"]),
        0.0 if ablation == "no_uniqueness" else float(row["effective_semantic_margin"]),
        0.0 if ablation == "no_d" else float(row["delta"]),
        0.0 if ablation == "no_irg" else float(row["irg"]),
        candidate.quality,
        -v4_rank,
    )


def _select_promotion(promotable, *, variant: str, ablation: str | None = None):
    """Select one promotion and reject exact evidence ties in safe V6-C."""
    if not promotable:
        return None
    ordered = sorted(promotable, key=lambda value: value[0], reverse=True)
    if variant == "c" and ablation != "no_uniqueness" and len(ordered) > 1 and ordered[0][0][:5] == ordered[1][0][:5]:
        return None
    return ordered[0]


def _prepare_v6(model: WorkbookModel, base_candidate_limit: int, semantic_candidate_limit: int):
    """Compute label-free V4 and candidate interventions once per workbook."""
    cache = getattr(model, "_fg_v6_preparation_cache", None)
    key = (base_candidate_limit, semantic_candidate_limit)
    if cache is not None and key in cache:
        return cache[key]
    started = time.perf_counter()
    base = v4_scores(model, candidate_limit=base_candidate_limit)
    v4_rank = {item.cell: rank for rank, item in enumerate(base, 1)}
    base_global_energy, _, base_maps = _energy(model, include_maps=True)
    portfolios: dict[CellKey, list[dict[str, object]]] = {}
    effects_by_cell: dict[CellKey, list[dict[str, object]]] = {}
    for item in base:
        semantic = semantic_candidates(
            model,
            item.cell,
            base_candidate_limit=base_candidate_limit,
            semantic_candidate_limit=semantic_candidate_limit,
            include_boundary=True,
        )
        portfolios[item.cell] = [
            {
                "formula": entry.candidate.formula,
                "sources": list(entry.candidate.sources),
                "edit_kinds": list(entry.candidate.edit_kinds),
                "reference_quality": entry.candidate.reference_quality,
                "support": entry.support_count,
                "family_support": entry.family_support,
                "boundary_support": entry.boundary_support,
                "boundary_count": entry.boundary_count,
            }
            for entry in semantic
        ]
        if any(entry.support_count >= 2 for entry in semantic):
            effects_by_cell[item.cell] = _evaluate_cell(
                model,
                item.cell,
                semantic,
                base_global_energy=base_global_energy,
                base_maps=base_maps,
            )
    prepared = {
        "base": base,
        "v4_rank": v4_rank,
        "portfolios": portfolios,
        "effects_by_cell": effects_by_cell,
        "preparation_seconds": time.perf_counter() - started,
    }
    if cache is None:
        cache = {}
        setattr(model, "_fg_v6_preparation_cache", cache)
    cache[key] = prepared
    return prepared


def v6_prepared_v4_scores(model: WorkbookModel, *, candidate_limit: int = 15):
    """Return the exact V4 ranking already computed for a V6 bundle."""
    return _prepare_v6(model, candidate_limit, 25)["base"]


def _v6_scores_impl(
    model: WorkbookModel,
    *,
    variant: str = "c",
    base_candidate_limit: int = 15,
    semantic_candidate_limit: int = 25,
    ablation: str | None = None,
) -> list[LocalizationResult]:
    """Return a complete V6 ranking without accepting any label information."""
    variant = variant.lower()
    if variant not in {"a", "b", "c"}:
        raise ValueError("variant must be one of: a, b, c")
    prepared = _prepare_v6(model, base_candidate_limit, semantic_candidate_limit)
    ranking_started = time.perf_counter()
    base = prepared["base"]
    if ablation == "v4_only":
        return base
    v4_rank = prepared["v4_rank"]

    best_by_cell: dict[CellKey, dict[str, object]] = {}
    portfolios: dict[CellKey, list[dict[str, object]]] = prepared["portfolios"]
    promotable: list[tuple[tuple[object, ...], CellKey, dict[str, object], str, int]] = []
    for item in base:
        raw_rows = prepared["effects_by_cell"].get(item.cell, [])
        rows = _effective_rows(raw_rows, variant, ablation)
        if not rows:
            continue
        classified: list[tuple[tuple[object, ...], dict[str, object], str, int]] = []
        for row in rows:
            tier, target = _classify(row, variant, ablation)
            classified.append((_promotion_key(row, tier, v4_rank[item.cell], ablation), row, tier, target))
        classified.sort(key=lambda value: value[0], reverse=True)
        _, best, tier, target = classified[0]
        best_by_cell[item.cell] = best
        if tier != "none" and v4_rank[item.cell] > target:
            promotable.append((_promotion_key(best, tier, v4_rank[item.cell], ablation), item.cell, best, tier, target))

    selected: tuple[tuple[object, ...], CellKey, dict[str, object], str, int] | None = _select_promotion(
        promotable, variant=variant, ablation=ablation
    )

    ordered_cells = [item.cell for item in base]
    if ablation == "semantics_only":
        def semantic_only_key(cell):
            row = best_by_cell.get(cell)
            if not row:
                return (0.0, 0.0, 0, 0.0, cell)
            candidate: RepairCandidate = row["candidate"]  # type: ignore[assignment]
            return (
                -float(row["effective_semantic_strength"]),
                -float(row["effective_semantic_margin"]),
                -int(row["effective_support_count"]),
                -candidate.quality,
                cell,
            )
        ordered_cells = sorted(model.formula_cells, key=semantic_only_key)
        selected = None
    elif selected is not None:
        _, promoted_cell, _, _, target = selected
        ordered_cells.remove(promoted_cell)
        ordered_cells.insert(min(target - 1, len(ordered_cells)), promoted_cell)
    v6_rank = {cell: rank for rank, cell in enumerate(ordered_cells, 1)}
    base_lookup = {item.cell: item for item in base}
    elapsed = float(prepared["preparation_seconds"]) + (time.perf_counter() - ranking_started)
    results: list[LocalizationResult] = []
    selected_cell = selected[1] if selected else None
    selected_tier = selected[3] if selected else "none"
    selected_target = selected[4] if selected else 0
    for cell in ordered_cells:
        base_item = base_lookup[cell]
        row = best_by_cell.get(cell)
        semantic = row["semantic"] if row else None
        candidate = row["candidate"] if row else None
        promoted = cell == selected_cell
        evidence = dict(base_item.evidence)
        evidence.update({
            "model_version": V6_MODEL_VERSION,
            "v6_variant": variant,
            "v4_rank": v4_rank[cell],
            "v6_rank": v6_rank[cell],
            "semantic_tier": selected_tier if promoted else "none",
            "family_support": float(row["effective_family_support"]) if row else 0.0,
            "family_margin": float(row["effective_family_margin"]) if row else 0.0,
            "boundary_support": float(row["effective_boundary_support"]) if row else 0.0,
            "boundary_margin": float(row["effective_boundary_margin"]) if row else 0.0,
            "candidate_formula": candidate.formula if candidate else (base_item.candidate_formula or ""),
            "candidate_portfolio": portfolios.get(cell, []),
            "candidate_sources": ",".join(candidate.sources) if candidate else "",
            "candidate_edit_kinds": ",".join(candidate.edit_kinds) if candidate else "",
            "candidate_reference_quality": candidate.reference_quality if candidate else 0.0,
            "semantic_energy_gain": float(row["semantic_energy_gain"]) if row else 0.0,
            "counterfactual_delta": float(row["delta"]) if row else 0.0,
            "counterfactual_irg": float(row["irg"]) if row else 0.0,
            "global_harm": float(row["global_harm"]) if row else 0.0,
            "promotion_target": selected_target if promoted else 0,
            "promotion_reason": f"{selected_tier}_semantic_counterfactual" if promoted else "not_promoted",
            "propagation_path": _propagation_path(model, cell),
            "localization_seconds": elapsed,
        })
        results.append(LocalizationResult(
            cell=cell,
            score=float(len(ordered_cells) - v6_rank[cell] + 1),
            candidate_formula=candidate.formula if candidate else base_item.candidate_formula,
            evidence=evidence,
        ))
    return results


def v6_scores(
    model: WorkbookModel,
    *,
    variant: str = "c",
    base_candidate_limit: int = 15,
    semantic_candidate_limit: int = 25,
) -> list[LocalizationResult]:
    """Public, label-free V6 interface fixed by the preregistration."""
    return _v6_scores_impl(
        model,
        variant=variant,
        base_candidate_limit=base_candidate_limit,
        semantic_candidate_limit=semantic_candidate_limit,
    )


def v6_ablation_scores(
    model: WorkbookModel,
    ablation: str,
    *,
    variant: str = "c",
) -> list[LocalizationResult]:
    """Internal fixed ablations; not part of the public localization API."""
    allowed = {
        "no_ffc", "no_bss", "no_d", "no_irg", "no_side_effect",
        "no_uniqueness", "v4_only", "semantics_only",
    }
    if ablation not in allowed:
        raise ValueError(f"Unknown V6 ablation: {ablation}")
    if variant not in {"a", "b", "c"}:
        raise ValueError(f"Unknown V6 variant: {variant}")
    return _v6_scores_impl(model, variant=variant, ablation=ablation)
