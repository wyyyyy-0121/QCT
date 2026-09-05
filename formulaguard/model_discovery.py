"""Label-free atomic signal audit for the model-discovery research line.

This module is deliberately independent of the historical V4/V5 rankers.  It
does not accept a manifest row, a label, a source cell, or an expected output.
It only turns the observable contents of one :class:`WorkbookModel` into
auditable signal views.  The output is an evidence inventory, not a promoted
model; the separate scoring stage decides whether any view is useful.
"""

from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_left
from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from .a1 import num_to_col, parse_address
from .formula import (
    Binary,
    Func,
    Node,
    Number,
    Range,
    Ref,
    Unary,
    normalized_formula,
    translate_formula,
)
from .workbook import CellKey, DependencyGraph, WorkbookModel

PROTOCOL = "formulaguard_model_discovery_label_free_signal_audit_v1"
MODEL_VERSION = "model-discovery-atomic-signals-v1"
REVIEW_BUDGET = 5
FORBIDDEN_LABEL_FIELDS = (
    "correct_formula",
    "source_cell",
    "source_cells",
    "error_type",
    "case_kind",
    "corpus_id",
    "template_id",
    "filename_semantics",
    "secret_labels",
    "expected_output",
    "pass_fail",
)


@dataclass(frozen=True)
class SignalAuditConfig:
    """Fixed, low-complexity audit limits.

    These limits are engineering bounds, not fitted parameters.  They are
    serialized into every result so a future Gate 2 protocol can freeze them
    before labels are inspected.
    """

    review_budget: int = REVIEW_BUDGET
    axis_radius: int = 12
    local_radius: int = 6
    max_axis_peers: int = 16
    max_local_peers: int = 24
    max_role_peers: int = 16
    max_hypotheses: int = 4
    impact_depth: int = 4
    max_impact_nodes: int = 2000

    def __post_init__(self) -> None:
        if self.review_budget != REVIEW_BUDGET:
            raise ValueError("model-discovery review budget is fixed at five")
        for name in (
            "axis_radius", "local_radius", "max_axis_peers", "max_local_peers",
            "max_role_peers", "max_hypotheses", "impact_depth", "max_impact_nodes",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be positive")

    def as_dict(self) -> dict[str, int]:
        return {key: int(value) for key, value in asdict(self).items()}


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _stable_hash(value: object) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _cell_sort(key: CellKey) -> tuple[str, int, int, str]:
    address = parse_address(key[1])
    return key[0], address.row, address.col, key[1]


def _label(key: CellKey) -> str:
    return f"{key[0]}!{key[1]}"


def _coordinate(key: CellKey) -> tuple[int, int]:
    address = parse_address(key[1])
    return address.row, address.col


def _band(value: int) -> int:
    if value <= 0:
        return 0
    if value == 1:
        return 1
    if value <= 3:
        return 2
    if value <= 8:
        return 3
    return 4


def _outer_class(node: Node) -> str:
    if isinstance(node, Binary):
        # Keep the broad operation kind in the role key.  Operator changes are
        # a possible defect signal, so encoding the exact operator here would
        # prevent a changed formula from finding its otherwise compatible peers.
        return "binary"
    if isinstance(node, Func):
        return "function"
    if isinstance(node, Unary):
        return "unary"
    return type(node).__name__.lower()


def _shape_class(node: Node) -> str:
    """Return an operator/name-independent formula reference shape."""

    if isinstance(node, Number):
        return "number"
    if isinstance(node, Ref):
        return "ref"
    if isinstance(node, Range):
        return "range"
    if isinstance(node, Unary):
        return f"unary({_shape_class(node.value)})"  # type: ignore[arg-type]
    if isinstance(node, Binary):
        return f"binary({_shape_class(node.left)},{_shape_class(node.right)})"  # type: ignore[arg-type]
    if isinstance(node, Func):
        return f"function({','.join(_shape_class(arg) for arg in node.args)})"
    return type(node).__name__.lower()


def _format_class(model: WorkbookModel, key: CellKey) -> str:
    value = model.number_format(key).upper()
    if "%" in value:
        return "percent"
    if any(token in value for token in ("YY", "DD", "MM", "H", "SS")):
        return "date_or_time"
    if value in {"GENERAL", "@"}:
        return value.lower()
    return "numeric_format"


def _sha256_path(path: str) -> str | None:
    candidate = Path(path)
    if not candidate.is_file():
        return None
    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _input_hash(model: WorkbookModel) -> str:
    source_hash = _sha256_path(model.source) if model.source else None
    if source_hash:
        return source_hash
    return _stable_hash({
        "cells": sorted(((_label(key), repr(value)) for key, value in model.cells.items())),
        "formulas": sorted(((_label(key), value) for key, value in model.formulas.items())),
    })


def _union_find(values: Iterable[CellKey]):
    parent = {value: value for value in values}

    def find(value: CellKey) -> CellKey:
        root = value
        while parent[root] != root:
            root = parent[root]
        while parent[value] != value:
            next_value = parent[value]
            parent[value] = root
            value = next_value
        return root

    def union(left: CellKey, right: CellKey) -> None:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return
        if _cell_sort(left_root) <= _cell_sort(right_root):
            parent[right_root] = left_root
        else:
            parent[left_root] = right_root

    return parent, find, union


def _build_regions(
    model: WorkbookModel,
    parseable: Mapping[CellKey, bool],
) -> tuple[dict[CellKey, str], dict[str, int]]:
    """Build conservative contiguous formula regions without labels."""

    cells = tuple(sorted((key for key, ok in parseable.items() if ok), key=_cell_sort))
    _parent, find, union = _union_find(cells)
    cell_set = set(cells)
    for key in cells:
        sheet, address_text = key
        address = parse_address(address_text)
        for row, col in ((address.row, address.col + 1), (address.row + 1, address.col)):
            other = (sheet, f"{num_to_col(col)}{row}")
            if other not in cell_set or not parseable.get(other, False):
                continue
            try:
                left = normalized_formula(model.formulas[key])
                translated = normalized_formula(
                    translate_formula(model.formulas[key], key[1], other[1])
                )
                right = normalized_formula(model.formulas[other])
            except Exception:  # noqa: BLE001, S112 intentional compatibility or fallback boundary; preserve runtime behavior
                continue
            if translated == right or left == right:
                union(key, other)

    members: dict[CellKey, list[CellKey]] = defaultdict(list)
    for key in cells:
        members[find(key)].append(key)
    region_by_cell: dict[CellKey, str] = {}
    region_sizes: dict[str, int] = {}
    for root, values in sorted(members.items(), key=lambda item: _cell_sort(item[0])):
        region_id = "region:" + _stable_hash([_label(value) for value in sorted(values, key=_cell_sort)])[:20]
        region_sizes[region_id] = len(values)
        for value in values:
            region_by_cell[value] = region_id
    for key in model.formula_cells:
        if key not in region_by_cell:
            region_id = "region:" + _stable_hash([_label(key)])[:20]
            region_by_cell[key] = region_id
            region_sizes[region_id] = 1
    return region_by_cell, region_sizes


def _bounded_impact(
    graph: DependencyGraph,
    start: CellKey,
    formula_set: set[CellKey],
    sinks: set[CellKey],
    config: SignalAuditConfig,
) -> dict[str, int | float]:
    """Measure propagation separately from defect evidence.

    A bounded cone keeps large workbooks tractable and prevents impact from
    silently becoming a proxy for error probability.
    """

    queue: deque[tuple[CellKey, int]] = deque([(start, 0)])
    seen: dict[CellKey, int] = {start: 0}
    while queue and len(seen) - 1 < config.max_impact_nodes:
        node, depth = queue.popleft()
        if depth >= config.impact_depth:
            continue
        for child in sorted(graph.dependents.get(node, ()), key=_cell_sort):
            if child in seen:
                continue
            seen[child] = depth + 1
            queue.append((child, depth + 1))
            if len(seen) - 1 >= config.max_impact_nodes:
                break
    descendants = set(seen) - {start}
    formula_descendants = descendants & formula_set
    sink_count = len(formula_descendants & sinks)
    max_depth = max((seen[item] for item in descendants), default=0)
    weighted = sum(1.0 / (1.0 + seen[item]) for item in formula_descendants)
    # log scaling avoids making a single very wide workbook dominate the score.
    impact_score = min(
        1.0,
        0.45 * (1.0 - math.exp(-len(formula_descendants) / 8.0))
        + 0.30 * (1.0 - math.exp(-sink_count / 3.0))
        + 0.25 * (1.0 - math.exp(-weighted / 8.0)),
    )
    return {
        "descendant_count": len(formula_descendants),
        "sink_count": sink_count,
        "max_depth": max_depth,
        "weighted_reach": round(weighted, 12),
        "impact_score": round(impact_score, 12),
        "truncated": int(len(seen) - 1 >= config.max_impact_nodes),
    }


def _nearest_axis(
    values: Sequence[CellKey],
    key: CellKey,
    *,
    axis: str,
    radius: int,
    limit: int,
) -> list[CellKey]:
    row, col = _coordinate(key)
    candidates = []
    for other in values:
        if other == key:
            continue
        other_row, other_col = _coordinate(other)
        distance = abs(other_col - col) if axis == "row" else abs(other_row - row)
        if distance <= radius:
            candidates.append((distance, _cell_sort(other), other))
    candidates.sort()
    return [item[2] for item in candidates[:limit]]


def _nearest_local(
    by_sheet_row: Mapping[tuple[str, int], Sequence[CellKey]],
    key: CellKey,
    *,
    radius: int,
    limit: int,
) -> list[CellKey]:
    row, col = _coordinate(key)
    candidates = []
    for candidate_row in range(max(1, row - radius), row + radius + 1):
        for other in by_sheet_row.get((key[0], candidate_row), ()):
            if other == key:
                continue
            other_row, other_col = _coordinate(other)
            distance = abs(other_row - row) + abs(other_col - col)
            if max(abs(other_row - row), abs(other_col - col)) <= radius:
                candidates.append((distance, _cell_sort(other), other))
    candidates.sort()
    return [item[2] for item in candidates[:limit]]


def _nearest_role(
    values: Sequence[CellKey],
    key: CellKey,
    *,
    limit: int,
) -> list[CellKey]:
    """Use a coordinate window so large role families stay linear-ish."""

    ordered = sorted(values, key=_cell_sort)
    if not ordered:
        return []
    coordinates = [(_coordinate(item)[0] * 1_000_000 + _coordinate(item)[1]) for item in ordered]
    target = _coordinate(key)[0] * 1_000_000 + _coordinate(key)[1]
    position = bisect_left(coordinates, target)
    window = ordered[max(0, position - limit * 2): position + limit * 2 + 1]
    candidates = [
        (abs(_coordinate(item)[0] - _coordinate(key)[0]) + abs(_coordinate(item)[1] - _coordinate(key)[1]), _cell_sort(item), item)
        for item in window if item != key
    ]
    candidates.sort()
    return [item[2] for item in candidates[:limit]]


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _round(value: float) -> float:
    return round(float(value), 12)


def _ranking_key(record: Mapping[str, object], channel: str) -> tuple[object, ...]:
    label = str(record["cell"])
    if channel == "impact":
        return (
            -float(record["impact_score"]),
            -int(record["descendant_count"]),
            -int(record["sink_count"]),
            label,
        )
    if channel == "role":
        return (
            -float(record["role_outlier_score"]),
            -float(record["competition_score"]),
            -int(record["equivalence_class_size"]),
            label,
        )
    if channel == "peer":
        return (
            -float(record["peer_disagreement"]),
            -int(record["alternative_support"]),
            -int(record["independent_support"]),
            label,
        )
    # Impact is deliberately after defect evidence and only breaks ties within
    # an evidence tier; it cannot turn an impact-only cell into a defect claim.
    return (
        -int(record["evidence_tier"]),
        -float(record["defect_score"]),
        -int(record["independent_support"]),
        -int(record["alternative_support"]),
        -float(record["impact_score"]),
        label,
    )


def _select_review(
    records: Mapping[str, Mapping[str, object]],
    ordered: Sequence[str],
    budget: int,
) -> list[str]:
    selected: list[str] = []
    regions: set[str] = set()
    # Prefer actual evidence or impact, while retaining a deterministic
    # fallback when a workbook has no supported peer relationship.
    for pass_number in (0, 1):
        for label in ordered:
            record = records[label]
            if pass_number == 0 and int(record["evidence_tier"]) == 0 and float(record["impact_score"]) <= 0.0:
                continue
            region = str(record["region_id"])
            if label in selected or region in regions:
                continue
            selected.append(label)
            regions.add(region)
            if len(selected) >= budget:
                return selected
    return selected[:budget]


def audit_workbook(
    model: WorkbookModel,
    *,
    config: SignalAuditConfig | None = None,
) -> dict[str, object]:
    """Return deterministic label-free atomic signals for one workbook."""

    config = config or SignalAuditConfig()
    formula_cells = tuple(sorted(model.formula_cells, key=_cell_sort))
    formula_set = set(formula_cells)
    graph = model.dependency_graph()
    sinks = set(graph.sinks(formula_cells))
    parseable: dict[CellKey, bool] = {}
    parse_errors: dict[CellKey, str] = {}
    fingerprints: dict[CellKey, str] = {}
    shapes: dict[CellKey, str] = {}
    nodes: dict[CellKey, Node] = {}
    all_fingerprints = model.fingerprints()
    for key in formula_cells:
        try:
            nodes[key] = model.ast(model.formulas[key])
            fingerprints[key] = all_fingerprints[key]
            shapes[key] = _shape_class(nodes[key])
            parseable[key] = True
        except Exception as exc:  # noqa: BLE001 intentional compatibility or fallback boundary; preserve runtime behavior
            parseable[key] = False
            parse_errors[key] = f"{type(exc).__name__}: {exc}"
            fingerprints[key] = "UNSUPPORTED"

    visible = {key: bool(model.is_visible(key)) for key in formula_cells}
    by_sheet_row: dict[tuple[str, int], list[CellKey]] = defaultdict(list)
    by_sheet_col: dict[tuple[str, int], list[CellKey]] = defaultdict(list)
    by_sheet: dict[str, list[CellKey]] = defaultdict(list)
    by_fingerprint: dict[tuple[str, str], list[CellKey]] = defaultdict(list)
    by_role: dict[tuple[str, tuple[object, ...]], list[CellKey]] = defaultdict(list)
    roles: dict[CellKey, tuple[object, ...]] = {}
    for key in formula_cells:
        if not parseable[key]:
            continue
        row, col = _coordinate(key)
        by_sheet_row[(key[0], row)].append(key)
        by_sheet_col[(key[0], col)].append(key)
        by_sheet[key[0]].append(key)
        by_fingerprint[(key[0], fingerprints[key])].append(key)
        precedent_count = len(graph.precedents.get(key, ()))
        dependent_count = len(graph.dependents.get(key, ()))
        role = (
            _outer_class(nodes[key]),
            shapes[key],
            _band(precedent_count),
            _band(dependent_count),
            _format_class(model, key),
        )
        roles[key] = role
        by_role[(key[0], role)].append(key)

    for values in (*by_sheet_row.values(), *by_sheet_col.values(), *by_sheet.values(), *by_fingerprint.values(), *by_role.values()):
        values.sort(key=_cell_sort)
    region_by_cell, region_sizes = _build_regions(model, parseable)

    raw_records: dict[str, dict[str, object]] = {}
    for key in formula_cells:
        label = _label(key)
        row, col = _coordinate(key)
        precedent_count = len(graph.precedents.get(key, ()))
        dependent_count = len(graph.dependents.get(key, ()))
        impact = _bounded_impact(graph, key, formula_set, sinks, config)
        region_id = region_by_cell[key]
        if not parseable[key]:
            raw_records[label] = {
                "cell": label,
                "sheet_visible": int(model.sheet_visibility.get(key[0], True)),
                "cell_visible": int(visible[key]),
                "parseable": False,
                "parse_error": parse_errors.get(key, "unsupported_formula"),
                "fingerprint": "UNSUPPORTED",
                "shape_class": "unsupported",
                "equivalence_class_size": 0,
                "region_id": region_id,
                "region_size": region_sizes.get(region_id, 1),
                "row": row,
                "column": col,
                "precedent_count": precedent_count,
                "dependent_count": dependent_count,
                "evidence_tier": 0,
                "defect_score": 0.0,
                "role_outlier_score": 0.0,
                "competition_score": 0.0,
                "peer_disagreement": 0.0,
                "alternative_support": 0,
                "independent_support": 0,
                "impact_only": 0,
                **impact,
                "status": "unsupported",
                "status_reason": "formula_parse_failed",
                "repair_hypotheses": [],
            }
            continue

        row_peers = _nearest_axis(
            by_sheet_row.get((key[0], row), ()), key, axis="row",
            radius=config.axis_radius, limit=config.max_axis_peers,
        )
        col_peers = _nearest_axis(
            by_sheet_col.get((key[0], col), ()), key, axis="column",
            radius=config.axis_radius, limit=config.max_axis_peers,
        )
        local_peers = _nearest_local(
            by_sheet_row, key, radius=config.local_radius, limit=config.max_local_peers,
        )
        role_peers = _nearest_role(
            by_role.get((key[0], roles[key]), ()), key, limit=config.max_role_peers,
        )
        peer_axes = {
            "row": row_peers,
            "column": col_peers,
            "local": local_peers,
            "role": role_peers,
        }
        all_peers = sorted(
            {peer for peers in peer_axes.values() for peer in peers if parseable.get(peer, False) and visible.get(peer, True)},
            key=_cell_sort,
        )
        target_norm = normalized_formula(model.formulas[key])
        candidate_votes: Counter[str] = Counter()
        candidate_sources: dict[str, set[CellKey]] = defaultdict(set)
        candidate_axes: dict[str, set[str]] = defaultdict(set)
        candidate_texts: dict[str, set[str]] = defaultdict(set)
        peer_candidate: dict[CellKey, str] = {}
        for peer in all_peers:
            # Formula shape compatibility prevents unrelated horizontal
            # calculations from manufacturing repair evidence.  Operators and
            # function names remain free to differ so those defects can still
            # be detected when the reference topology is unchanged.
            if shapes.get(peer) != shapes[key]:
                continue
            try:
                candidate = translate_formula(model.formulas[peer], peer[1], key[1])
                candidate_norm = normalized_formula(candidate)
            except Exception:  # noqa: BLE001, S112 intentional compatibility or fallback boundary; preserve runtime behavior
                continue
            peer_candidate[peer] = candidate_norm
            candidate_votes[candidate_norm] += 1
            candidate_sources[candidate_norm].add(peer)
            candidate_texts[candidate_norm].add(candidate)
            for axis, peers in peer_axes.items():
                if peer in peers:
                    candidate_axes[candidate_norm].add(axis)

        alternatives = [norm for norm in candidate_votes if norm != target_norm]
        alternatives.sort(
            key=lambda norm: (
                -candidate_votes[norm],
                -len(candidate_axes[norm]),
                -len(candidate_sources[norm]),
                norm,
            )
        )
        best_alt = alternatives[0] if alternatives else None
        second_alt = alternatives[1] if len(alternatives) > 1 else None
        alternative_support = candidate_votes[best_alt] if best_alt else 0
        second_support = candidate_votes[second_alt] if second_alt else 0
        independent_support = len(candidate_axes[best_alt]) if best_alt else 0
        total_votes = sum(candidate_votes.values())
        peer_disagreement = (
            sum(value for norm, value in candidate_votes.items() if norm != target_norm)
            / total_votes
            if total_votes else 0.0
        )
        same_family = len(by_fingerprint.get((key[0], fingerprints[key]), ()))
        role_pool = by_role.get((key[0], roles[key]), ())
        role_same = sum(fingerprints.get(peer) == fingerprints[key] for peer in role_pool)
        role_outlier = 1.0 - role_same / max(1, len(role_pool))
        local_classes = Counter(fingerprints.get(peer, "UNSUPPORTED") for peer in all_peers)
        class_values = sorted(local_classes.values(), reverse=True)
        competition = (
            (class_values[1] / max(1, class_values[0]))
            if len(class_values) > 1 and class_values[0] else 0.0
        )
        margin = alternative_support - second_support
        axis_ratio = independent_support / 4.0
        support_ratio = alternative_support / max(1, total_votes)
        margin_ratio = max(0.0, margin) / max(1, total_votes)
        defect_score = _clamp(
            0.50 * support_ratio + 0.30 * axis_ratio + 0.20 * margin_ratio
        )
        strong = (
            best_alt is not None
            and alternative_support >= 2
            and len(candidate_sources[best_alt]) >= 2
            and independent_support >= 2
            and margin > 0
            and competition <= 0.75
        )
        ambiguous = (
            best_alt is not None
            and alternative_support >= 2
            and not strong
        )
        impact_only = not strong and not ambiguous and float(impact["impact_score"]) >= 0.35
        if strong:
            status, reason, tier = "evidence_supported", "dominant_multi_view_alternative", 3
        elif ambiguous:
            status, reason, tier = "ambiguous", "competing_or_single_view_alternative", 1
        elif impact_only:
            status, reason, tier = "impact_only", "propagation_without_defect_support", 0
        elif not all_peers:
            status, reason, tier = "unsupported", "no_observable_formula_peers", 0
        else:
            status, reason, tier = "unsupported", "no_alternative_supported", 0

        hypotheses = []
        for norm in alternatives[:config.max_hypotheses]:
            texts = sorted(candidate_texts[norm])
            hypotheses.append({
                "formula": texts[0] if texts else norm,
                "normalized_formula": norm,
                "support_count": candidate_votes[norm],
                "support_axes": sorted(candidate_axes[norm]),
                "support_cells": [_label(item) for item in sorted(candidate_sources[norm], key=_cell_sort)[:config.max_axis_peers]],
            })
        raw_records[label] = {
            "cell": label,
            "sheet_visible": int(model.sheet_visibility.get(key[0], True)),
            "cell_visible": int(visible[key]),
            "parseable": True,
            "parse_error": "",
            "fingerprint": fingerprints[key],
            "shape_class": shapes[key],
            "equivalence_class_size": same_family,
            "region_id": region_id,
            "region_size": region_sizes.get(region_id, 1),
            "row": row,
            "column": col,
            "precedent_count": precedent_count,
            "dependent_count": dependent_count,
            "role_key": list(roles[key]),
            "peer_counts": {axis: len(peers) for axis, peers in peer_axes.items()},
            "peer_formula_count": len(all_peers),
            "formula_family_count": same_family,
            "alternative_support": alternative_support,
            "second_alternative_support": second_support,
            "independent_support": independent_support,
            "alternative_margin": margin,
            "peer_disagreement": _round(peer_disagreement),
            "role_outlier_score": _round(_clamp(role_outlier)),
            "competition_score": _round(_clamp(competition)),
            "defect_score": _round(defect_score),
            "evidence_tier": tier,
            "best_alternative": best_alt or "",
            "status": status,
            "status_reason": reason,
            "impact_only": int(status == "impact_only"),
            **impact,
            "repair_hypotheses": hypotheses,
        }

    channels = ("combined", "peer", "role", "impact")
    rankings: dict[str, list[str]] = {}
    rank_records: dict[str, list[dict[str, object]]] = {}
    for channel in channels:
        ordered_records = sorted(raw_records.values(), key=lambda record: _ranking_key(record, channel))
        labels = [str(record["cell"]) for record in ordered_records]
        rankings[channel] = labels
        rank_records[channel] = [
            {
                "cell": str(record["cell"]),
                "rank": index,
                "score": _round(float(record["impact_score"] if channel == "impact" else record["defect_score"])),
                "region_id": str(record["region_id"]),
            }
            for index, record in enumerate(ordered_records, 1)
        ]
    reviews = {
        channel: _select_review(raw_records, rankings[channel], config.review_budget)
        for channel in channels
    }

    records = [raw_records[label] for label in sorted(raw_records, key=lambda value: _cell_sort((value.split("!", 1)[0], value.split("!", 1)[1])))]
    source_kind = "xlsx" if model.source.lower().endswith((".xlsx", ".xlsm")) else "in_memory"
    payload: dict[str, object] = {
        "protocol": PROTOCOL,
        "model_version": MODEL_VERSION,
        "input_sha256": _input_hash(model),
        "source_kind": source_kind,
        "label_inputs": [],
        "forbidden_label_fields": list(FORBIDDEN_LABEL_FIELDS),
        "configuration": config.as_dict(),
        "configuration_sha256": _stable_hash(config.as_dict()),
        "formula_count": len(formula_cells),
        "parseable_formula_count": sum(parseable.values()),
        "unsupported_formula_count": sum(not value for value in parseable.values()),
        "visible_formula_count": sum(visible.values()),
        "region_count": len(region_sizes),
        "region_sizes": dict(sorted(region_sizes.items())),
        "rankings": rankings,
        "rank_records": rank_records,
        "review_cells": reviews,
        "records": records,
    }
    payload["audit_sha256"] = _stable_hash(payload)
    return payload


def validate_label_free_output(payload: Mapping[str, object]) -> list[str]:
    """Validate the non-negotiable prediction boundary for one audit result."""

    errors: list[str] = []
    if payload.get("protocol") != PROTOCOL:
        errors.append("unexpected model-discovery signal protocol")
    if payload.get("model_version") != MODEL_VERSION:
        errors.append("unexpected model-discovery signal version")
    recorded_hash = payload.get("audit_sha256")
    if recorded_hash:
        unhashed = dict(payload)
        unhashed.pop("audit_sha256", None)
        if recorded_hash != _stable_hash(unhashed):
            errors.append("audit_sha256 does not match payload")
    else:
        errors.append("audit_sha256 is missing")
    if payload.get("label_inputs") != []:
        errors.append("label inputs are not empty")
    recorded = set(payload.get("forbidden_label_fields", ()))
    missing = set(FORBIDDEN_LABEL_FIELDS) - recorded
    if missing:
        errors.append(f"forbidden label fields missing: {sorted(missing)}")
    records = payload.get("records")
    rankings = payload.get("rankings")
    if not isinstance(records, list) or not isinstance(rankings, dict):
        return errors + ["records/rankings are malformed"]
    labels = [str(item.get("cell")) for item in records if isinstance(item, Mapping)]
    if len(labels) != len(set(labels)):
        errors.append("duplicate formula record cells")
    expected = set(labels)
    for channel in ("combined", "peer", "role", "impact"):
        values = rankings.get(channel)
        if not isinstance(values, list) or set(map(str, values)) != expected or len(values) != len(expected):
            errors.append(f"{channel} ranking is incomplete or duplicated")
    for item in records:
        if not isinstance(item, Mapping):
            errors.append("formula record is not an object")
            continue
        if set(item) & set(FORBIDDEN_LABEL_FIELDS):
            errors.append(f"forbidden label field leaked into record {item.get('cell')}")
        status = item.get("status")
        if status not in {"evidence_supported", "ambiguous", "unsupported", "impact_only"}:
            errors.append(f"invalid status for {item.get('cell')}")
    return errors


__all__ = [
    "FORBIDDEN_LABEL_FIELDS",
    "MODEL_VERSION",
    "PROTOCOL",
    "SignalAuditConfig",
    "audit_workbook",
    "validate_label_free_output",
]
