"""Version-delta edit-longevity U0 primitives."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

PROTOCOL = "formulaguard_vdel_u0_v1"
MIN_FORMULAS_FOR_OVERLAP = 20
EXACT_CONTAINMENT_THRESHOLD = 0.80
COORDINATE_CONTAINMENT_THRESHOLD = 0.90
COORDINATE_FORMULA_AGREEMENT_THRESHOLD = 0.80


def stable_id(*parts: object) -> str:
    payload = "\0".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def fold_for_group(group_id: int) -> int:
    digest = hashlib.sha256(
        f"formulaguard-vdel-v1\0{group_id}".encode("ascii")
    ).hexdigest()
    return int(digest[:8], 16) % 5


def formula_map(profile: Mapping[str, object]) -> dict[tuple[str, str], str]:
    rows = profile.get("formulas")
    if not isinstance(rows, list):
        raise TypeError("VDEL profile has no formula list")
    result: dict[tuple[str, str], str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("VDEL formula profile row is malformed")
        key = (str(row.get("sheet", "")), str(row.get("address", "")))
        formula = str(row.get("formula", "")).strip()
        if not all(key) or not formula.startswith("=") or key in result:
            raise ValueError("VDEL formula profile key is invalid or duplicated")
        result[key] = formula
    return result


def profile_has_valid_formula_text(profile: Mapping[str, object]) -> bool:
    rows = profile.get("formulas")
    if not isinstance(rows, list):
        return False
    return all(
        isinstance(row, Mapping)
        and isinstance(row.get("formula"), str)
        and str(row["formula"]).strip().startswith("=")
        for row in rows
    )


def sheet_titles(profile: Mapping[str, object]) -> frozenset[str]:
    titles = profile.get("sheet_titles")
    if not isinstance(titles, list) or any(not isinstance(item, str) for item in titles):
        raise ValueError("VDEL profile has no valid sheet-title list")
    if len(titles) != len(set(titles)):
        raise ValueError("VDEL profile has duplicate sheet titles")
    return frozenset(titles)


@dataclass(frozen=True)
class FormulaSignature:
    formulas: Mapping[tuple[str, str], str]
    exact_entries: frozenset[tuple[str, str, str]]

    @property
    def count(self) -> int:
        return len(self.formulas)


def formula_signature(profile: Mapping[str, object]) -> FormulaSignature:
    formulas = formula_map(profile)
    return FormulaSignature(
        formulas=formulas,
        exact_entries=frozenset(
            (sheet, address, formula)
            for (sheet, address), formula in formulas.items()
        ),
    )


def near_duplicate(
    first: FormulaSignature,
    second: FormulaSignature,
    *,
    min_formulas: int = MIN_FORMULAS_FOR_OVERLAP,
    exact_threshold: float = EXACT_CONTAINMENT_THRESHOLD,
    coordinate_threshold: float = COORDINATE_CONTAINMENT_THRESHOLD,
    agreement_threshold: float = COORDINATE_FORMULA_AGREEMENT_THRESHOLD,
) -> bool:
    if first.count < min_formulas or second.count < min_formulas:
        return False
    smaller = min(first.count, second.count)
    exact_overlap = len(first.exact_entries & second.exact_entries)
    if exact_overlap / smaller >= exact_threshold:
        return True

    first_keys = set(first.formulas)
    shared_keys = first_keys & set(second.formulas)
    if len(shared_keys) / smaller < coordinate_threshold:
        return False
    equal_formulas = sum(
        first.formulas[key] == second.formulas[key] for key in shared_keys
    )
    return bool(shared_keys) and equal_formulas / len(shared_keys) >= agreement_threshold


def transition_is_candidate(transition: Mapping[str, object]) -> bool:
    try:
        direct = int(transition["direct_formula_text_changes"])
        additions = int(transition["formula_additions"])
        removals = int(transition["formula_removals"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("VDEL transition counts are malformed") from exc
    return (
        transition.get("eligible") is True
        and 2 <= direct <= 12
        and transition.get("bulk_direct_rewrite") is False
        and transition.get("bulk_add_remove") is False
        and additions + removals <= 12
    )


def classify_window(
    *,
    group_id: int,
    current_order: int,
    transition: Mapping[str, object],
    previous: Mapping[str, object],
    current: Mapping[str, object],
    future: Mapping[str, object],
) -> tuple[str, dict[str, object]]:
    if sheet_titles(previous) != sheet_titles(current):
        return "sheet_title_change", {}

    previous_formulas = formula_map(previous)
    current_formulas = formula_map(current)
    future_formulas = formula_map(future)
    direct_keys = sorted(
        key
        for key in set(previous_formulas) & set(current_formulas)
        if previous_formulas[key] != current_formulas[key]
    )
    expected_direct = int(transition["direct_formula_text_changes"])
    if len(direct_keys) != expected_direct:
        raise ValueError("VDEL direct-edit count differs from the frozen transition")

    labels: list[dict[str, object]] = []
    for sheet, address in direct_keys:
        future_formula = future_formulas.get((sheet, address))
        if future_formula is None:
            continue
        labels.append({
            "candidate_id": stable_id(
                "vdel-candidate", group_id, current_order, sheet, address
            ),
            "re_edited": future_formula != current_formulas[(sheet, address)],
        })
    if len(labels) < 2:
        return "fewer_than_two_available_candidates", {
            "direct_edit_count": len(direct_keys),
            "available_candidate_count": len(labels),
        }

    positives = sum(row["re_edited"] is True for row in labels)
    negatives = len(labels) - positives
    base = {
        "window_id": stable_id("vdel-window", group_id, current_order),
        "group_id_hash": stable_id("vdel-group", group_id),
        "fold": fold_for_group(group_id),
        "direct_edit_count": len(direct_keys),
        "available_candidate_count": len(labels),
        "unavailable_candidate_count": len(direct_keys) - len(labels),
        "positive_count": positives,
        "negative_count": negatives,
        "candidate_labels": labels,
    }
    if positives and negatives:
        return "ranking_window", base
    if not positives:
        return "no_reedit_control", base
    return "all_reedited", base


def evaluate_u0_gates(summary: Mapping[str, object]) -> dict[str, bool]:
    folds = summary.get("folds")
    if not isinstance(folds, Mapping):
        raise TypeError("VDEL U0 fold summary is malformed")
    fold_coverage = all(
        isinstance(folds.get(str(fold)), Mapping)
        and int(folds[str(fold)].get("ranking_windows", 0)) >= 15
        and int(folds[str(fold)].get("groups", 0)) >= 8
        for fold in range(5)
    )
    return {
        "ranking_windows_120_across_40_groups": (
            int(summary.get("ranking_windows", 0)) >= 120
            and int(summary.get("ranking_window_groups", 0)) >= 40
        ),
        "candidate_class_counts_at_least_240_120_120": (
            int(summary.get("ranking_candidates", 0)) >= 240
            and int(summary.get("re_edited_candidates", 0)) >= 120
            and int(summary.get("stable_candidates", 0)) >= 120
        ),
        "five_fold_coverage": fold_coverage,
        "controls_30_across_15_groups": (
            int(summary.get("no_reedit_controls", 0)) >= 30
            and int(summary.get("no_reedit_control_groups", 0)) >= 15
        ),
        "complete_group_overlap_exclusion": (
            summary.get("overlap_exclusion_complete") is True
            and int(summary.get("excluded_group_rows", 0)) == 0
        ),
        "complete_group_invalid_profile_exclusion": (
            summary.get("profile_text_validation_complete") is True
            and int(summary.get("invalid_profile_group_rows", 0)) == 0
        ),
        "integrity_and_reproducibility_ready": (
            summary.get("input_hashes_verified") is True
            and summary.get("group_order_verified") is True
            and summary.get("candidate_accounting_verified") is True
            and summary.get("fold_isolation_verified") is True
        ),
        "zero_forbidden_inputs": (
            summary.get("cached_value_inputs") == []
            and summary.get("constant_inputs") == []
            and summary.get("email_inputs") == []
            and summary.get("fault_label_inputs") == []
            and summary.get("public_label_inputs") == []
            and summary.get("answer_workbook_inputs") == []
            and summary.get("v4_inputs") == []
            and summary.get("protected_data_inputs") == []
        ),
    }


def validate_private_manifest(payload: Mapping[str, object]) -> None:
    if payload.get("protocol") != PROTOCOL:
        raise ValueError("VDEL U0 manifest protocol is invalid")
    windows = payload.get("ranking_windows")
    controls = payload.get("no_reedit_controls")
    if not isinstance(windows, list) or not isinstance(controls, list):
        raise TypeError("VDEL U0 manifest rows are malformed")
    seen_windows: set[str] = set()
    group_folds: dict[str, int] = {}
    for row in [*windows, *controls]:
        if not isinstance(row, Mapping):
            raise TypeError("VDEL U0 manifest row is malformed")
        window_id = str(row.get("window_id", ""))
        group_hash = str(row.get("group_id_hash", ""))
        fold = int(row.get("fold", -1))
        if (
            len(window_id) != 64
            or len(group_hash) != 64
            or fold not in range(5)
            or window_id in seen_windows
        ):
            raise ValueError("VDEL U0 manifest identity is invalid")
        seen_windows.add(window_id)
        prior_fold = group_folds.setdefault(group_hash, fold)
        if prior_fold != fold:
            raise ValueError("VDEL evolution group crosses folds")
        labels = row.get("candidate_labels")
        if not isinstance(labels, list) or len(labels) < 2:
            raise ValueError("VDEL U0 candidate labels are malformed")
        if any(
            not isinstance(label, Mapping)
            or len(str(label.get("candidate_id", ""))) != 64
            or not isinstance(label.get("re_edited"), bool)
            for label in labels
        ):
            raise ValueError("VDEL U0 candidate label is invalid")
    for row in windows:
        labels = row["candidate_labels"]
        values = {label["re_edited"] for label in labels}
        if values != {False, True}:
            raise ValueError("VDEL ranking window does not contain both classes")
    for row in controls:
        if any(label["re_edited"] for label in row["candidate_labels"]):
            raise ValueError("VDEL no-re-edit control contains a positive label")


__all__ = [
    "COORDINATE_CONTAINMENT_THRESHOLD",
    "COORDINATE_FORMULA_AGREEMENT_THRESHOLD",
    "EXACT_CONTAINMENT_THRESHOLD",
    "MIN_FORMULAS_FOR_OVERLAP",
    "PROTOCOL",
    "FormulaSignature",
    "classify_window",
    "evaluate_u0_gates",
    "fold_for_group",
    "formula_map",
    "formula_signature",
    "near_duplicate",
    "profile_has_valid_formula_text",
    "stable_id",
    "transition_is_candidate",
    "validate_private_manifest",
]
