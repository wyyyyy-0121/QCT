"""Atomic Evidence Transfer Ranker feature and ranking primitives."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .v4_rrc import ATOMIC_NUMERIC, ATOMIC_STATUSES, CHANNELS, RidgeModel

CHANNEL_CONTINUOUS_FEATURES = (
    *(f"rr_{channel}" for channel in CHANNELS),
    *(name for channel in CHANNELS for name in (f"score_{channel}", f"margin_{channel}")),
)
ATOMIC_CONTINUOUS_FEATURES = tuple(f"atomic_{name}" for name in ATOMIC_NUMERIC)
SCALE_CONTINUOUS_FEATURES = (
    "workbook_log1p_formula_count",
    "workbook_parseable_ratio",
    "workbook_visible_ratio",
    "workbook_unsupported_ratio",
    "workbook_log1p_region_count",
    "candidate_region_ratio",
    "candidate_equivalence_ratio",
    "candidate_peer_formula_ratio",
    "candidate_formula_family_ratio",
)
CHANNEL_DISCRETE_FEATURES = (
    "top5_combined",
    "top5_role",
    "top5_impact",
    "top5_consensus_count",
)
STATUS_FEATURES = tuple(f"atomic_status_{status}" for status in ATOMIC_STATUSES)


@dataclass(frozen=True)
class AETRView:
    continuous: tuple[str, ...]
    discrete: tuple[str, ...]
    weighting: str = "structure_unit_class_balanced"

    @property
    def model_feature_count(self) -> int:
        return 2 * len(self.continuous) + len(self.discrete)


AETR_VIEWS = {
    "full": AETRView(
        (
            *CHANNEL_CONTINUOUS_FEATURES,
            *ATOMIC_CONTINUOUS_FEATURES,
            *SCALE_CONTINUOUS_FEATURES,
        ),
        (*CHANNEL_DISCRETE_FEATURES, *STATUS_FEATURES),
    ),
    "rank_only": AETRView(
        CHANNEL_CONTINUOUS_FEATURES,
        CHANNEL_DISCRETE_FEATURES,
    ),
    "evidence_only": AETRView(
        (*ATOMIC_CONTINUOUS_FEATURES, *SCALE_CONTINUOUS_FEATURES),
        STATUS_FEATURES,
    ),
    "no_workbook_scale": AETRView(
        (*CHANNEL_CONTINUOUS_FEATURES, *ATOMIC_CONTINUOUS_FEATURES),
        (*CHANNEL_DISCRETE_FEATURES, *STATUS_FEATURES),
    ),
    "formula_micro_weighting": AETRView(
        (
            *CHANNEL_CONTINUOUS_FEATURES,
            *ATOMIC_CONTINUOUS_FEATURES,
            *SCALE_CONTINUOUS_FEATURES,
        ),
        (*CHANNEL_DISCRETE_FEATURES, *STATUS_FEATURES),
        weighting="formula_micro",
    ),
}
VIEW_ORDER = tuple(AETR_VIEWS)


def _number(value: object) -> float:
    if value is None or value == "":
        return math.nan
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def _rank_data(
    audit: Mapping[str, object],
) -> tuple[
    dict[str, dict[str, int]],
    dict[str, dict[str, Mapping[str, object]]],
]:
    rankings = audit.get("rankings")
    rank_records = audit.get("rank_records")
    if not isinstance(rankings, Mapping) or not isinstance(rank_records, Mapping):
        raise TypeError("AETR source rankings are malformed")
    ranks: dict[str, dict[str, int]] = {}
    records: dict[str, dict[str, Mapping[str, object]]] = {}
    for channel in CHANNELS:
        ranking = rankings.get(channel)
        rows = rank_records.get(channel)
        if not isinstance(ranking, list) or not isinstance(rows, list):
            raise TypeError(f"AETR {channel} ranking is malformed")
        ranks[channel] = {
            str(cell): index + 1 for index, cell in enumerate(ranking)
        }
        by_cell: dict[str, Mapping[str, object]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise TypeError(f"AETR {channel} rank record is malformed")
            cell = str(row.get("cell", ""))
            if not cell or cell in by_cell:
                raise ValueError(f"AETR {channel} rank record has duplicate cells")
            by_cell[cell] = row
        if set(by_cell) != set(ranks[channel]):
            raise ValueError(f"AETR {channel} rank records differ from ranking")
        records[channel] = by_cell
    inventory = set(ranks[CHANNELS[0]])
    if any(set(ranks[channel]) != inventory for channel in CHANNELS[1:]):
        raise ValueError("AETR channel formula inventories differ")
    return ranks, records


def _channel_values(
    cell: str,
    channel: str,
    ranks: Mapping[str, Mapping[str, int]],
    records: Mapping[str, Mapping[str, Mapping[str, object]]],
) -> tuple[float, float, float]:
    rank = ranks[channel].get(cell)
    if rank is None:
        raise ValueError(f"AETR formula is absent from {channel} ranking")
    score = _number(records[channel][cell].get("score"))
    next_score = 0.0
    if rank < len(records[channel]):
        by_rank = {
            int(row["rank"]): row for row in records[channel].values()
        }
        next_score = _number(by_rank[rank + 1].get("score"))
    margin = (
        max(0.0, score - next_score)
        if math.isfinite(score) and math.isfinite(next_score)
        else math.nan
    )
    return 1.0 / rank, score, margin


def _atomic_values(record: Mapping[str, object]) -> dict[str, float]:
    peer_counts = record.get("peer_counts")
    peer_counts = peer_counts if isinstance(peer_counts, Mapping) else {}
    output = {
        f"atomic_{name}": _number(record.get(name))
        for name in ATOMIC_NUMERIC
        if not name.startswith("peer_count_")
    }
    for direction in ("row", "column", "local", "role"):
        output[f"atomic_peer_count_{direction}"] = _number(
            peer_counts.get(direction),
        )
    return output


def workbook_feature_maps(
    audit: Mapping[str, object],
) -> tuple[tuple[str, ...], dict[str, dict[str, float]]]:
    """Build the complete AETR input without V4 or identity features."""

    audit_records = audit.get("records")
    if not isinstance(audit_records, list):
        raise TypeError("AETR atomic records are malformed")
    records: dict[str, Mapping[str, object]] = {}
    inventory: list[str] = []
    for row in audit_records:
        if not isinstance(row, Mapping):
            raise TypeError("AETR atomic record is malformed")
        cell = str(row.get("cell", ""))
        if not cell or cell in records:
            raise ValueError("AETR atomic inventory has empty or duplicate cells")
        inventory.append(cell)
        records[cell] = row
    ranks, rank_records = _rank_data(audit)
    if set(inventory) != set(ranks[CHANNELS[0]]):
        raise ValueError("AETR atomic and ranking inventories differ")
    formula_count = max(1.0, _number(audit.get("formula_count")))
    shared_scale = {
        "workbook_log1p_formula_count": math.log1p(formula_count),
        "workbook_parseable_ratio": _number(audit.get("parseable_formula_count")) / formula_count,
        "workbook_visible_ratio": _number(audit.get("visible_formula_count")) / formula_count,
        "workbook_unsupported_ratio": _number(audit.get("unsupported_formula_count")) / formula_count,
        "workbook_log1p_region_count": math.log1p(
            max(0.0, _number(audit.get("region_count"))),
        ),
    }
    output: dict[str, dict[str, float]] = {}
    for cell in inventory:
        record = records[cell]
        values: dict[str, float] = {}
        for channel in CHANNELS:
            reciprocal, score, margin = _channel_values(
                cell, channel, ranks, rank_records,
            )
            values[f"rr_{channel}"] = reciprocal
            values[f"score_{channel}"] = score
            values[f"margin_{channel}"] = margin
        values.update(_atomic_values(record))
        values.update(shared_scale)
        values.update({
            "candidate_region_ratio": _number(record.get("region_size")) / formula_count,
            "candidate_equivalence_ratio": (
                _number(record.get("equivalence_class_size")) / formula_count
            ),
            "candidate_peer_formula_ratio": (
                _number(record.get("peer_formula_count")) / formula_count
            ),
            "candidate_formula_family_ratio": (
                _number(record.get("formula_family_count")) / formula_count
            ),
            "top5_combined": float(ranks["combined"][cell] <= 5),
            "top5_role": float(ranks["role"][cell] <= 5),
            "top5_impact": float(ranks["impact"][cell] <= 5),
        })
        values["top5_consensus_count"] = sum(
            values[name]
            for name in ("top5_combined", "top5_role", "top5_impact")
        )
        status = str(record.get("status", ""))
        if status not in ATOMIC_STATUSES:
            raise ValueError(f"AETR atomic status is invalid: {status}")
        for allowed in ATOMIC_STATUSES:
            values[f"atomic_status_{allowed}"] = float(status == allowed)
        expected = {
            *AETR_VIEWS["full"].continuous,
            *AETR_VIEWS["full"].discrete,
        }
        missing = sorted(expected - set(values))
        if missing:
            raise ValueError(f"AETR feature extraction is incomplete: {missing}")
        output[cell] = values
    return tuple(inventory), output


def ranking_from_model(
    model: RidgeModel,
    audit: Mapping[str, object],
    inventory: Sequence[str],
    features: Mapping[str, Mapping[str, float]],
) -> tuple[list[str], dict[str, float]]:
    """Score every formula and use only label-free channel ranks for exact ties."""

    ranks, _ = _rank_data(audit)
    inventory_order = {cell: index for index, cell in enumerate(inventory)}
    scores = {cell: model.predict(features[cell]) for cell in inventory}
    ranking = sorted(
        inventory,
        key=lambda cell: (
            -scores[cell],
            ranks["peer"][cell],
            ranks["combined"][cell],
            ranks["role"][cell],
            ranks["impact"][cell],
            inventory_order[cell],
        ),
    )
    return ranking, scores


__all__ = [
    "AETR_VIEWS",
    "VIEW_ORDER",
    "AETRView",
    "ranking_from_model",
    "workbook_feature_maps",
]
