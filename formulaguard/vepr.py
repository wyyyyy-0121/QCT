"""Natural next-edit availability primitives for the preregistered VEPR line."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from .vdel import formula_map

PROTOCOL = "formulaguard_vepr_u0_v1"
FOLD_SALT = "formulaguard-vepr-v1"
MIN_CURRENT_FORMULAS = 10
MAX_CURRENT_FORMULAS = 5_000
MIN_DIRECT_EDITS = 1
MAX_DIRECT_EDITS = 19
MAX_ADDITIONS_REMOVALS = 12
MIN_STABLE_CANDIDATES = 5


def stable_id(*parts: object) -> str:
    payload = "\0".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def fold_for_group(group_id: int) -> int:
    digest = hashlib.sha256(f"{FOLD_SALT}\0{group_id}".encode("ascii")).hexdigest()
    return int(digest[:8], 16) % 5


def snapshot_sha256(profile: Mapping[str, object]) -> str:
    formulas = formula_map(profile)
    payload = [
        [sheet, address, formula]
        for (sheet, address), formula in sorted(formulas.items())
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def layout_sha256(profile: Mapping[str, object]) -> str:
    formulas = formula_map(profile)
    payload = [[sheet, address] for sheet, address in sorted(formulas)]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def transition_is_ranking_candidate(transition: Mapping[str, object]) -> bool:
    try:
        formulas = int(transition["previous_formula_count"])
        direct = int(transition["direct_formula_text_changes"])
        additions = int(transition["formula_additions"])
        removals = int(transition["formula_removals"])
        stable = int(transition["unchanged_formula_keys"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("VEPR transition counts are malformed") from exc
    return (
        transition.get("eligible") is True
        and MIN_CURRENT_FORMULAS <= formulas <= MAX_CURRENT_FORMULAS
        and MIN_DIRECT_EDITS <= direct <= MAX_DIRECT_EDITS
        and transition.get("bulk_direct_rewrite") is False
        and transition.get("bulk_add_remove") is False
        and additions + removals <= MAX_ADDITIONS_REMOVALS
        and stable >= MIN_STABLE_CANDIDATES
    )


def transition_is_control_candidate(transition: Mapping[str, object]) -> bool:
    try:
        formulas = int(transition["previous_formula_count"])
        direct = int(transition["direct_formula_text_changes"])
        additions = int(transition["formula_additions"])
        removals = int(transition["formula_removals"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("VEPR control counts are malformed") from exc
    return (
        transition.get("eligible") is True
        and MIN_CURRENT_FORMULAS <= formulas <= MAX_CURRENT_FORMULAS
        and direct == 0
        and additions == 0
        and removals == 0
        and transition.get("no_formula_text_change") is True
    )


def classify_ranking_transition(
    *,
    group_id: int,
    current_order: int,
    transition: Mapping[str, object],
    current: Mapping[str, object],
    future: Mapping[str, object],
) -> dict[str, object]:
    """Materialize opaque next-edit labels after the current snapshot exists."""

    current_formulas = formula_map(current)
    current_hash = snapshot_sha256(current)
    future_formulas = formula_map(future)
    shared = sorted(set(current_formulas) & set(future_formulas))
    changed = [key for key in shared if current_formulas[key] != future_formulas[key]]
    stable = [key for key in shared if current_formulas[key] == future_formulas[key]]
    changed_set = set(changed)
    if (
        len(current_formulas) != int(transition["previous_formula_count"])
        or len(future_formulas) != int(transition["current_formula_count"])
        or len(changed) != int(transition["direct_formula_text_changes"])
        or len(stable) != int(transition["unchanged_formula_keys"])
        or not transition_is_ranking_candidate(transition)
    ):
        raise ValueError("VEPR profile comparison differs from the frozen transition")

    labels = [
        {
            "candidate_id": stable_id(
                "vepr-candidate", group_id, current_order, sheet, address
            ),
            "next_direct_edit": key in changed_set,
        }
        for key in shared
        for sheet, address in [key]
    ]
    labels.sort(key=lambda row: str(row["candidate_id"]))
    positive_count = len(changed)
    stable_count = len(stable)
    return {
        "ranking_id": stable_id("vepr-ranking", group_id, current_order),
        "current_snapshot_id": stable_id("vepr-snapshot", group_id, current_order),
        "current_snapshot_sha256": current_hash,
        "group_id_hash": stable_id("vepr-group", group_id),
        "fold": fold_for_group(group_id),
        "current_formula_count": len(current_formulas),
        "candidate_count": len(labels),
        "positive_count": positive_count,
        "stable_count": stable_count,
        "candidate_labels": labels,
    }


def build_control(
    *,
    group_id: int,
    current_order: int,
    transition: Mapping[str, object],
    current: Mapping[str, object],
) -> dict[str, object]:
    if not transition_is_control_candidate(transition):
        raise ValueError("VEPR control does not satisfy the frozen transition rules")
    formulas = formula_map(current)
    if len(formulas) != int(transition["previous_formula_count"]):
        raise ValueError("VEPR control formula count differs from the frozen transition")
    return {
        "control_id": stable_id("vepr-control", group_id, current_order),
        "current_snapshot_id": stable_id("vepr-snapshot", group_id, current_order),
        "current_snapshot_sha256": snapshot_sha256(current),
        "layout_sha256": layout_sha256(current),
        "group_id_hash": stable_id("vepr-group", group_id),
        "fold": fold_for_group(group_id),
        "current_formula_count": len(formulas),
    }


def evaluate_u0_gates(summary: Mapping[str, object]) -> dict[str, bool]:
    folds = summary.get("folds")
    if not isinstance(folds, Mapping):
        raise TypeError("VEPR U0 fold summary is malformed")
    fold_coverage = all(
        isinstance(folds.get(str(fold)), Mapping)
        and int(folds[str(fold)].get("ranking_transitions", 0)) >= 30
        and int(folds[str(fold)].get("ranking_groups", 0)) >= 6
        and int(folds[str(fold)].get("positive_rows", 0)) >= 80
        and int(folds[str(fold)].get("stable_rows", 0)) >= 3_000
        for fold in range(5)
    )
    control_fold_coverage = all(
        isinstance(folds.get(str(fold)), Mapping)
        and int(folds[str(fold)].get("controls", 0)) >= 20
        and int(folds[str(fold)].get("control_groups", 0)) >= 10
        for fold in range(5)
    )
    return {
        "ranking_transitions_300_across_50_groups": (
            int(summary.get("ranking_transitions", 0)) >= 300
            and int(summary.get("ranking_groups", 0)) >= 50
        ),
        "candidate_classes_600_positive_30000_stable": (
            int(summary.get("positive_rows", 0)) >= 600
            and int(summary.get("stable_rows", 0)) >= 30_000
        ),
        "five_fold_ranking_coverage": fold_coverage,
        "controls_200_across_80_groups": (
            int(summary.get("controls", 0)) >= 200
            and int(summary.get("control_groups", 0)) >= 80
        ),
        "five_fold_control_coverage": control_fold_coverage,
        "complete_group_overlap_exclusion": (
            summary.get("overlap_exclusion_complete") is True
            and int(summary.get("overlap_excluded_rows", 0)) == 0
        ),
        "complete_group_invalid_profile_exclusion": (
            summary.get("profile_text_validation_complete") is True
            and int(summary.get("invalid_profile_rows", 0)) == 0
        ),
        "integrity_and_reproducibility_ready": (
            summary.get("input_hashes_verified") is True
            and summary.get("group_order_verified") is True
            and summary.get("candidate_accounting_verified") is True
            and summary.get("snapshot_before_label_verified") is True
            and summary.get("fold_isolation_verified") is True
        ),
        "zero_forbidden_inputs": all(
            summary.get(field) == []
            for field in (
                "cached_value_inputs",
                "constant_inputs",
                "cell_text_inputs",
                "email_inputs",
                "fault_label_inputs",
                "expected_output_inputs",
                "correct_workbook_inputs",
                "public_source_cell_inputs",
                "v4_inputs",
                "protected_data_inputs",
            )
        ),
    }


def validate_private_manifest(payload: Mapping[str, object]) -> None:
    if payload.get("protocol") != PROTOCOL:
        raise ValueError("VEPR U0 manifest protocol is invalid")
    rankings = payload.get("ranking_transitions")
    controls = payload.get("unchanged_controls")
    if not isinstance(rankings, list) or not isinstance(controls, list):
        raise TypeError("VEPR U0 manifest rows are malformed")

    seen: set[str] = set()
    group_folds: dict[str, int] = {}
    for row in rankings:
        if not isinstance(row, Mapping):
            raise TypeError("VEPR ranking row is malformed")
        identity = str(row.get("ranking_id", ""))
        group = str(row.get("group_id_hash", ""))
        fold = int(row.get("fold", -1))
        labels = row.get("candidate_labels")
        if (
            len(identity) != 64
            or identity in seen
            or len(group) != 64
            or fold not in range(5)
            or not isinstance(labels, list)
            or len(labels) < 6
        ):
            raise ValueError("VEPR ranking identity or labels are invalid")
        seen.add(identity)
        if group_folds.setdefault(group, fold) != fold:
            raise ValueError("VEPR evolution group crosses folds")
        candidate_ids = [str(label.get("candidate_id", "")) for label in labels]
        values = {label.get("next_direct_edit") for label in labels}
        if (
            len(candidate_ids) != len(set(candidate_ids))
            or any(len(identity) != 64 for identity in candidate_ids)
            or values != {False, True}
            or len(labels) != int(row.get("candidate_count", -1))
            or sum(label.get("next_direct_edit") is True for label in labels)
            != int(row.get("positive_count", -1))
            or sum(label.get("next_direct_edit") is False for label in labels)
            != int(row.get("stable_count", -1))
        ):
            raise ValueError("VEPR candidate labels or accounting are invalid")

    control_layouts: set[tuple[str, str]] = set()
    for row in controls:
        if not isinstance(row, Mapping):
            raise TypeError("VEPR control row is malformed")
        identity = str(row.get("control_id", ""))
        group = str(row.get("group_id_hash", ""))
        layout = str(row.get("layout_sha256", ""))
        fold = int(row.get("fold", -1))
        if (
            len(identity) != 64
            or identity in seen
            or len(group) != 64
            or len(layout) != 64
            or fold not in range(5)
            or (group, layout) in control_layouts
        ):
            raise ValueError("VEPR control identity or layout is invalid")
        seen.add(identity)
        control_layouts.add((group, layout))
        if group_folds.setdefault(group, fold) != fold:
            raise ValueError("VEPR control group crosses folds")


__all__ = [
    "FOLD_SALT",
    "MAX_ADDITIONS_REMOVALS",
    "MAX_CURRENT_FORMULAS",
    "MAX_DIRECT_EDITS",
    "MIN_CURRENT_FORMULAS",
    "MIN_DIRECT_EDITS",
    "MIN_STABLE_CANDIDATES",
    "PROTOCOL",
    "build_control",
    "classify_ranking_transition",
    "evaluate_u0_gates",
    "fold_for_group",
    "layout_sha256",
    "snapshot_sha256",
    "stable_id",
    "transition_is_control_candidate",
    "transition_is_ranking_candidate",
    "validate_private_manifest",
]
