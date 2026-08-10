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
    selected = [item for _, item in same_col]
    if len(selected) < 2:
        selected += [item for _, item in same_row]
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


def behavior_anomaly_scores(model: WorkbookModel, overrides: Mapping[CellKey, str] | None = None):
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
            weights=(0.45, 0.25, 0.30)):
    fa = formula_anomaly_scores(model, overrides)
    ga = graph_anomaly_scores(model, overrides)
    ba = behavior_anomaly_scores(model, overrides)
    n = max(1, len(model.formula_cells))
    components = {
        "formula": sum(fa.values()) / n,
        "graph": sum(ga.values()) / n,
        "behavior": sum(ba.values()) / n,
    }
    total = weights[0] * components["formula"] + weights[1] * components["graph"] + weights[2] * components["behavior"]
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
    return ranked[:limit]


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
    results: list[LocalizationResult] = []

    for key in model.formula_cells:
        descendants = descendant_counts.get(key, 0)
        influence = 0.0
        if use_influence and key in intervention_cells:
            influence = math.log1p(descendants) / max(1e-9, math.log1p(max_desc))
        best_score = gir_weights[0] * prior_scores[key]
        best_candidate = None
        best_delta = 0.0
        best_delta_normalized = 0.0
        best_quality = 0.0
        best_support = 0
        best_edit_kind = ""
        best_candidate_source = ""
        best_components: dict[str, float] = {}
        if use_intervention and key in intervention_cells:
            for repair_candidate in generate_candidates(model, key, candidate_limit):
                candidate, support = repair_candidate
                candidate_energy, candidate_components = _energy(model, {key: candidate}, weights=weights)
                delta = base_energy - candidate_energy
                delta_normalized = max(0.0, delta) / max(1e-9, base_energy)
                score = (
                    gir_weights[0] * prior_scores[key]
                    + gir_weights[1] * delta_normalized
                    + gir_weights[2] * delta_normalized * influence
                    + gir_weights[3] * repair_candidate.quality
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
                "descendants": descendants,
                "influence": influence,
                "base_energy": base_energy,
                "delta_energy": best_delta,
                "delta_energy_normalized": best_delta_normalized,
                "candidate_quality": best_quality,
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
