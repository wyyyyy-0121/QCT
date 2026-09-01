"""Low-complexity V4 residual risk controller primitives.

The controller never changes V4 positions one through four.  It estimates the
utility of moving one frozen peer-review candidate into position five and may
abstain by retaining V4 unchanged.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np


CHANNELS = ("peer", "combined", "role", "impact")
ATOMIC_NUMERIC = (
    "equivalence_class_size",
    "region_size",
    "precedent_count",
    "dependent_count",
    "peer_count_row",
    "peer_count_column",
    "peer_count_local",
    "peer_count_role",
    "peer_formula_count",
    "formula_family_count",
    "alternative_support",
    "second_alternative_support",
    "independent_support",
    "alternative_margin",
    "peer_disagreement",
    "role_outlier_score",
    "competition_score",
    "defect_score",
    "evidence_tier",
    "impact_only",
    "descendant_count",
    "sink_count",
    "max_depth",
    "weighted_reach",
    "impact_score",
    "truncated",
)
ATOMIC_STATUSES = ("unsupported", "ambiguous", "evidence_supported", "impact_only")
V4_NUMERIC = (
    "formula_anomaly",
    "graph_anomaly",
    "behavior_anomaly",
    "legacy_prior",
    "rrf_score",
    "consensus_rrf_score",
    "candidate_support",
    "candidate_quality",
    "local_gain",
    "global_harm",
    "candidate_delta",
    "intervention_responsibility_gain",
)
V4_STATUSES = (
    "strong_counterfactual",
    "moderate_counterfactual",
    "pattern_only",
    "uncalibrated_candidate",
    "no_candidate",
    "not_intervened",
)


def _continuous_feature_names() -> tuple[str, ...]:
    names: list[str] = []
    names.extend(f"rr_{channel}" for channel in CHANNELS)
    names.append("rr_v4")
    for channel in CHANNELS:
        names.extend((f"score_{channel}", f"margin_{channel}"))
    names.extend(f"atomic_{name}" for name in ATOMIC_NUMERIC)
    names.extend(f"v4_{name}" for name in V4_NUMERIC)
    names.extend((
        "workbook_log1p_formula_count",
        "workbook_parseable_ratio",
        "workbook_visible_ratio",
        "workbook_unsupported_ratio",
        "workbook_log1p_region_count",
        "candidate_region_ratio",
        "candidate_equivalence_ratio",
        "candidate_peer_formula_ratio",
        "candidate_formula_family_ratio",
    ))
    difference_bases = (
        *(f"rr_{channel}" for channel in CHANNELS),
        "rr_v4",
        *(f"score_{channel}" for channel in CHANNELS),
        *(f"atomic_{name}" for name in ATOMIC_NUMERIC),
        *(f"v4_{name}" for name in V4_NUMERIC),
    )
    names.extend(f"candidate_minus_fifth_{name}" for name in difference_bases)
    return tuple(names)


CONTINUOUS_FEATURES = _continuous_feature_names()
BINARY_FEATURES = (
    "top5_combined",
    "top5_role",
    "top5_impact",
    "top5_consensus_count",
    *(f"atomic_status_{status}" for status in ATOMIC_STATUSES),
    *(f"v4_status_{status}" for status in V4_STATUSES),
)
MODEL_FEATURES = (
    *CONTINUOUS_FEATURES,
    *BINARY_FEATURES,
    *(f"missing_{name}" for name in CONTINUOUS_FEATURES),
)


def structure_fold(structure_group: str) -> int:
    digest = hashlib.sha256(structure_group.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 5


def _number(value: object) -> float:
    if value is None or value == "":
        return math.nan
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def _rank_maps(audit: Mapping[str, object]) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, Mapping[str, object]]]]:
    ranks: dict[str, dict[str, int]] = {}
    records: dict[str, dict[str, Mapping[str, object]]] = {}
    rankings = audit["rankings"]
    rank_records = audit["rank_records"]
    for channel in CHANNELS:
        ranks[channel] = {
            str(cell): index + 1
            for index, cell in enumerate(rankings[channel])
        }
        records[channel] = {
            str(row["cell"]): row for row in rank_records[channel]
        }
    return ranks, records


def _channel_values(
    cell: str,
    channel: str,
    ranks: Mapping[str, Mapping[str, int]],
    records: Mapping[str, Mapping[str, Mapping[str, object]]],
) -> tuple[float, float, float]:
    rank = ranks[channel].get(cell)
    reciprocal = 1.0 / rank if rank else math.nan
    record = records[channel].get(cell)
    if record is None:
        return reciprocal, math.nan, math.nan
    score = _number(record.get("score"))
    next_score = 0.0
    next_rank = int(record["rank"]) + 1
    if next_rank <= len(records[channel]):
        by_rank = {int(row["rank"]): row for row in records[channel].values()}
        next_score = _number(by_rank[next_rank].get("score"))
    margin = max(0.0, score - next_score) if math.isfinite(score) and math.isfinite(next_score) else math.nan
    return reciprocal, score, margin


def _atomic_values(record: Mapping[str, object]) -> dict[str, float]:
    peers = record.get("peer_counts")
    peers = peers if isinstance(peers, dict) else {}
    output = {
        f"atomic_{name}": _number(record.get(name))
        for name in ATOMIC_NUMERIC
        if not name.startswith("peer_count_")
    }
    for direction in ("row", "column", "local", "role"):
        output[f"atomic_peer_count_{direction}"] = _number(peers.get(direction))
    return output


def _v4_values(record: Mapping[str, object] | None) -> dict[str, float]:
    evidence = record.get("evidence", {}) if record else {}
    if not isinstance(evidence, dict):
        evidence = {}
    return {f"v4_{name}": _number(evidence.get(name)) for name in V4_NUMERIC}


def candidate_feature_map(
    candidate: str,
    audit: Mapping[str, object],
    v4_ranking: Sequence[Mapping[str, object]],
) -> dict[str, float]:
    """Build the exact preregistered label-free feature map for one candidate."""

    ranks, records = _rank_maps(audit)
    atomic_by_cell = {
        str(row["cell"]): row for row in audit["records"]
    }
    v4_by_cell = {str(row["cell"]): row for row in v4_ranking}
    if candidate not in atomic_by_cell or candidate not in v4_by_cell:
        raise ValueError(f"candidate missing complete evidence: {candidate}")
    fifth = str(v4_ranking[4]["cell"]) if len(v4_ranking) >= 5 else None

    def raw_values(cell: str) -> dict[str, float]:
        output: dict[str, float] = {}
        for channel in CHANNELS:
            reciprocal, score, margin = _channel_values(cell, channel, ranks, records)
            output[f"rr_{channel}"] = reciprocal
            output[f"score_{channel}"] = score
            output[f"margin_{channel}"] = margin
        v4_record = v4_by_cell.get(cell)
        v4_rank = int(v4_record["rank"]) if v4_record else 0
        output["rr_v4"] = 1.0 / v4_rank if v4_rank else math.nan
        output.update(_atomic_values(atomic_by_cell[cell]))
        output.update(_v4_values(v4_record))
        return output

    values = raw_values(candidate)
    formula_count = max(1.0, _number(audit.get("formula_count")))
    values.update({
        "top5_combined": float(ranks["combined"].get(candidate, 10**9) <= 5),
        "top5_role": float(ranks["role"].get(candidate, 10**9) <= 5),
        "top5_impact": float(ranks["impact"].get(candidate, 10**9) <= 5),
    })
    values["top5_consensus_count"] = sum(
        values[name] for name in ("top5_combined", "top5_role", "top5_impact")
    )
    atomic_status = str(atomic_by_cell[candidate].get("status", ""))
    if atomic_status not in ATOMIC_STATUSES:
        raise ValueError(f"unknown atomic status: {atomic_status}")
    for status in ATOMIC_STATUSES:
        values[f"atomic_status_{status}"] = float(atomic_status == status)
    v4_evidence = v4_by_cell[candidate].get("evidence", {})
    v4_status = str(v4_evidence.get("diagnostic_status", ""))
    if v4_status not in V4_STATUSES:
        raise ValueError(f"unknown V4 status: {v4_status}")
    for status in V4_STATUSES:
        values[f"v4_status_{status}"] = float(v4_status == status)
    values.update({
        "workbook_log1p_formula_count": math.log1p(formula_count),
        "workbook_parseable_ratio": _number(audit.get("parseable_formula_count")) / formula_count,
        "workbook_visible_ratio": _number(audit.get("visible_formula_count")) / formula_count,
        "workbook_unsupported_ratio": _number(audit.get("unsupported_formula_count")) / formula_count,
        "workbook_log1p_region_count": math.log1p(max(0.0, _number(audit.get("region_count")))),
        "candidate_region_ratio": _number(atomic_by_cell[candidate].get("region_size")) / formula_count,
        "candidate_equivalence_ratio": _number(atomic_by_cell[candidate].get("equivalence_class_size")) / formula_count,
        "candidate_peer_formula_ratio": _number(atomic_by_cell[candidate].get("peer_formula_count")) / formula_count,
        "candidate_formula_family_ratio": _number(atomic_by_cell[candidate].get("formula_family_count")) / formula_count,
    })
    fifth_values = raw_values(fifth) if fifth else {name: math.nan for name in values}
    difference_bases = (
        *(f"rr_{channel}" for channel in CHANNELS),
        "rr_v4",
        *(f"score_{channel}" for channel in CHANNELS),
        *(f"atomic_{name}" for name in ATOMIC_NUMERIC),
        *(f"v4_{name}" for name in V4_NUMERIC),
    )
    for name in difference_bases:
        left, right = values.get(name, math.nan), fifth_values.get(name, math.nan)
        values[f"candidate_minus_fifth_{name}"] = (
            left - right if math.isfinite(left) and math.isfinite(right) else math.nan
        )
    missing = sorted(set((*CONTINUOUS_FEATURES, *BINARY_FEATURES)) - set(values))
    if missing:
        raise ValueError(f"feature extraction incomplete: {missing}")
    return values


def peer_candidates(audit: Mapping[str, object], v4_ranking: Sequence[Mapping[str, object]]) -> list[str]:
    blocked = {str(row["cell"]) for row in v4_ranking[:5]}
    result: list[str] = []
    for cell in audit["review_cells"]["peer"][:5]:
        cell = str(cell)
        if cell not in blocked and cell not in result:
            result.append(cell)
    return result


def guarded_candidate(
    candidate: str,
    audit: Mapping[str, object],
    *,
    revision: int,
) -> bool:
    if revision == 0:
        return True
    if revision != 1:
        raise ValueError(f"unknown V4-RRC revision: {revision}")
    atomic = {str(row["cell"]): row for row in audit["records"]}[candidate]
    rankings = audit["rankings"]
    return (
        atomic.get("status") == "evidence_supported"
        and (
            candidate in rankings["combined"][:5]
            or candidate in rankings["role"][:5]
        )
    )


@dataclass(frozen=True)
class Preprocessor:
    medians: tuple[float, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    continuous_features: tuple[str, ...] = CONTINUOUS_FEATURES
    binary_features: tuple[str, ...] = BINARY_FEATURES

    def transform_one(self, values: Mapping[str, float]) -> np.ndarray:
        continuous = np.asarray(
            [values[name] for name in self.continuous_features], dtype=np.float64,
        )
        missing = ~np.isfinite(continuous)
        imputed = np.where(missing, np.asarray(self.medians), continuous)
        standardized = (imputed - np.asarray(self.means)) / np.asarray(self.scales)
        binary = np.asarray(
            [values[name] for name in self.binary_features], dtype=np.float64,
        )
        return np.concatenate((standardized, binary, missing.astype(np.float64)))

    def to_dict(self) -> dict[str, object]:
        model_features = (
            *self.continuous_features,
            *self.binary_features,
            *(f"missing_{name}" for name in self.continuous_features),
        )
        return {
            "continuous_features": list(self.continuous_features),
            "binary_features": list(self.binary_features),
            "model_features": list(model_features),
            "medians": list(self.medians),
            "means": list(self.means),
            "scales": list(self.scales),
        }


def fit_preprocessor(
    rows: Sequence[Mapping[str, float]],
    *,
    continuous_features: Sequence[str] = CONTINUOUS_FEATURES,
    binary_features: Sequence[str] = BINARY_FEATURES,
) -> Preprocessor:
    if not rows:
        raise ValueError("cannot fit preprocessor without rows")
    continuous_features = tuple(continuous_features)
    binary_features = tuple(binary_features)
    if (
        not continuous_features
        or len(continuous_features) != len(set(continuous_features))
        or len(binary_features) != len(set(binary_features))
        or set(continuous_features) & set(binary_features)
    ):
        raise ValueError("ridge feature names must be unique, disjoint, and include continuous data")
    matrix = np.asarray(
        [[row[name] for name in continuous_features] for row in rows],
        dtype=np.float64,
    )
    medians = []
    for column in matrix.T:
        finite = column[np.isfinite(column)]
        medians.append(float(np.median(finite)) if finite.size else 0.0)
    imputed = np.where(np.isfinite(matrix), matrix, np.asarray(medians))
    means = imputed.mean(axis=0)
    scales = imputed.std(axis=0)
    scales[scales == 0.0] = 1.0
    return Preprocessor(
        tuple(medians),
        tuple(means.tolist()),
        tuple(scales.tolist()),
        continuous_features=continuous_features,
        binary_features=binary_features,
    )


@dataclass(frozen=True)
class RidgeModel:
    preprocessor: Preprocessor
    intercept: float
    coefficients: tuple[float, ...]
    ridge_lambda: float = 1.0

    def predict(self, values: Mapping[str, float]) -> float:
        vector = self.preprocessor.transform_one(values)
        return self.intercept + float(vector @ np.asarray(self.coefficients))

    def to_dict(self) -> dict[str, object]:
        return {
            "family": "linear_l2_ridge_closed_form_numpy",
            "ridge_lambda": self.ridge_lambda,
            "intercept": self.intercept,
            "coefficients": list(self.coefficients),
            "preprocessor": self.preprocessor.to_dict(),
        }


def fit_ridge(
    feature_rows: Sequence[Mapping[str, float]],
    targets: Sequence[float],
    weights: Sequence[float],
    *,
    ridge_lambda: float = 1.0,
    continuous_features: Sequence[str] = CONTINUOUS_FEATURES,
    binary_features: Sequence[str] = BINARY_FEATURES,
) -> RidgeModel:
    if not (len(feature_rows) == len(targets) == len(weights)) or not feature_rows:
        raise ValueError("ridge inputs must be nonempty and equally sized")
    preprocessor = fit_preprocessor(
        feature_rows,
        continuous_features=continuous_features,
        binary_features=binary_features,
    )
    x = np.vstack([preprocessor.transform_one(row) for row in feature_rows])
    x = np.column_stack((np.ones(len(x), dtype=np.float64), x))
    y = np.asarray(targets, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    if np.any(w <= 0.0) or not np.all(np.isfinite(w)):
        raise ValueError("ridge weights must be finite and positive")
    root_w = np.sqrt(w)
    xw = x * root_w[:, None]
    yw = y * root_w
    penalty = np.eye(x.shape[1], dtype=np.float64) * ridge_lambda
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(xw.T @ xw + penalty, xw.T @ yw)
    if not np.all(np.isfinite(coefficients)):
        raise ValueError("ridge fit produced non-finite coefficients")
    return RidgeModel(
        preprocessor=preprocessor,
        intercept=float(coefficients[0]),
        coefficients=tuple(float(value) for value in coefficients[1:]),
        ridge_lambda=ridge_lambda,
    )


def residual_utility(
    case_kind: str,
    source_cells: Sequence[str],
    v4_ranking: Sequence[str],
    candidate: str,
) -> float:
    if case_kind == "control":
        return -2.0
    sources = set(source_cells)
    before = bool(sources & set(v4_ranking[:5]))
    after = bool(sources & set((*v4_ranking[:4], candidate)))
    if after and not before:
        return 1.0
    if before and not after:
        return -4.0
    return 0.0


def rerank(v4_ranking: Sequence[str], candidate: str | None) -> list[str]:
    result = list(v4_ranking)
    if candidate is None or len(result) < 5 or candidate in result[:5]:
        return result
    if candidate not in result:
        raise ValueError(f"candidate absent from complete V4 ranking: {candidate}")
    result.remove(candidate)
    result.insert(4, candidate)
    return result
