"""Frozen label-free feature views for the Peer Repair learnability audit."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from .v4_rrc import (
    ATOMIC_STATUSES,
    BINARY_FEATURES,
    CONTINUOUS_FEATURES,
)

VIEW_ORDER = ("v4", "atomic", "closure", "responsibility", "combined")

V4_CONTINUOUS_FEATURES = tuple(
    name for name in CONTINUOUS_FEATURES
    if (
        name in {"rr_v4", "candidate_minus_fifth_rr_v4"}
        or name.startswith(("v4_", "candidate_minus_fifth_v4_"))
    )
)
V4_BINARY_FEATURES = tuple(
    name for name in BINARY_FEATURES if name.startswith("v4_status_")
)
ATOMIC_CONTINUOUS_FEATURES = tuple(
    name for name in CONTINUOUS_FEATURES if name not in V4_CONTINUOUS_FEATURES
)
ATOMIC_BINARY_FEATURES = tuple(
    name for name in BINARY_FEATURES if name not in V4_BINARY_FEATURES
)

CLOSURE_CANDIDATE_NUMERIC = (
    "evidence_tier_before",
    "evidence_tier_after",
    "peer_rank_before",
    "peer_rank_after",
    "peer_rank_change",
    "defect_score_before",
    "defect_score_after",
    "defect_score_drop",
    "peer_disagreement_before",
    "peer_disagreement_after",
    "peer_disagreement_drop",
    "alternative_support_before",
    "alternative_support_after",
    "alternative_support_drop",
    "independent_support_before",
    "independent_support_after",
    "independent_support_drop",
    "alternative_margin_before",
    "alternative_margin_after",
    "alternative_margin_drop",
    "competition_score_before",
    "competition_score_after",
    "competition_score_drop",
    "role_outlier_score_before",
    "role_outlier_score_after",
    "role_outlier_score_drop",
)
CLOSURE_GLOBAL_NUMERIC = (
    "formula_count",
    "defect_score_sum_before",
    "defect_score_sum_after",
    "defect_score_sum_drop",
    "other_new_supported_count",
    "other_new_actionable_count",
    "other_defect_worsened_count",
    "other_defect_improved_count",
    "maximum_other_defect_increase",
    "evidence_supported_count_before",
    "evidence_supported_count_after",
    "evidence_supported_count_drop",
    "ambiguous_count_before",
    "ambiguous_count_after",
    "ambiguous_count_drop",
    "unsupported_count_before",
    "unsupported_count_after",
    "unsupported_count_drop",
    "impact_only_count_before",
    "impact_only_count_after",
    "impact_only_count_drop",
)
CLOSURE_CANDIDATE_FLAGS = (
    "peer_priority_decreased",
    "peer_review_before",
    "peer_review_after",
    "actionable_before",
    "actionable_after",
    "actionable_status_resolved",
    "atomic_anomaly_before",
    "atomic_anomaly_after",
    "anomaly_disappeared",
    "local_consistency_recovered",
)
CLOSURE_CONTINUOUS_FEATURES = (
    "closure_candidate_v4_rank",
    *(f"closure_candidate_{name}" for name in CLOSURE_CANDIDATE_NUMERIC),
    *(f"closure_global_{name}" for name in CLOSURE_GLOBAL_NUMERIC),
)
CLOSURE_BINARY_FEATURES = (
    "closure_repair_hypothesis_available",
    "closure_repair_executed",
    *(f"closure_status_before_{status}" for status in ATOMIC_STATUSES),
    *(f"closure_status_after_{status}" for status in ATOMIC_STATUSES),
    *(f"closure_candidate_{name}" for name in CLOSURE_CANDIDATE_FLAGS),
    "closure_global_no_new_actionable_anomaly",
    "closure_round_trip_reversible",
    "closure_repair_closes_without_new_anomaly",
)

RESPONSIBILITY_NUMERIC = (
    "scope_formula_count",
    "local_energy_before",
    "local_energy_after",
    "local_gain",
    "local_harm",
    "global_energy_before",
    "global_energy_after",
    "global_harm",
    "side_effect",
    "exact_repair_delta",
    "downstream_formula_count",
    "comparable_downstream_formula_count",
    "changed_downstream_formula_count",
    "visible_sink_count",
    "reachable_visible_sink_count",
    "comparable_reachable_visible_sink_count",
    "changed_reachable_visible_sink_count",
    "baseline_evaluation_error_count",
    "repaired_evaluation_error_count",
    "new_evaluation_error_count",
    "resolved_evaluation_error_count",
)
RESPONSIBILITY_FLAGS = (
    "positive_exact_repair_delta",
    "changed_reachable_visible_sink",
    "key_output_available",
    "key_output_reachable",
    "key_output_comparable",
    "key_output_changed",
    "no_new_evaluation_errors",
    "responsibility_pass",
)
RESPONSIBILITY_CONTINUOUS_FEATURES = (
    "responsibility_candidate_v4_rank",
    *(f"responsibility_{name}" for name in RESPONSIBILITY_NUMERIC),
)
RESPONSIBILITY_BINARY_FEATURES = (
    "responsibility_repair_hypothesis_available",
    "responsibility_evaluated",
    *(f"responsibility_{name}" for name in RESPONSIBILITY_FLAGS),
)


@dataclass(frozen=True)
class FeatureView:
    continuous: tuple[str, ...]
    binary: tuple[str, ...]

    @property
    def model_feature_count(self) -> int:
        return 2 * len(self.continuous) + len(self.binary)


FEATURE_VIEWS = {
    "v4": FeatureView(V4_CONTINUOUS_FEATURES, V4_BINARY_FEATURES),
    "atomic": FeatureView(ATOMIC_CONTINUOUS_FEATURES, ATOMIC_BINARY_FEATURES),
    "closure": FeatureView(CLOSURE_CONTINUOUS_FEATURES, CLOSURE_BINARY_FEATURES),
    "responsibility": FeatureView(
        RESPONSIBILITY_CONTINUOUS_FEATURES,
        RESPONSIBILITY_BINARY_FEATURES,
    ),
    "combined": FeatureView(
        (
            *V4_CONTINUOUS_FEATURES,
            *ATOMIC_CONTINUOUS_FEATURES,
            *CLOSURE_CONTINUOUS_FEATURES,
            *RESPONSIBILITY_CONTINUOUS_FEATURES,
        ),
        (
            *V4_BINARY_FEATURES,
            *ATOMIC_BINARY_FEATURES,
            *CLOSURE_BINARY_FEATURES,
            *RESPONSIBILITY_BINARY_FEATURES,
        ),
    ),
}


def _number(row: Mapping[str, object], field: str) -> float:
    value = row.get(field)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"learnability numeric feature is invalid: {field}")
    return float(value)


def _flag(row: Mapping[str, object], field: str) -> float:
    value = row.get(field)
    if not isinstance(value, bool):
        raise TypeError(f"learnability boolean feature is invalid: {field}")
    return float(value)


def closure_feature_map(probe: Mapping[str, object]) -> dict[str, float]:
    closure = probe.get("closure")
    repair_available = _flag(probe, "repair_hypothesis_available")
    repair_executed = _flag(probe, "repair_executed")
    if repair_executed != 1.0 or not isinstance(closure, Mapping):
        raise ValueError("learnability candidate requires an executed closure probe")
    candidate = closure.get("candidate")
    global_metrics = closure.get("global")
    if not isinstance(candidate, Mapping) or not isinstance(global_metrics, Mapping):
        raise TypeError("closure metrics are malformed")
    output = {
        "closure_candidate_v4_rank": _number(probe, "candidate_v4_rank"),
        "closure_repair_hypothesis_available": repair_available,
        "closure_repair_executed": repair_executed,
    }
    for name in CLOSURE_CANDIDATE_NUMERIC:
        output[f"closure_candidate_{name}"] = _number(candidate, name)
    for name in CLOSURE_GLOBAL_NUMERIC:
        output[f"closure_global_{name}"] = _number(global_metrics, name)
    before = str(candidate.get("status_before", ""))
    after = str(candidate.get("status_after", ""))
    if before not in ATOMIC_STATUSES or after not in ATOMIC_STATUSES:
        raise ValueError("closure candidate status is invalid")
    for status in ATOMIC_STATUSES:
        output[f"closure_status_before_{status}"] = float(before == status)
        output[f"closure_status_after_{status}"] = float(after == status)
    for name in CLOSURE_CANDIDATE_FLAGS:
        output[f"closure_candidate_{name}"] = _flag(candidate, name)
    output["closure_global_no_new_actionable_anomaly"] = _flag(
        global_metrics, "no_new_actionable_anomaly",
    )
    output["closure_round_trip_reversible"] = _flag(
        closure, "round_trip_reversible",
    )
    output["closure_repair_closes_without_new_anomaly"] = _flag(
        closure, "repair_closes_without_new_anomaly",
    )
    return output


def responsibility_feature_map(probe: Mapping[str, object]) -> dict[str, float]:
    responsibility = probe.get("responsibility")
    repair_available = _flag(probe, "repair_hypothesis_available")
    evaluated = _flag(probe, "responsibility_evaluated")
    if (
        evaluated != 1.0
        or not isinstance(responsibility, Mapping)
    ):
        raise ValueError("learnability candidate requires evaluated responsibility")
    output = {
        "responsibility_candidate_v4_rank": _number(probe, "candidate_v4_rank"),
        "responsibility_repair_hypothesis_available": repair_available,
        "responsibility_evaluated": evaluated,
    }
    for name in RESPONSIBILITY_NUMERIC:
        output[f"responsibility_{name}"] = _number(responsibility, name)
    for name in RESPONSIBILITY_FLAGS:
        output[f"responsibility_{name}"] = _flag(responsibility, name)
    return output


def build_feature_views(
    base: Mapping[str, float],
    closure_probe: Mapping[str, object],
    responsibility_probe: Mapping[str, object],
) -> dict[str, dict[str, float]]:
    """Return all preregistered views without identity or label fields."""

    closure = closure_feature_map(closure_probe)
    responsibility = responsibility_feature_map(responsibility_probe)
    complete = {**base, **closure, **responsibility}
    result: dict[str, dict[str, float]] = {}
    for name in VIEW_ORDER:
        view = FEATURE_VIEWS[name]
        expected = (*view.continuous, *view.binary)
        missing = [field for field in expected if field not in complete]
        if missing:
            raise ValueError(f"learnability feature view {name} is incomplete: {missing}")
        result[name] = {field: float(complete[field]) for field in expected}
    return result


__all__ = [
    "FEATURE_VIEWS",
    "VIEW_ORDER",
    "FeatureView",
    "build_feature_views",
    "closure_feature_map",
    "responsibility_feature_map",
]
