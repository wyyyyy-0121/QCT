"""Label-free counterfactual repair-closure evidence for one Peer candidate.

The probe changes one formula only in memory, re-runs the frozen atomic-signal
audit, and emits aggregate deltas.  It deliberately omits cell addresses,
formula text, fingerprints, roles, workbook values, and revealed labels.
"""

from __future__ import annotations

import math
import re
from typing import Mapping, Sequence

from .model_discovery import audit_workbook, validate_label_free_output
from .workbook import CellKey, WorkbookModel


PROTOCOL = "formulaguard_peer_repair_closure_v1"
MODEL_VERSION = "peer-repair-closure-label-free-v1"
CANDIDATE_POLICY = "peer_review_top1_outside_v4_top5"
REVIEW_BUDGET = 5
ACTIONABLE_STATUSES = frozenset({"evidence_supported", "ambiguous"})
FORBIDDEN_OUTPUT_FIELDS = frozenset({
    "cell",
    "cells",
    "formula",
    "formulas",
    "normalized_formula",
    "best_alternative",
    "fingerprint",
    "role_key",
    "support_cells",
    "source_cell",
    "source_cells",
    "correct_formula",
    "expected_output",
    "label_file",
    "label_row",
    "event_id",
    "case_kind",
    "cohort",
    "structure_group",
})
_CELL_LABEL = re.compile(r"(?:^|[^A-Za-z0-9_])[A-Za-z]{1,4}[1-9][0-9]*(?:$|[^A-Za-z0-9_])")
_AUDIT_PROJECTION_FIELDS = (
    "configuration",
    "configuration_sha256",
    "formula_count",
    "parseable_formula_count",
    "unsupported_formula_count",
    "visible_formula_count",
    "region_count",
    "region_sizes",
    "rankings",
    "rank_records",
    "review_cells",
    "records",
)


def _round(value: float) -> float:
    return round(float(value), 12)


def _record_map(audit: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    records = audit.get("records")
    if not isinstance(records, list):
        raise ValueError("peer audit records are malformed")
    result: dict[str, Mapping[str, object]] = {}
    for row in records:
        if not isinstance(row, Mapping):
            raise ValueError("peer audit record is malformed")
        label = str(row.get("cell", ""))
        if not label or label in result:
            raise ValueError("peer audit contains an empty or duplicate cell")
        result[label] = row
    return result


def _cell_key(label: str, model: WorkbookModel) -> CellKey:
    if "!" not in label:
        raise ValueError("peer candidate is not a sheet-qualified cell")
    sheet, address = label.rsplit("!", 1)
    key = (sheet, address)
    if key not in model.formulas:
        raise ValueError("peer candidate is absent from the workbook formula inventory")
    return key


def _clone_with_formula(
    model: WorkbookModel,
    key: CellKey,
    formula: str,
) -> WorkbookModel:
    formulas = dict(model.formulas)
    formulas[key] = formula
    return WorkbookModel(
        model.cells,
        formulas,
        source="",
        cell_visibility=model.cell_visibility,
        number_formats=model.number_formats,
        sheet_visibility=model.sheet_visibility,
    )


def _audit_projection(audit: Mapping[str, object]) -> dict[str, object]:
    return {field: audit.get(field) for field in _AUDIT_PROJECTION_FIELDS}


def _peer_rank(audit: Mapping[str, object], label: str) -> int:
    rankings = audit.get("rankings")
    if not isinstance(rankings, Mapping) or not isinstance(rankings.get("peer"), list):
        raise ValueError("peer audit ranking is malformed")
    try:
        return [str(value) for value in rankings["peer"]].index(label) + 1
    except ValueError as exc:
        raise ValueError("peer candidate is absent from the repaired ranking") from exc


def _status_counts(records: Mapping[str, Mapping[str, object]]) -> dict[str, int]:
    return {
        status: sum(str(row.get("status")) == status for row in records.values())
        for status in ("evidence_supported", "ambiguous", "unsupported", "impact_only")
    }


def _numeric(row: Mapping[str, object], field: str) -> float:
    value = row.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError(f"peer audit field is not finite numeric data: {field}")
    return float(value)


def _candidate_metrics(
    before_audit: Mapping[str, object],
    after_audit: Mapping[str, object],
    label: str,
) -> dict[str, object]:
    before_records = _record_map(before_audit)
    after_records = _record_map(after_audit)
    if set(before_records) != set(after_records) or label not in before_records:
        raise ValueError("repair changed the formula-cell inventory")
    before = before_records[label]
    after = after_records[label]
    before_status = str(before.get("status"))
    after_status = str(after.get("status"))
    alternative_support_before = _numeric(before, "alternative_support")
    alternative_support_after = _numeric(after, "alternative_support")
    disagreement_before = _numeric(before, "peer_disagreement")
    disagreement_after = _numeric(after, "peer_disagreement")
    atomic_anomaly_before = alternative_support_before > 0.0 and disagreement_before > 0.0
    atomic_anomaly_after = alternative_support_after > 0.0 and disagreement_after > 0.0
    before_rank = _peer_rank(before_audit, label)
    after_rank = _peer_rank(after_audit, label)
    before_review = before_audit.get("review_cells")
    after_review = after_audit.get("review_cells")
    if not isinstance(before_review, Mapping) or not isinstance(after_review, Mapping):
        raise ValueError("peer review sets are malformed")
    fields = (
        "defect_score",
        "peer_disagreement",
        "alternative_support",
        "independent_support",
        "alternative_margin",
        "competition_score",
        "role_outlier_score",
    )
    payload: dict[str, object] = {
        "status_before": before_status,
        "status_after": after_status,
        "evidence_tier_before": int(before.get("evidence_tier", 0)),
        "evidence_tier_after": int(after.get("evidence_tier", 0)),
        "peer_rank_before": before_rank,
        "peer_rank_after": after_rank,
        "peer_rank_change": after_rank - before_rank,
        "peer_priority_decreased": after_rank > before_rank,
        "peer_review_before": label in [str(value) for value in before_review.get("peer", [])],
        "peer_review_after": label in [str(value) for value in after_review.get("peer", [])],
        "actionable_before": before_status in ACTIONABLE_STATUSES,
        "actionable_after": after_status in ACTIONABLE_STATUSES,
        "actionable_status_resolved": (
            before_status in ACTIONABLE_STATUSES and after_status not in ACTIONABLE_STATUSES
        ),
        "atomic_anomaly_before": atomic_anomaly_before,
        "atomic_anomaly_after": atomic_anomaly_after,
        "anomaly_disappeared": atomic_anomaly_before and not atomic_anomaly_after,
    }
    for field in fields:
        before_value = _numeric(before, field)
        after_value = _numeric(after, field)
        payload[f"{field}_before"] = _round(before_value)
        payload[f"{field}_after"] = _round(after_value)
        payload[f"{field}_drop"] = _round(before_value - after_value)
    payload["local_consistency_recovered"] = bool(
        float(payload["defect_score_drop"]) > 0.0
        and float(payload["peer_disagreement_drop"]) > 0.0
        and float(payload["alternative_support_drop"]) > 0.0
    )
    return payload


def _global_metrics(
    before_audit: Mapping[str, object],
    after_audit: Mapping[str, object],
    label: str,
) -> dict[str, object]:
    before = _record_map(before_audit)
    after = _record_map(after_audit)
    if set(before) != set(after):
        raise ValueError("repair changed the formula-cell inventory")
    before_counts = _status_counts(before)
    after_counts = _status_counts(after)
    before_total = sum(_numeric(row, "defect_score") for row in before.values())
    after_total = sum(_numeric(row, "defect_score") for row in after.values())
    new_supported = 0
    new_actionable = 0
    worsened = 0
    improved = 0
    maximum_increase = 0.0
    for other in sorted(before):
        if other == label:
            continue
        before_status = str(before[other].get("status"))
        after_status = str(after[other].get("status"))
        if before_status != "evidence_supported" and after_status == "evidence_supported":
            new_supported += 1
        if before_status not in ACTIONABLE_STATUSES and after_status in ACTIONABLE_STATUSES:
            new_actionable += 1
        change = _numeric(after[other], "defect_score") - _numeric(before[other], "defect_score")
        if change > 1e-12:
            worsened += 1
            maximum_increase = max(maximum_increase, change)
        elif change < -1e-12:
            improved += 1
    payload: dict[str, object] = {
        "formula_count": len(before),
        "defect_score_sum_before": _round(before_total),
        "defect_score_sum_after": _round(after_total),
        "defect_score_sum_drop": _round(before_total - after_total),
        "other_new_supported_count": new_supported,
        "other_new_actionable_count": new_actionable,
        "other_defect_worsened_count": worsened,
        "other_defect_improved_count": improved,
        "maximum_other_defect_increase": _round(maximum_increase),
        "no_new_actionable_anomaly": new_actionable == 0,
    }
    for status in before_counts:
        payload[f"{status}_count_before"] = before_counts[status]
        payload[f"{status}_count_after"] = after_counts[status]
        payload[f"{status}_count_drop"] = before_counts[status] - after_counts[status]
    return payload


def select_peer_candidate(
    v4_ranking: Sequence[str],
    source_audit: Mapping[str, object],
) -> tuple[str | None, str]:
    """Select only Peer review Top-1, provided it is outside frozen V4 Top-5."""

    v4 = tuple(str(value) for value in v4_ranking)
    if len(v4) != len(set(v4)):
        raise ValueError("V4 ranking contains duplicate cells")
    reviews = source_audit.get("review_cells")
    rankings = source_audit.get("rankings")
    if (
        not isinstance(reviews, Mapping)
        or not isinstance(reviews.get("peer"), list)
        or not isinstance(rankings, Mapping)
        or not isinstance(rankings.get("peer"), list)
    ):
        raise ValueError("peer review set is malformed")
    peer = tuple(str(value) for value in reviews["peer"])
    peer_inventory = tuple(str(value) for value in rankings["peer"])
    if len(peer) != len(set(peer)):
        raise ValueError("peer review set contains duplicate cells")
    if set(v4) != set(peer_inventory) or len(v4) != len(peer_inventory):
        raise ValueError("peer review set differs from the V4 formula inventory")
    if not peer:
        return None, "no_peer_review_candidate"
    if peer[0] in v4[:REVIEW_BUDGET]:
        return None, "peer_top1_already_in_v4_top5"
    return peer[0], "peer_top1_outside_v4_top5"


def probe_repair_closure(
    model: WorkbookModel,
    v4_ranking: Sequence[str],
    source_audit: Mapping[str, object],
) -> dict[str, object]:
    """Run one deterministic, label-free counterfactual repair probe."""

    audit_errors = validate_label_free_output(source_audit)
    if audit_errors:
        raise ValueError(f"source peer audit is invalid: {'; '.join(audit_errors)}")
    v4 = tuple(str(value) for value in v4_ranking)
    records = _record_map(source_audit)
    candidate, reason = select_peer_candidate(v4, source_audit)
    payload: dict[str, object] = {
        "protocol": PROTOCOL,
        "model_version": MODEL_VERSION,
        "candidate_policy": CANDIDATE_POLICY,
        "review_budget": REVIEW_BUDGET,
        "candidate_selected": candidate is not None,
        "selection_reason": reason,
        "repair_hypothesis_available": False,
        "repair_executed": False,
        "closure": None,
        "label_inputs": [],
        "protected_data_inputs": [],
    }
    if candidate is None:
        return payload
    if candidate not in records:
        raise ValueError("selected peer candidate has no audit record")
    payload["candidate_v4_rank"] = v4.index(candidate) + 1
    payload["candidate_peer_rank"] = _peer_rank(source_audit, candidate)
    hypotheses = records[candidate].get("repair_hypotheses")
    if not isinstance(hypotheses, list):
        raise ValueError("selected peer repair hypotheses are malformed")
    if not hypotheses:
        payload["selection_reason"] = "peer_top1_has_no_repair_hypothesis"
        return payload
    first = hypotheses[0]
    if not isinstance(first, Mapping):
        raise ValueError("first peer repair hypothesis is malformed")
    formula = first.get("formula")
    if not isinstance(formula, str) or not formula.startswith("="):
        raise ValueError("first peer repair hypothesis has no valid formula")
    key = _cell_key(candidate, model)
    original_formula = model.formulas[key]
    if formula == original_formula:
        raise ValueError("peer repair hypothesis does not change the formula")
    repaired_model = _clone_with_formula(model, key, formula)
    repaired_audit = audit_workbook(repaired_model)
    repaired_errors = validate_label_free_output(repaired_audit)
    if repaired_errors:
        raise ValueError(f"repaired peer audit is invalid: {'; '.join(repaired_errors)}")
    restored_model = _clone_with_formula(repaired_model, key, original_formula)
    restored_audit = audit_workbook(restored_model)
    restored_errors = validate_label_free_output(restored_audit)
    if restored_errors:
        raise ValueError(f"restored peer audit is invalid: {'; '.join(restored_errors)}")
    candidate_metrics = _candidate_metrics(source_audit, repaired_audit, candidate)
    global_metrics = _global_metrics(source_audit, repaired_audit, candidate)
    reversible = _audit_projection(restored_audit) == _audit_projection(source_audit)
    payload.update({
        "repair_hypothesis_available": True,
        "repair_executed": True,
        "closure": {
            "candidate": candidate_metrics,
            "global": global_metrics,
            "round_trip_reversible": reversible,
            "repair_closes_without_new_anomaly": bool(
                candidate_metrics["anomaly_disappeared"]
                and candidate_metrics["peer_priority_decreased"]
                and global_metrics["no_new_actionable_anomaly"]
                and float(global_metrics["defect_score_sum_drop"]) > 0.0
                and reversible
            ),
        },
    })
    errors = validate_probe_output(payload)
    if errors:
        raise ValueError(f"repair-closure output is invalid: {'; '.join(errors)}")
    return payload


def _sensitive_output_errors(value: object, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key)
            if name in FORBIDDEN_OUTPUT_FIELDS:
                errors.append(f"forbidden field {path}.{name}")
            errors.extend(_sensitive_output_errors(child, f"{path}.{name}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_sensitive_output_errors(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        if value.startswith("="):
            errors.append(f"raw formula text at {path}")
        if "!" in value and _CELL_LABEL.search(value.rsplit("!", 1)[-1]):
            errors.append(f"cell label at {path}")
    return errors


def validate_probe_output(payload: Mapping[str, object]) -> list[str]:
    """Validate the persistence boundary of one repair-closure result."""

    errors: list[str] = []
    if payload.get("protocol") != PROTOCOL:
        errors.append("unexpected repair-closure protocol")
    if payload.get("model_version") != MODEL_VERSION:
        errors.append("unexpected repair-closure model version")
    if payload.get("candidate_policy") != CANDIDATE_POLICY:
        errors.append("unexpected repair-closure candidate policy")
    if payload.get("review_budget") != REVIEW_BUDGET:
        errors.append("unexpected repair-closure review budget")
    if payload.get("label_inputs") != []:
        errors.append("repair-closure label inputs are not empty")
    if payload.get("protected_data_inputs") != []:
        errors.append("repair-closure protected inputs are not empty")
    selected = payload.get("candidate_selected") is True
    executed = payload.get("repair_executed") is True
    if executed and not selected:
        errors.append("repair executed without a selected candidate")
    if executed and payload.get("closure") is None:
        errors.append("executed repair has no closure metrics")
    if not executed and payload.get("closure") is not None:
        errors.append("unexecuted repair has closure metrics")
    errors.extend(_sensitive_output_errors(payload))
    return errors


__all__ = [
    "ACTIONABLE_STATUSES",
    "CANDIDATE_POLICY",
    "FORBIDDEN_OUTPUT_FIELDS",
    "MODEL_VERSION",
    "PROTOCOL",
    "REVIEW_BUDGET",
    "probe_repair_closure",
    "select_peer_candidate",
    "validate_probe_output",
]
