"""Formula families, baseline scores, counterfactual interventions, and GIR."""

from __future__ import annotations

import hashlib
import math
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .a1 import iter_rect, num_to_col, parse_address
from .formula import (
    Range,
    Ref,
    Func,
    Binary,
    edit_cost,
    iter_refs,
    normalized_formula,
    parse_formula,
    small_edit_candidates_with_kinds,
    translate_formula,
)
from .workbook import CellKey, DependencyGraph, WorkbookModel


@dataclass
class LocalizationResult:
    cell: CellKey
    score: float
    candidate_formula: str | None = None
    evidence: dict[str, float | int | str] = field(default_factory=dict)

    @property
    def cell_label(self) -> str:
        return f"{self.cell[0]}!{self.cell[1]}"


@dataclass(frozen=True)
class RepairCandidate:
    formula: str
    support: int
    sources: tuple[str, ...]
    edit_kinds: tuple[str, ...]
    edit_cost: float
    reference_quality: float
    quality: float

    def __iter__(self):
        """Preserve the historical ``formula, support`` unpacking interface."""
        yield self.formula
        yield self.support


def _coordinate(key: CellKey):
    addr = parse_address(key[1])
    return key[0], addr.row, addr.col


def _peers(model: WorkbookModel, key: CellKey, radius: int = 5) -> list[CellKey]:
    cache = getattr(model, "_fg_peer_cache", None)
    if cache is None:
        cache = {}
        setattr(model, "_fg_peer_cache", cache)
    cache_key = (key, radius)
    if cache_key in cache:
        return cache[cache_key]
    sheet, row, col = _coordinate(key)
    same_col: list[tuple[int, CellKey]] = []
    same_row: list[tuple[int, CellKey]] = []
    formula_set = set(model.formula_cells)
    column_name = num_to_col(col)
    active_up = True
    active_down = True
    for delta in range(1, radius + 1):
        if active_up:
            candidate = (sheet, f"{column_name}{row - delta}") if row - delta >= 1 else None
            if candidate in formula_set:
                same_col.append((delta, candidate))
            else:
                active_up = False
        if active_down:
            candidate = (sheet, f"{column_name}{row + delta}")
            if candidate in formula_set:
                same_col.append((delta, candidate))
            else:
                active_down = False
        if not active_up and not active_down:
            break
    for other in model.formula_cells:
        if other == key:
            continue
        osheet, orow, ocol = _coordinate(other)
        if osheet == sheet and orow == row and abs(ocol - col) <= 3:
            same_row.append((abs(ocol - col), other))
    same_col.sort()
    same_row.sort()
    column_peers = [item for _, item in same_col]
    row_peers = [item for _, item in same_row]

    def orientation_score(peers: list[CellKey]) -> tuple[int, float, int]:
        translated: list[str] = []
        for peer in peers:
            try:
                translated.append(translate_formula(model.formulas[peer], peer[1], key[1]))
            except Exception:
                continue
        if not translated:
            return 0, float("-inf"), 0
        counts = Counter(normalized_formula(item) for item in translated)
        consensus = max(counts.values())
        closest = min(
            edit_cost(model.formulas[key], item)
            for item in translated
            if counts[normalized_formula(item)] == consensus
        )
        return consensus, -closest, len(translated)

    column_score = orientation_score(column_peers)
    row_score = orientation_score(row_peers)
    if column_score[0] >= 2 and row_score[0] >= 2:
        # When both directions form a copy family, prefer the family requiring
        # the smaller edit from the current formula; use vote count only as a
        # tie-breaker.  This avoids swallowing a short horizontal block into a
        # longer but semantically unrelated vertical region.
        column_choice = (column_score[1], column_score[0], column_score[2])
        row_choice = (row_score[1], row_score[0], row_score[2])
        selected = column_peers if column_choice >= row_choice else row_peers
    elif column_score[0] >= 2:
        selected = column_peers
    elif row_score[0] >= 2:
        selected = row_peers
    else:
        selected = column_peers + row_peers
    result = list(dict.fromkeys(selected))
    cache[cache_key] = result
    return result


def formula_anomaly_scores(model: WorkbookModel, overrides: Mapping[CellKey, str] | None = None):
    fps = model.fingerprints(overrides)
    coordinate_lookup = {_coordinate(cell): cell for cell in model.formula_cells}
    scores: dict[CellKey, float] = {}
    for key in model.formula_cells:
        peer_keys = _peers(model, key)
        sample = [key] + peer_keys
        counts = Counter(fps[k] for k in sample)
        dominant_count = max(counts.values(), default=0)
        if len(sample) <= 1 or dominant_count < 2:
            family_score = 0.0
        elif counts[fps[key]] < dominant_count:
            family_score = dominant_count / len(sample)
        else:
            family_score = max(0.0, 1.0 - counts[fps[key]] / len(sample))
        sheet, row, col = _coordinate(key)
        immediate = [
            candidate for candidate in (
                coordinate_lookup.get((sheet, row - 1, col)),
                coordinate_lookup.get((sheet, row + 1, col)),
            )
            if candidate is not None
        ]
        if len(immediate) == 2 and fps[immediate[0]] == fps[immediate[1]] != fps[key]:
            immediate_score = 1.0
        elif immediate and any(fps[other] != fps[key] for other in immediate):
            immediate_score = 0.35
        else:
            immediate_score = 0.0
        scores[key] = max(family_score, immediate_score)
    return scores


def excel_like_scores(model: WorkbookModel, overrides: Mapping[CellKey, str] | None = None):
    fps = model.fingerprints(overrides)
    lookup = {(_coordinate(k)): k for k in model.formula_cells}
    result: dict[CellKey, float] = {}
    for key in model.formula_cells:
        sheet, row, col = _coordinate(key)
        above = lookup.get((sheet, row - 1, col))
        below = lookup.get((sheet, row + 1, col))
        score = 0.0
        if above and below and fps[above] == fps[below] != fps[key]:
            score = 1.0
        elif above and fps[above] != fps[key]:
            score = 0.35
        elif below and fps[below] != fps[key]:
            score = 0.35
        result[key] = score
    return result


def excelint_like_scores(model: WorkbookModel, overrides: Mapping[CellKey, str] | None = None):
    fps = model.fingerprints(overrides)
    result: dict[CellKey, float] = {}
    for key in model.formula_cells:
        sample = [key] + _peers(model, key, radius=8)
        counts = Counter(fps[k] for k in sample)
        distinct = max(1, len(counts))
        probability = (counts[fps[key]] + 1.0) / (len(sample) + distinct)
        surprise = -math.log2(probability)
        support = 1.0 - counts[fps[key]] / max(1, len(sample))
        result[key] = surprise * (0.5 + support)
    return result


def _median_abs_deviation(values: Sequence[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    median = statistics.median(values)
    mad = statistics.median(abs(v - median) for v in values)
    return median, mad


def constraint_residual_scores(
    model: WorkbookModel,
    overrides: Mapping[CellKey, str] | None = None,
    evaluation: tuple[Mapping[CellKey, object], Mapping[CellKey, str]] | None = None,
):
    """Score internal balance checks, reusing an existing workbook evaluation when supplied."""
    values, errors = evaluation if evaluation is not None else model.evaluate(overrides)
    scores: dict[CellKey, float] = {}
    for key in model.formula_cells:
        formula = (overrides or {}).get(key, model.formulas[key])
        try:
            node = parse_formula(formula)
        except Exception:
            continue
        if not isinstance(node, Binary) or node.op != "-":
            continue
        if not isinstance(node.left, Ref) or not isinstance(node.right, Ref):
            continue
        left_key = (node.left.sheet or key[0], node.left.address.a1.replace("$", ""))
        right_key = (node.right.sheet or key[0], node.right.address.a1.replace("$", ""))
        if key in errors or left_key in errors or right_key in errors:
            scores[key] = 1.0
            continue
        try:
            left_value = float(values[left_key])
            right_value = float(values[right_key])
        except (KeyError, TypeError, ValueError):
            scores[key] = 1.0
            continue
        relative_residual = abs(left_value - right_value) / max(1.0, abs(left_value), abs(right_value))
        scores[key] = min(1.0, 10.0 * relative_residual)
    return scores


def _behavior_anomaly_bundle(
    model: WorkbookModel,
    overrides: Mapping[CellKey, str] | None = None,
) -> tuple[dict[CellKey, float], dict[CellKey, float], dict[CellKey, float]]:
    """Return public, general, and constraint scores from one workbook evaluation."""
    fps = model.fingerprints(overrides)
    values, errors = model.evaluate(overrides)
    groups: dict[tuple[str, int, str], list[CellKey]] = defaultdict(list)
    for key in model.formula_cells:
        _, _, col = _coordinate(key)
        groups[(key[0], col, fps[key])].append(key)
    scores = {key: 0.0 for key in model.formula_cells}
    for group in groups.values():
        numeric_values: list[tuple[CellKey, float]] = []
        for key in group:
            if key in errors:
                scores[key] = 1.0
                continue
            try:
                numeric_values.append((key, float(values[key])))
            except (KeyError, TypeError, ValueError):
                pass
        if len(numeric_values) < 3:
            continue
        median, mad = _median_abs_deviation([v for _, v in numeric_values])
        scale = max(1e-9, 1.4826 * mad, abs(median) * 0.02)
        for key, value in numeric_values:
            z = abs(value - median) / scale
            scores[key] = min(1.0, z / 6.0)

    # Aggregate summaries over the same range form a weak semantic checksum.
    # Duplicating MIN/MAX while removing its counterpart is suspicious even
    # when every formula still returns a valid number.
    aggregate_groups: dict[tuple[str, str, str], list[tuple[CellKey, str]]] = defaultdict(list)
    aggregate_columns: dict[tuple[str, int], list[tuple[CellKey, tuple[str, str]]]] = defaultdict(list)
    for key in model.formula_cells:
        formula = (overrides or {}).get(key, model.formulas[key])
        try:
            node = parse_formula(formula)
        except Exception:
            continue
        if not isinstance(node, Func) or node.name not in {"SUM", "AVERAGE", "MIN", "MAX"} or len(node.args) != 1:
            continue
        argument = node.args[0]
        if not isinstance(argument, Range):
            continue
        sheet = argument.start.sheet or argument.end.sheet or key[0]
        range_key = (argument.start.address.a1, argument.end.address.a1)
        aggregate_groups[(sheet, *range_key)].append((key, node.name))
        aggregate_columns[(key[0], _coordinate(key)[2])].append((key, range_key))
    for group in aggregate_groups.values():
        if len(group) < 3:
            continue
        name_counts = Counter(name for _, name in group)
        for key, name in group:
            if name_counts[name] > 1:
                scores[key] = max(scores[key], min(1.0, name_counts[name] / len(group) + 0.5))
    for group in aggregate_columns.values():
        if len(group) < 3:
            continue
        range_counts = Counter(range_key for _, range_key in group)
        dominant_range, dominant_count = range_counts.most_common(1)[0]
        if dominant_count < 2:
            continue
        for key, range_key in group:
            if range_key != dominant_range:
                scores[key] = 1.0

    # Balance/check cells provide an internal invariant without an external
    # answer key.  Keep them visible to the behavior-only baseline as well.
    general_scores = scores
    constraint_scores = constraint_residual_scores(model, overrides, (values, errors))
    combined_scores = dict(general_scores)
    for key, score in constraint_scores.items():
        combined_scores[key] = max(combined_scores[key], score)
    return combined_scores, general_scores, constraint_scores


def behavior_anomaly_scores(model: WorkbookModel, overrides: Mapping[CellKey, str] | None = None):
    scores, _, _ = _behavior_anomaly_bundle(model, overrides)
    return scores


def graph_anomaly_scores(model: WorkbookModel, overrides: Mapping[CellKey, str] | None = None):
    graph = model.dependency_graph(overrides)
    coordinate_lookup = {_coordinate(key): key for key in model.formula_cells}
    features: dict[CellKey, tuple[float, float]] = {}
    for key in model.formula_cells:
        features[key] = (float(len(graph.precedents.get(key, ()))), float(len(graph.dependents.get(key, ()))))
    result: dict[CellKey, float] = {}
    for key in model.formula_cells:
        peer_keys = _peers(model, key)
        if len(peer_keys) < 2:
            result[key] = 0.0
            continue
        indegrees = [features[p][0] for p in peer_keys]
        outdegrees = [features[p][1] for p in peer_keys]
        med_in = statistics.median(indegrees)
        med_out = statistics.median(outdegrees)
        own_in, own_out = features[key]
        in_dev = abs(own_in - med_in) / max(1.0, med_in)
        out_dev = abs(own_out - med_out) / max(1.0, med_out)
        result[key] = min(1.0, 0.7 * in_dev + 0.3 * out_dev)
        sheet, row, col = _coordinate(key)
        if row > 1:
            previous = coordinate_lookup.get((sheet, row - 1, col))
            if previous:
                formula = (overrides or {}).get(key, model.formulas[key])
                try:
                    direct_refs = [item for item in iter_refs(parse_formula(formula)) if isinstance(item, Ref)]
                except Exception:
                    direct_refs = []
                same_column_older = {
                    (item.sheet or sheet, item.address.a1.replace("$", ""))
                    for item in direct_refs
                    if (item.sheet or sheet) == sheet and item.address.col == col and item.address.row < row - 1
                }
                direct_keys = {(item.sheet or sheet, item.address.a1.replace("$", "")) for item in direct_refs}
                if same_column_older and previous not in direct_keys:
                    result[key] = 1.0
    return result


def _energy(model: WorkbookModel, overrides: Mapping[CellKey, str] | None = None,
            weights=(0.45, 0.25, 0.30), include_maps: bool = False):
    fa = formula_anomaly_scores(model, overrides)
    ga = graph_anomaly_scores(model, overrides)
    _, ba_general, ca = _behavior_anomaly_bundle(model, overrides)
    n = max(1, len(model.formula_cells))
    behavior_general = sum(ba_general.values()) / n
    constraint_energy = sum(ca.values()) / max(1, len(ca))
    components = {
        "formula": sum(fa.values()) / n,
        "graph": sum(ga.values()) / n,
        "behavior": 0.25 * behavior_general + 0.75 * constraint_energy,
        "behavior_general": behavior_general,
        "constraint": constraint_energy,
    }
    total = weights[0] * components["formula"] + weights[1] * components["graph"] + weights[2] * components["behavior"]
    if include_maps:
        return total, components, {
            "formula": fa,
            "graph": ga,
            "behavior_general": ba_general,
            "constraint": ca,
        }
    return total, components


def generate_candidates(model: WorkbookModel, key: CellKey, limit: int = 10) -> list[RepairCandidate]:
    original = model.formulas[key]
    support: Counter[str] = Counter()
    sources: dict[str, set[str]] = defaultdict(set)
    edit_kinds: dict[str, set[str]] = defaultdict(set)
    peer_candidates: Counter[str] = Counter()
    for peer in _peers(model, key, radius=2):
        try:
            candidate = translate_formula(model.formulas[peer], peer[1], key[1])
        except Exception:
            continue
        if normalized_formula(candidate) != normalized_formula(original):
            peer_candidates[candidate] += 1
    for candidate, peer_support in peer_candidates.items():
        if peer_support >= 2:
            support[candidate] += peer_support
            sources[candidate].add("peer_translation")
            edit_kinds[candidate].add("copy_pattern")
    for candidate, kinds in small_edit_candidates_with_kinds(original):
        support[candidate] += 1
        sources[candidate].add("bounded_edit")
        edit_kinds[candidate].update(kinds)

    def reference_quality(candidate: str) -> float:
        try:
            refs = []
            for item in iter_refs(parse_formula(candidate)):
                if isinstance(item, Ref):
                    refs.append((item.sheet or key[0], item.address.a1.replace("$", "")))
                elif isinstance(item, Range):
                    sheet = item.start.sheet or item.end.sheet or key[0]
                    refs.extend((sheet, address) for address in iter_rect(item.start.address, item.end.address))
            if not refs:
                return 1.0
            populated = sum(1 for ref in refs if ref in model.cells or ref in model.formulas)
            return populated / len(refs)
        except Exception:
            return 0.0

    valid = []
    for candidate in support:
        quality = reference_quality(candidate)
        if quality < 0.80:
            continue
        try:
            parse_formula(candidate)
        except Exception:
            continue
        valid.append((candidate, quality))
    max_support = max((support[candidate] for candidate, _ in valid), default=1)
    ranked: list[RepairCandidate] = []
    for candidate, ref_quality in valid:
        cost = edit_cost(original, candidate)
        support_quality = support[candidate] / max_support
        kind_prior = max(
            ({
                "copy_pattern": 1.00 if support[candidate] >= 2 else 0.60,
                "copy_offset": 1.00,
                "copy_offset_row": 1.00,
                "parameter_anchor": 1.00,
                "range_boundary_row": 0.98,
                "range_boundary_end_row": 1.00,
                "range_boundary_end_col": 1.00,
                "operator": 0.95,
                "aggregate_function": 0.95,
                "range_boundary": 0.90,
                "reference_shift": 0.85,
                "absolute_reference": 0.75,
            }.get(kind, 0.50) for kind in edit_kinds[candidate]),
            default=0.50,
        )
        cost_quality = 1.0 / (1.0 + cost)
        candidate_quality = min(
            1.0,
            0.40 * support_quality + 0.30 * ref_quality + 0.20 * kind_prior + 0.10 * cost_quality,
        )
        ranked.append(RepairCandidate(
            formula=candidate,
            support=support[candidate],
            sources=tuple(sorted(sources[candidate])),
            edit_kinds=tuple(sorted(edit_kinds[candidate])),
            edit_cost=cost,
            reference_quality=ref_quality,
            quality=candidate_quality,
        ))
    ranked.sort(key=lambda item: (-item.quality, -item.support, item.edit_cost, item.formula))
    if limit < 12 or len(ranked) <= limit:
        return ranked[:limit]

    # Preserve edit-family diversity in the bounded Top-15.  Without a small
    # portfolio, numerous operator/reference variants can crowd out an entire
    # plausible error class before counterfactual evaluation begins.
    quotas = (
        ("copy_offset_row", 2),
        ("range_boundary_end_row", 2),
        ("range_boundary_end_col", 2),
        ("operator", 3),
        ("aggregate_function", 3),
        ("parameter_anchor", 2),
    )
    selected: list[RepairCandidate] = []
    selected_formulas: set[str] = set()
    for kind, quota in quotas:
        for item in ranked:
            if len(selected) >= limit or quota <= 0:
                break
            if item.formula in selected_formulas or kind not in item.edit_kinds:
                continue
            selected.append(item)
            selected_formulas.add(item.formula)
            quota -= 1
    for item in ranked:
        if len(selected) >= limit:
            break
        if item.formula not in selected_formulas:
            selected.append(item)
            selected_formulas.add(item.formula)
    return selected


def warder_like_scores(model: WorkbookModel):
    fps = model.fingerprints()
    scores: dict[CellKey, float] = {}
    repairs: dict[CellKey, str | None] = {}
    for key in model.formula_cells:
        candidates = generate_candidates(model, key, limit=10)
        peer_fps = Counter(fps[p] for p in _peers(model, key))
        best_score, best_formula = 0.0, None
        for repair_candidate in candidates:
            candidate, support = repair_candidate
            try:
                candidate_fp = model.fingerprints({key: candidate})[key]
            except Exception:
                continue
            score = peer_fps[candidate_fp] * support / (1.0 + edit_cost(model.formulas[key], candidate))
            if score > best_score:
                best_score, best_formula = score, candidate
        scores[key] = best_score
        repairs[key] = best_formula
    return scores, repairs


def gir_scores(model: WorkbookModel, *, candidate_limit=15, weights=(0.45, 0.25, 0.30),
               gir_weights=(0.35, 0.50, 0.10, 0.05), use_influence=True,
               use_intervention=True, max_intervention_cells=50):
    start = time.perf_counter()
    graph = model.dependency_graph()
    base_energy, base_components = _energy(model, weights=weights)
    formula_scores = formula_anomaly_scores(model)
    graph_scores = graph_anomaly_scores(model)
    behavior_scores = behavior_anomaly_scores(model)
    prior_scores = {
        key: (
            weights[0] * formula_scores[key]
            + weights[1] * graph_scores[key]
            + weights[2] * behavior_scores[key]
        )
        for key in model.formula_cells
    }
    # Full counterfactual evaluation is reserved for the most suspicious cells.
    # This makes the method usable on large workbooks while still returning a
    # complete ranking for every formula cell.
    if len(model.formula_cells) <= max_intervention_cells:
        intervention_cells = set(model.formula_cells)
    else:
        intervention_cells = set(sorted(
            model.formula_cells,
            key=lambda key: (-prior_scores[key], key),
        )[:max_intervention_cells])
    descendant_counts = {key: len(graph.descendants(key)) for key in intervention_cells}
    max_desc = max(descendant_counts.values(), default=1)
    formula_set = set(model.formula_cells)

    def block_boundary_factor(key: CellKey) -> float:
        sheet, row, col = _coordinate(key)
        column = num_to_col(col)
        above = (sheet, f"{column}{row - 1}") if row > 1 else None
        below = (sheet, f"{column}{row + 1}")
        below_two = (sheet, f"{column}{row + 2}")
        # The first seed of a recurrence block commonly has a different
        # formula shape and graph degree from the repeated rows below it.
        if above not in formula_set and below in formula_set and below_two in formula_set:
            return 0.25
        return 1.0

    results: list[LocalizationResult] = []

    for key in model.formula_cells:
        descendants = descendant_counts.get(key, 0)
        influence = 0.0
        if use_influence and key in intervention_cells:
            influence = math.log1p(descendants) / max(1e-9, math.log1p(max_desc))
        influence_factor = 1.0 if not use_influence else 0.25 + 0.75 * influence
        boundary_factor = block_boundary_factor(key)
        prior_responsibility = prior_scores[key] * influence_factor * boundary_factor
        best_score = gir_weights[0] * prior_responsibility
        best_candidate = None
        best_delta = 0.0
        best_delta_normalized = 0.0
        best_quality = 0.0
        best_support = 0
        best_edit_kind = ""
        best_candidate_source = ""
        best_components: dict[str, float] = {}
        candidate_pool: list[RepairCandidate] = []
        if use_intervention and key in intervention_cells:
            candidate_pool = generate_candidates(model, key, candidate_limit)
            for repair_candidate in candidate_pool:
                candidate, support = repair_candidate
                candidate_energy, candidate_components = _energy(model, {key: candidate}, weights=weights)
                delta = base_energy - candidate_energy
                delta_normalized = max(0.0, delta) / max(1e-9, base_energy)
                delta_responsibility = delta_normalized * influence_factor
                quality_responsibility = repair_candidate.quality * influence_factor if delta_normalized > 0 else 0.0
                score = (
                    gir_weights[0] * prior_responsibility
                    + gir_weights[1] * delta_responsibility
                    + gir_weights[2] * delta_normalized * influence
                    + gir_weights[3] * quality_responsibility
                )
                if score > best_score:
                    best_score = score
                    best_candidate = candidate
                    best_delta = delta
                    best_delta_normalized = delta_normalized
                    best_quality = repair_candidate.quality
                    best_support = support
                    best_edit_kind = ",".join(repair_candidate.edit_kinds)
                    best_candidate_source = ",".join(repair_candidate.sources)
                    best_components = candidate_components
        if use_intervention and candidate_pool and best_candidate is None:
            fallback = max(candidate_pool, key=lambda item: (item.support, item.quality, -item.edit_cost, item.formula))
            best_candidate = fallback.formula
            best_quality = fallback.quality
            best_support = fallback.support
            best_edit_kind = ",".join(fallback.edit_kinds)
            best_candidate_source = ",".join(fallback.sources)
        elif not use_intervention:
            candidates = generate_candidates(model, key, candidate_limit)
            if candidates:
                best_candidate = candidates[0].formula
                best_quality = candidates[0].quality
                best_support = candidates[0].support
                best_edit_kind = ",".join(candidates[0].edit_kinds)
                best_candidate_source = ",".join(candidates[0].sources)
                best_score += gir_weights[3] * best_quality
        results.append(LocalizationResult(
            cell=key,
            score=best_score,
            candidate_formula=best_candidate,
            evidence={
                "formula_anomaly": formula_scores[key],
                "graph_anomaly": graph_scores[key],
                "behavior_anomaly": behavior_scores[key],
                "prior_score": prior_scores[key],
                "prior_responsibility": prior_responsibility,
                "rootness_factor": influence_factor,
                "block_boundary_factor": boundary_factor,
                "descendants": descendants,
                "influence": influence,
                "base_energy": base_energy,
                "delta_energy": best_delta,
                "delta_energy_normalized": best_delta_normalized,
                "delta_responsibility": best_delta_normalized * (1.0 if not use_influence else 0.25 + 0.75 * influence),
                "candidate_quality": best_quality,
                "candidate_quality_responsibility": (
                    best_quality * (1.0 if not use_influence else 0.25 + 0.75 * influence)
                    if best_delta_normalized > 0 else 0.0
                ),
                "candidate_support": best_support,
                "candidate_edit_kind": best_edit_kind,
                "candidate_source": best_candidate_source,
                "gir_weight_prior": gir_weights[0],
                "gir_weight_intervention": gir_weights[1],
                "gir_weight_influence": gir_weights[2],
                "gir_weight_candidate_quality": gir_weights[3],
                "candidate_formula_energy": best_components.get("formula", base_components["formula"]),
                "candidate_graph_energy": best_components.get("graph", base_components["graph"]),
                "candidate_behavior_energy": best_components.get("behavior", base_components["behavior"]),
            },
        ))
    results.sort(key=lambda item: (-item.score, item.cell))
    elapsed = time.perf_counter() - start
    for item in results:
        item.evidence["localization_seconds"] = elapsed
    return results


def _v3_component_change(before: float, after: float) -> tuple[float, float]:
    """Return normalized improvement and harm for one energy component."""
    denominator = max(1e-9, before)
    gain = max(0.0, before - after) / denominator
    harm = max(0.0, after - before) / denominator
    return gain, harm


def car_v3_scores(
    model: WorkbookModel,
    *,
    candidate_limit: int = 15,
    max_intervention_cells: int = 50,
    use_adaptive_graph: bool = True,
    use_side_effect_penalty: bool = True,
    use_path_responsibility: bool = True,
):
    """FormulaGuard-v3 structure-adaptive counterfactual responsibility."""
    start = time.perf_counter()
    graph = model.dependency_graph()
    base_energy, base_components, base_maps = _energy(model, include_maps=True)
    formula_scores = formula_anomaly_scores(model)
    graph_scores = graph_anomaly_scores(model)
    behavior_scores = behavior_anomaly_scores(model)
    fingerprints = model.fingerprints()
    formula_set = set(model.formula_cells)

    reliability: dict[CellKey, tuple[float, float, float]] = {}
    adaptive_weights: dict[CellKey, tuple[float, float, float]] = {}
    local_priors: dict[CellKey, float] = {}
    for key in model.formula_cells:
        peers = _peers(model, key)
        if peers:
            peer_fingerprints = [fingerprints[peer] for peer in peers]
            peer_coverage = min(1.0, len(peers) / 4.0)
            copy_consistency = max(Counter(peer_fingerprints).values()) / len(peer_fingerprints)
            rho = peer_coverage * copy_consistency
        else:
            rho, peer_coverage, copy_consistency = 0.0, 0.0, 0.0
        if not use_adaptive_graph:
            rho = 1.0
        reliability[key] = (rho, peer_coverage, copy_consistency)
        weights = (0.45, 0.20 * rho, 0.55 - 0.20 * rho)
        adaptive_weights[key] = weights
        local_priors[key] = (
            weights[0] * formula_scores[key]
            + weights[1] * graph_scores[key]
            + weights[2] * behavior_scores[key]
        )

    if len(model.formula_cells) <= max_intervention_cells:
        intervention_cells = set(model.formula_cells)
    else:
        intervention_cells = set(sorted(
            model.formula_cells,
            key=lambda cell: (-local_priors[cell], cell),
        )[:max_intervention_cells])

    descendants_by_cell = {cell: graph.descendants(cell) for cell in intervention_cells}
    max_descendants = max((len(nodes) for nodes in descendants_by_cell.values()), default=1) or 1
    check_tokens = ("check", "audit", "control", "validation")
    check_cells = {
        cell for cell in model.formula_cells
        if any(token in cell[0].casefold() for token in check_tokens)
    }
    reached_checks = {
        cell: descendants_by_cell.get(cell, set()) & check_cells
        for cell in intervention_cells
    }
    max_checks = max((len(nodes) for nodes in reached_checks.values()), default=1) or 1
    structural_sinks = set(graph.sinks(model.formula_cells))

    def block_boundary_factor(key: CellKey) -> float:
        sheet, row, col = _coordinate(key)
        column = num_to_col(col)
        above = (sheet, f"{column}{row - 1}") if row > 1 else None
        below = (sheet, f"{column}{row + 1}")
        below_two = (sheet, f"{column}{row + 2}")
        if above not in formula_set and below in formula_set and below_two in formula_set:
            return 0.25
        return 1.0

    results: list[LocalizationResult] = []
    for key in model.formula_cells:
        rho, peer_coverage, copy_consistency = reliability[key]
        w_formula, w_graph, w_behavior = adaptive_weights[key]
        descendants = descendants_by_cell.get(key, set())
        influence = (
            math.log1p(len(descendants)) / max(1e-9, math.log1p(max_descendants))
            if key in intervention_cells else 0.0
        )
        check_reach = len(reached_checks.get(key, set())) / max_checks if key in intervention_cells else 0.0
        path_responsibility = 0.60 * influence + 0.40 * check_reach
        if not use_path_responsibility:
            path_responsibility = 0.0
        boundary = block_boundary_factor(key)
        # Path information may strengthen a positive intervention, but cannot
        # manufacture suspicion in the absence of counterfactual recovery.
        adaptive_prior = local_priors[key] * boundary

        best_score = 0.20 * adaptive_prior
        best_candidate: RepairCandidate | None = None
        best_values = {
            "raw_gain": 0.0,
            "side_effect": 0.0,
            "net_gain": 0.0,
            "gain_formula": 0.0,
            "gain_graph": 0.0,
            "gain_behavior": 0.0,
            "gain_constraint": 0.0,
            "harm_formula": 0.0,
            "harm_graph": 0.0,
            "harm_behavior": 0.0,
            "harm_constraint": 0.0,
            "candidate_total_energy": base_energy,
            "candidate_constraint_energy": base_components["constraint"],
            "downstream_recovery": 0.0,
            "candidate_path_responsibility": 0.0,
        }
        candidates: list[RepairCandidate] = []
        if key in intervention_cells:
            candidates = generate_candidates(model, key, candidate_limit)
            for candidate in candidates:
                candidate_energy, after, after_maps = _energy(
                    model, {key: candidate.formula}, include_maps=True
                )
                changes = {
                    name: _v3_component_change(base_components[name], after[name])
                    for name in ("formula", "graph", "behavior_general", "constraint")
                }
                component_weights = {
                    "formula": 0.20,
                    "graph": 0.15 * rho,
                    "behavior_general": 0.25,
                    "constraint": 0.40,
                }
                raw_gain = sum(component_weights[name] * changes[name][0] for name in changes)
                side_effect = sum(component_weights[name] * changes[name][1] for name in changes)
                penalty = 0.50 * side_effect if use_side_effect_penalty else 0.0
                net_gain = max(0.0, raw_gain - penalty)
                downstream_nodes = descendants | {key}
                recovery_numerator = 0.0
                recovery_denominator = 0.0
                for component_name, component_weight in component_weights.items():
                    before_map = base_maps[component_name]
                    after_map = after_maps[component_name]
                    for node in downstream_nodes:
                        before_value = float(before_map.get(node, 0.0))
                        after_value = float(after_map.get(node, 0.0))
                        recovery_denominator += component_weight * before_value
                        recovery_numerator += component_weight * max(0.0, before_value - after_value)
                downstream_recovery = min(
                    1.0,
                    recovery_numerator / max(1e-9, recovery_denominator),
                )
                candidate_path = path_responsibility * downstream_recovery
                score = (
                    0.20 * adaptive_prior
                    + 0.60 * net_gain
                    + 0.10 * net_gain * candidate_path
                    + 0.10 * net_gain * candidate.quality
                )
                if score > best_score:
                    best_score = score
                    best_candidate = candidate
                    best_values = {
                        "raw_gain": raw_gain,
                        "side_effect": side_effect,
                        "net_gain": net_gain,
                        "gain_formula": changes["formula"][0],
                        "gain_graph": changes["graph"][0],
                        "gain_behavior": changes["behavior_general"][0],
                        "gain_constraint": changes["constraint"][0],
                        "harm_formula": changes["formula"][1],
                        "harm_graph": changes["graph"][1],
                        "harm_behavior": changes["behavior_general"][1],
                        "harm_constraint": changes["constraint"][1],
                        "candidate_total_energy": candidate_energy,
                        "candidate_constraint_energy": after["constraint"],
                        "downstream_recovery": downstream_recovery,
                        "candidate_path_responsibility": candidate_path,
                    }
        if best_candidate is None and candidates:
            best_candidate = max(
                candidates,
                key=lambda item: (item.support, item.quality, -item.edit_cost, item.formula),
            )
            fallback_energy, fallback_components = _energy(model, {key: best_candidate.formula})
            best_values["candidate_total_energy"] = fallback_energy
            best_values["candidate_constraint_energy"] = fallback_components["constraint"]

        reachable_terminals = sorted(
            descendants & (structural_sinks | check_cells),
            key=lambda cell: (
                0 if cell in check_cells else 1,
                graph.shortest_path_length(key, cell) or 10**9,
                cell,
            ),
        )[:10]
        paths = [graph.shortest_path(key, target) or [] for target in reachable_terminals]
        serialized_paths = [
            " -> ".join(f"{sheet}!{address}" for sheet, address in path)
            for path in paths if path
        ]
        quality = best_candidate.quality if best_candidate else 0.0
        net_gain = best_values["net_gain"]
        results.append(LocalizationResult(
            cell=key,
            score=best_score,
            candidate_formula=best_candidate.formula if best_candidate else None,
            evidence={
                "model_version": "v3",
                "formula_anomaly": formula_scores[key],
                "graph_anomaly": graph_scores[key],
                "behavior_anomaly": behavior_scores[key],
                "structure_reliability": rho,
                "peer_coverage": peer_coverage,
                "copy_consistency": copy_consistency,
                "adaptive_weight_formula": w_formula,
                "adaptive_weight_graph": w_graph,
                "adaptive_weight_behavior": w_behavior,
                "local_prior": local_priors[key],
                "adaptive_prior": adaptive_prior,
                "base_energy": base_energy,
                "base_constraint_energy": base_components["constraint"],
                "block_boundary_factor": boundary,
                "descendants": len(descendants),
                "influence": influence,
                "check_reach": check_reach,
                "structural_path_responsibility": path_responsibility,
                "path_responsibility": best_values["candidate_path_responsibility"],
                "reported_path": serialized_paths[0] if serialized_paths else "",
                "reported_paths": " ; ".join(serialized_paths),
                **best_values,
                "candidate_quality": quality,
                "candidate_support": best_candidate.support if best_candidate else 0,
                "candidate_edit_kind": ",".join(best_candidate.edit_kinds) if best_candidate else "",
                "candidate_source": ",".join(best_candidate.sources) if best_candidate else "",
                "evidence_strength": net_gain * quality,
                "candidate_evidence": "positive" if net_gain > 0 else "weak",
            },
        ))

    results.sort(key=lambda item: (-item.score, item.cell))
    elapsed = time.perf_counter() - start
    for item in results:
        item.evidence["localization_seconds"] = elapsed
    return results


def sfl_oracle_scores(model: WorkbookModel, failed_sinks: set[CellKey]):
    graph = model.dependency_graph()
    sinks = set(graph.sinks(model.formula_cells))
    passed_sinks = sinks - failed_sinks
    result: dict[CellKey, float] = {}
    for key in model.formula_cells:
        covered_failed = sum(1 for sink in failed_sinks if key == sink or key in graph.ancestors(sink))
        covered_passed = sum(1 for sink in passed_sinks if key == sink or key in graph.ancestors(sink))
        denom = math.sqrt(max(1, len(failed_sinks)) * max(1, covered_failed + covered_passed))
        result[key] = covered_failed / denom if denom else 0.0
    return result


def _results_from_scores(scores: Mapping[CellKey, float], repairs: Mapping[CellKey, str | None] | None = None):
    repairs = repairs or {}
    results = [LocalizationResult(key, float(score), repairs.get(key)) for key, score in scores.items()]
    results.sort(key=lambda item: (-item.score, item.cell))
    return results


def localize(model: WorkbookModel, method: str = "formulaguard", *, failed_sinks: set[CellKey] | None = None,
             candidate_limit: int = 15, gir_weights=(0.35, 0.50, 0.10, 0.05)):
    method = method.lower()
    if method == "formulaguard":
        return gir_scores(model, candidate_limit=candidate_limit, gir_weights=gir_weights)
    if method == "formulaguard_v3":
        return car_v3_scores(model, candidate_limit=candidate_limit)
    if method == "v3_ablate_adaptive":
        return car_v3_scores(model, candidate_limit=candidate_limit, use_adaptive_graph=False)
    if method == "v3_ablate_side_effect":
        return car_v3_scores(model, candidate_limit=candidate_limit, use_side_effect_penalty=False)
    if method == "v3_ablate_path":
        return car_v3_scores(model, candidate_limit=candidate_limit, use_path_responsibility=False)
    if method == "pattern":
        return _results_from_scores(formula_anomaly_scores(model))
    if method == "graph":
        graph = model.dependency_graph()
        anomalies = graph_anomaly_scores(model)
        if len(model.formula_cells) <= 500:
            descendant_counts = {k: len(graph.descendants(k)) for k in model.formula_cells}
            max_desc = max(descendant_counts.values(), default=1) or 1
            scores = {k: anomalies[k] * (1 + descendant_counts[k] / max_desc) for k in model.formula_cells}
        else:
            max_out = max((len(graph.dependents.get(k, ())) for k in model.formula_cells), default=1) or 1
            scores = {k: anomalies[k] * (1 + len(graph.dependents.get(k, ())) / max_out) for k in model.formula_cells}
        return _results_from_scores(scores)
    if method == "behavior":
        return _results_from_scores(behavior_anomaly_scores(model))
    if method == "excel_like":
        return _results_from_scores(excel_like_scores(model))
    if method == "excelint_like":
        return _results_from_scores(excelint_like_scores(model))
    if method == "warder_like":
        scores, repairs = warder_like_scores(model)
        return _results_from_scores(scores, repairs)
    if method == "random":
        scores = {}
        for key in model.formula_cells:
            digest = hashlib.sha256(f"{model.source}|{key[0]}|{key[1]}".encode("utf-8")).digest()
            scores[key] = int.from_bytes(digest[:8], "big") / 2**64
        return _results_from_scores(scores)
    if method == "sfl_oracle":
        if failed_sinks is None:
            raise ValueError("sfl_oracle requires failed_sinks")
        return _results_from_scores(sfl_oracle_scores(model, failed_sinks))
    if method == "ablate_formula":
        return gir_scores(model, candidate_limit=candidate_limit, weights=(0.0, 0.45, 0.55), gir_weights=gir_weights)
    if method == "ablate_graph":
        return gir_scores(model, candidate_limit=candidate_limit, weights=(0.60, 0.0, 0.40), gir_weights=gir_weights)
    if method == "ablate_behavior":
        return gir_scores(model, candidate_limit=candidate_limit, weights=(0.65, 0.35, 0.0), gir_weights=gir_weights)
    if method == "ablate_influence":
        return gir_scores(model, candidate_limit=candidate_limit, gir_weights=gir_weights, use_influence=False)
    if method == "ablate_intervention":
        return gir_scores(model, candidate_limit=candidate_limit, gir_weights=gir_weights, use_intervention=False)
    raise ValueError(f"Unknown localization method: {method}")
