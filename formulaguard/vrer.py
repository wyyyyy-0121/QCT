"""Verified-revision corpus primitives for the frozen VRER protocol."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

from .formula import FormulaSyntaxError
from .workbook import WorkbookModel

PROTOCOL = "formulaguard_vrer_v1"
R0_PROTOCOL = "formulaguard_vrer_r0_audit_v1"
CORRECTION_TERMS = re.compile(
    r"\b(?:bug|correct(?:ed|ion|s)?|error|fix(?:ed|es|ing)?|incorrect|wrong)\b",
    re.IGNORECASE,
)
R0_THRESHOLDS = {
    "correction_episodes": 60,
    "corrected_formula_cells": 80,
    "revision_groups": 40,
    "repositories": 10,
    "control_episodes": 30,
    "control_repositories": 5,
    "maximum_repository_group_share": 0.25,
    "parseable_corrected_cell_fraction": 0.90,
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("VRER path must be a nonempty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("VRER path escapes its declared source root")
    return path.as_posix()


def workbook_profile(path: Path) -> dict[str, object]:
    """Extract formulas and parser coverage without retaining constants or cached values."""
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError("VRER R0 accepts only OOXML workbook packages")
    model = WorkbookModel.from_xlsx(path)
    formulas: list[dict[str, object]] = []
    parseable = 0
    for sheet, address in model.formula_cells:
        formula = model.formulas[(sheet, address)].strip()
        supported = True
        try:
            model.ast(formula)
        except FormulaSyntaxError:
            supported = False
        parseable += int(supported)
        formulas.append(
            {
                "sheet": sheet,
                "address": address,
                "formula": formula,
                "parseable": supported,
            }
        )
    return {
        "workbook_sha256": sha256_file(path),
        "sheet_titles": sorted(model.sheet_visibility),
        "formula_count": len(formulas),
        "parseable_formula_count": parseable,
        "formulas": formulas,
        "constant_values_retained": False,
        "cached_values_retained": False,
    }


def _formula_map(
    profile: Mapping[str, object],
) -> dict[tuple[str, str], dict[str, object]]:
    rows = profile.get("formulas")
    if not isinstance(rows, list):
        raise TypeError("VRER workbook profile has no formula list")
    result: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("VRER formula row is malformed")
        key = (str(row.get("sheet", "")), str(row.get("address", "")))
        formula = str(row.get("formula", "")).strip()
        if not all(key) or not formula or key in result:
            raise ValueError("VRER formula identity is empty or duplicated")
        result[key] = {"formula": formula, "parseable": row.get("parseable") is True}
    return result


def compare_workbook_profiles(
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> dict[str, object]:
    left = _formula_map(before)
    right = _formula_map(after)
    shared = set(left) & set(right)
    changed_keys = sorted(
        key for key in shared if left[key]["formula"] != right[key]["formula"]
    )
    added_keys = sorted(set(right) - set(left))
    removed_keys = sorted(set(left) - set(right))
    address_only_move = (
        bool(added_keys and removed_keys)
        and not changed_keys
        and (
            Counter(right[key]["formula"] for key in added_keys)
            == Counter(left[key]["formula"] for key in removed_keys)
        )
    )
    changes = [
        {
            "sheet": sheet,
            "address": address,
            "before_formula": left[(sheet, address)]["formula"],
            "after_formula": right[(sheet, address)]["formula"],
            "before_parseable": left[(sheet, address)]["parseable"],
            "after_parseable": right[(sheet, address)]["parseable"],
        }
        for sheet, address in changed_keys
    ]
    return {
        "same_sheet_titles": before.get("sheet_titles") == after.get("sheet_titles"),
        "before_formula_count": len(left),
        "after_formula_count": len(right),
        "shared_formula_cells": len(shared),
        "direct_formula_changes": len(changes),
        "formula_additions": len(added_keys),
        "formula_removals": len(removed_keys),
        "bulk_formula_add_remove": len(added_keys) + len(removed_keys) >= 20,
        "address_only_formula_move": address_only_move,
        "changed_cells": changes,
        "added_cells": [{"sheet": key[0], "address": key[1]} for key in added_keys],
        "removed_cells": [{"sheet": key[0], "address": key[1]} for key in removed_keys],
    }


def audit_candidate(
    candidate: Mapping[str, object],
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    license_verified: bool,
) -> dict[str, object]:
    source_kind = str(candidate.get("source_kind", ""))
    scope = str(candidate.get("evidence_scope", ""))
    quote = str(candidate.get("evidence_quote", "")).strip()
    diff = compare_workbook_profiles(before, after)
    rejected: list[str] = []

    if source_kind not in {"correction", "ordinary_edit_control"}:
        rejected.append("unsupported_source_kind")
    if not license_verified:
        rejected.append("license_not_verified")
    if source_kind == "correction" and not CORRECTION_TERMS.search(quote):
        rejected.append("no_explicit_correction_statement")
    if source_kind == "ordinary_edit_control" and CORRECTION_TERMS.search(quote):
        rejected.append("control_has_correction_language")
    if scope not in {"workbook", "exact_cells"}:
        rejected.append("invalid_evidence_scope")
    if not diff["same_sheet_titles"]:
        rejected.append("sheet_inventory_changed")
    if diff["direct_formula_changes"] == 0:
        rejected.append("no_same_cell_formula_change")
    if diff["address_only_formula_move"]:
        rejected.append("address_only_formula_move")
    if diff["bulk_formula_add_remove"]:
        rejected.append("bulk_formula_add_remove")
    if scope == "workbook" and diff["direct_formula_changes"] > 12:
        rejected.append("workbook_statement_has_more_than_12_direct_changes")

    if scope == "exact_cells":
        claimed = candidate.get("claimed_cells")
        if not isinstance(claimed, list) or not claimed:
            rejected.append("exact_cell_statement_has_no_claimed_cells")
        else:
            normalized_claimed = {
                (str(row.get("sheet", "")), str(row.get("address", "")))
                for row in claimed
                if isinstance(row, Mapping)
            }
            observed = {
                (str(row["sheet"]), str(row["address"]))
                for row in diff["changed_cells"]
            }
            if normalized_claimed != observed:
                rejected.append("claimed_cells_do_not_equal_formula_changes")

    accepted = not rejected
    corrected_cells = (
        diff["changed_cells"] if accepted and source_kind == "correction" else []
    )
    parseable_corrected = sum(
        row["before_parseable"] and row["after_parseable"] for row in corrected_cells
    )
    return {
        "candidate_id": str(candidate.get("candidate_id", "")),
        "repository": str(candidate.get("repository", "")),
        "revision_group": str(candidate.get("revision_group", "")),
        "source_kind": source_kind,
        "accepted": accepted,
        "rejection_reasons": rejected,
        "corrected_formula_cells": len(corrected_cells),
        "parseable_corrected_formula_cells": parseable_corrected,
        "diff": diff,
    }


def summarize_r0(
    records: Sequence[Mapping[str, object]],
    *,
    reproducible_audit: bool = False,
    protected_data_inputs: Sequence[str] = (),
    revealed_label_inputs: Sequence[str] = (),
) -> dict[str, object]:
    accepted = [row for row in records if row.get("accepted") is True]
    corrections = [row for row in accepted if row.get("source_kind") == "correction"]
    controls = [
        row for row in accepted if row.get("source_kind") == "ordinary_edit_control"
    ]
    groups = {str(row["revision_group"]) for row in corrections}
    repositories = {str(row["repository"]) for row in corrections}
    control_repositories = {str(row["repository"]) for row in controls}
    group_repository = {
        str(row["revision_group"]): str(row["repository"]) for row in corrections
    }
    repository_group_counts = Counter(group_repository.values())
    maximum_share = (
        max(repository_group_counts.values()) / len(groups) if groups else 1.0
    )
    corrected_cells = sum(
        int(row.get("corrected_formula_cells", 0)) for row in corrections
    )
    parseable_cells = sum(
        int(row.get("parseable_corrected_formula_cells", 0)) for row in corrections
    )
    parseable_fraction = parseable_cells / corrected_cells if corrected_cells else 0.0
    counts = {
        "candidate_episodes": len(records),
        "accepted_episodes": len(accepted),
        "rejected_episodes": len(records) - len(accepted),
        "correction_episodes": len(corrections),
        "corrected_formula_cells": corrected_cells,
        "revision_groups": len(groups),
        "repositories": len(repositories),
        "control_episodes": len(controls),
        "control_repositories": len(control_repositories),
        "maximum_repository_group_share": maximum_share,
        "parseable_corrected_cell_fraction": parseable_fraction,
    }
    gates = {
        "60_correction_episodes": counts["correction_episodes"] >= 60,
        "80_corrected_formula_cells": counts["corrected_formula_cells"] >= 80,
        "40_revision_groups": counts["revision_groups"] >= 40,
        "10_repositories": counts["repositories"] >= 10,
        "30_control_episodes": counts["control_episodes"] >= 30,
        "5_control_repositories": counts["control_repositories"] >= 5,
        "repository_share_at_most_25_percent": maximum_share <= 0.25,
        "parseability_at_least_90_percent": parseable_fraction >= 0.90,
        "independent_reproduction_passed": reproducible_audit,
        "no_protected_or_revealed_inputs": (
            not protected_data_inputs and not revealed_label_inputs
        ),
    }
    return {
        "protocol": R0_PROTOCOL,
        "thresholds": R0_THRESHOLDS,
        "counts": counts,
        "gates": gates,
        "r0_passed": all(gates.values()),
        "protected_data_inputs": list(protected_data_inputs),
        "revealed_label_inputs": list(revealed_label_inputs),
    }


__all__ = [
    "CORRECTION_TERMS",
    "PROTOCOL",
    "R0_PROTOCOL",
    "R0_THRESHOLDS",
    "audit_candidate",
    "compare_workbook_profiles",
    "safe_relative_path",
    "sha256_bytes",
    "sha256_file",
    "summarize_r0",
    "workbook_profile",
]
