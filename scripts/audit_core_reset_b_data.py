"""Audit core-reset-b development data roles, groups, and structural overlap."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.a1 import parse_address
from formulaguard.workbook import WorkbookModel


PROTOCOL = "core_reset_b_phase0_data_audit_v1"
NEAR_DUPLICATE_THRESHOLDS = {
    "formula_count_ratio": 0.90,
    "formula_multiset_jaccard": 0.90,
    "normalized_layout_jaccard": 0.85,
    "degree_histogram_jaccard": 0.85,
}
EXPECTED_COUNTS = {
    "public_events": 90,
    "public_errors": 60,
    "public_controls": 30,
    "public_error_provenance_groups": 22,
    "public_control_provenance_groups": 11,
    "public_shared_error_control_groups": 11,
    "historical_events": 100,
    "enron_events": 30,
    "enron_workbook_groups": 25,
}
FORBIDDEN_DATASET_PREFIXES = (
    "data/external/v5_psl/revealed_trial",
    "data/external/v5_psl/custodian",
    "data/external/v5_psl/final_blind",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(payload: object) -> str:
    value = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def relative_display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def safe_path(root: Path, value: str) -> Path:
    if not value or "\\" in value:
        raise ValueError(f"invalid relative path: {value!r}")
    candidate = (root / value).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError(f"path escapes root: {value!r}")
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def require_columns(
    rows: Sequence[Mapping[str, str]],
    required: set[str],
    *,
    name: str,
) -> None:
    if not rows:
        raise ValueError(f"{name} is empty")
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"{name} is missing columns: {sorted(missing)}")


@dataclass(frozen=True)
class WorkbookProfile:
    workbook_sha256: str
    formula_count: int
    nonempty_cell_count: int
    sheet_count: int
    unsupported_formula_count: int
    exact_layout_signature: str
    normalized_layout_signature: str
    formula_multiset_signature: str
    degree_histogram_signature: str
    sheet_structure_signature: str
    template_signature: str
    formula_counter: Counter[str]
    layout_counter: Counter[str]
    degree_counter: Counter[str]

    def public_row(self, *, path: str) -> dict[str, object]:
        return {
            "path": path,
            "workbook_sha256": self.workbook_sha256,
            "formula_count": self.formula_count,
            "nonempty_cell_count": self.nonempty_cell_count,
            "sheet_count": self.sheet_count,
            "unsupported_formula_count": self.unsupported_formula_count,
            "exact_layout_signature": self.exact_layout_signature,
            "normalized_layout_signature": self.normalized_layout_signature,
            "formula_multiset_signature": self.formula_multiset_signature,
            "degree_histogram_signature": self.degree_histogram_signature,
            "sheet_structure_signature": self.sheet_structure_signature,
            "template_signature": self.template_signature,
        }


class InputLedger:
    def __init__(
        self,
        allowed_roots: Iterable[Path],
        forbidden_prefixes: Iterable[Path],
    ) -> None:
        self.allowed_roots = tuple(path.resolve() for path in allowed_roots)
        self.forbidden_prefixes = tuple(path.resolve() for path in forbidden_prefixes)
        self.files: dict[Path, str] = {}
        self.models: dict[Path, WorkbookModel] = {}
        self.profiles: dict[Path, WorkbookProfile] = {}

    def record(self, path: Path) -> Path:
        resolved = path.resolve()
        if not any(
            resolved == root or root in resolved.parents
            for root in self.allowed_roots
        ):
            raise ValueError(f"dataset input is outside the allowlist: {resolved}")
        if any(
            resolved == prefix or prefix in resolved.parents
            for prefix in self.forbidden_prefixes
        ):
            raise ValueError(f"forbidden dataset input: {resolved}")
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        self.files.setdefault(resolved, sha256(resolved))
        return resolved

    def csv(self, path: Path) -> list[dict[str, str]]:
        return read_csv(self.record(path))

    def model(self, path: Path) -> WorkbookModel:
        resolved = self.record(path)
        if resolved not in self.models:
            self.models[resolved] = WorkbookModel.from_xlsx(resolved)
        return self.models[resolved]

    def profile(self, path: Path) -> WorkbookProfile:
        resolved = self.record(path)
        if resolved not in self.profiles:
            self.profiles[resolved] = workbook_profile(
                self.model(resolved),
                self.files[resolved],
            )
        return self.profiles[resolved]


def _canonical_fingerprint(value: str, sheet_indexes: Mapping[str, int]) -> str:
    result = value
    for sheet, index in sorted(sheet_indexes.items(), key=lambda item: -len(item[0])):
        result = result.replace(f"'{sheet}'!", f"'S{index}'!")
    return result


def _bounds(addresses: Sequence[str]) -> tuple[int, int, int, int]:
    parsed = [parse_address(address) for address in addresses]
    if not parsed:
        return 0, 0, 0, 0
    rows = [address.row for address in parsed]
    columns = [address.col for address in parsed]
    return min(rows), min(columns), max(rows), max(columns)


def workbook_profile(model: WorkbookModel, workbook_digest: str) -> WorkbookProfile:
    seen_sheets: list[str] = list(model.sheet_visibility)
    for sheet, _address in (*model.cells, *model.formulas):
        if sheet not in seen_sheets:
            seen_sheets.append(sheet)
    sheet_indexes = {sheet: index for index, sheet in enumerate(seen_sheets)}
    fingerprints = model.fingerprints()
    canonical = {
        cell: _canonical_fingerprint(value, sheet_indexes)
        for cell, value in fingerprints.items()
    }

    formula_counter = Counter(canonical.values())
    exact_layout: list[tuple[str, str, str]] = []
    normalized_layout: list[tuple[int, int, int, str]] = []
    layout_counter: Counter[str] = Counter()
    sheet_structures: list[dict[str, object]] = []

    for sheet in seen_sheets:
        formula_cells = sorted(
            (cell for cell in model.formula_cells if cell[0] == sheet),
            key=lambda cell: parse_address(cell[1]),
        )
        all_cells = sorted(
            {cell for cell in (*model.cells, *model.formulas) if cell[0] == sheet},
            key=lambda cell: parse_address(cell[1]),
        )
        formula_bounds = _bounds([cell[1] for cell in formula_cells])
        all_bounds = _bounds([cell[1] for cell in all_cells])
        min_row, min_col, max_row, max_col = formula_bounds
        for cell in formula_cells:
            address = parse_address(cell[1])
            row_offset = address.row - min_row
            col_offset = address.col - min_col
            fingerprint = canonical[cell]
            exact_layout.append((sheet, cell[1], fingerprint))
            normalized_layout.append(
                (sheet_indexes[sheet], row_offset, col_offset, fingerprint)
            )
            layout_counter[
                f"{sheet_indexes[sheet]}:{row_offset}:{col_offset}"
            ] += 1
        sheet_structures.append({
            "sheet_index": sheet_indexes[sheet],
            "formula_count": len(formula_cells),
            "nonempty_count": len(all_cells),
            "formula_height": max_row - min_row + 1 if formula_cells else 0,
            "formula_width": max_col - min_col + 1 if formula_cells else 0,
            "content_height": all_bounds[2] - all_bounds[0] + 1 if all_cells else 0,
            "content_width": all_bounds[3] - all_bounds[1] + 1 if all_cells else 0,
            "visible": bool(model.sheet_visibility.get(sheet, True)),
        })

    graph = model.dependency_graph()
    degree_counter = Counter(
        f"{len(graph.precedents.get(cell, ()))}:{len(graph.dependents.get(cell, ()))}"
        for cell in model.formula_cells
    )
    formula_items = sorted(formula_counter.items())
    degree_items = sorted(degree_counter.items())
    exact_layout_signature = stable_hash(exact_layout)
    normalized_layout_signature = stable_hash(normalized_layout)
    formula_multiset_signature = stable_hash(formula_items)
    degree_histogram_signature = stable_hash(degree_items)
    sheet_structure_signature = stable_hash(sheet_structures)
    template_signature = stable_hash({
        "normalized_layout": normalized_layout,
        "formula_multiset": formula_items,
        "degree_histogram": degree_items,
        "sheet_structures": sheet_structures,
    })
    return WorkbookProfile(
        workbook_sha256=workbook_digest,
        formula_count=len(model.formulas),
        nonempty_cell_count=len(set(model.cells) | set(model.formulas)),
        sheet_count=len(seen_sheets),
        unsupported_formula_count=sum(
            value.startswith("UNSUPPORTED:") for value in fingerprints.values()
        ),
        exact_layout_signature=exact_layout_signature,
        normalized_layout_signature=normalized_layout_signature,
        formula_multiset_signature=formula_multiset_signature,
        degree_histogram_signature=degree_histogram_signature,
        sheet_structure_signature=sheet_structure_signature,
        template_signature=template_signature,
        formula_counter=formula_counter,
        layout_counter=layout_counter,
        degree_counter=degree_counter,
    )


def weighted_jaccard(left: Counter[str], right: Counter[str]) -> float:
    keys = set(left) | set(right)
    denominator = sum(max(left[key], right[key]) for key in keys)
    if denominator == 0:
        return 1.0
    return sum(min(left[key], right[key]) for key in keys) / denominator


def profile_similarity(
    left: WorkbookProfile,
    right: WorkbookProfile,
) -> dict[str, float | bool]:
    maximum = max(left.formula_count, right.formula_count)
    count_ratio = min(left.formula_count, right.formula_count) / maximum if maximum else 1.0
    formula_jaccard = weighted_jaccard(left.formula_counter, right.formula_counter)
    layout_jaccard = weighted_jaccard(left.layout_counter, right.layout_counter)
    degree_jaccard = weighted_jaccard(left.degree_counter, right.degree_counter)
    near = (
        left.sheet_count == right.sheet_count
        and count_ratio >= NEAR_DUPLICATE_THRESHOLDS["formula_count_ratio"]
        and formula_jaccard >= NEAR_DUPLICATE_THRESHOLDS["formula_multiset_jaccard"]
        and layout_jaccard >= NEAR_DUPLICATE_THRESHOLDS["normalized_layout_jaccard"]
        and degree_jaccard >= NEAR_DUPLICATE_THRESHOLDS["degree_histogram_jaccard"]
    )
    return {
        "formula_count_ratio": count_ratio,
        "formula_multiset_jaccard": formula_jaccard,
        "normalized_layout_jaccard": layout_jaccard,
        "degree_histogram_jaccard": degree_jaccard,
        "near_duplicate": near,
    }


@dataclass(frozen=True)
class ProvenanceUnit:
    unit_id: str
    cohort: str
    provenance_group_id: str
    workbook_path: Path
    profile: WorkbookProfile


class UnionFind:
    def __init__(self, values: Iterable[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def structural_clusters(
    units: Sequence[ProvenanceUnit],
) -> tuple[dict[str, str], list[dict[str, object]]]:
    union = UnionFind(unit.unit_id for unit in units)
    overlaps: list[dict[str, object]] = []
    for index, left in enumerate(units):
        for right in units[index + 1:]:
            similarity = profile_similarity(left.profile, right.profile)
            exact_content = left.profile.workbook_sha256 == right.profile.workbook_sha256
            exact_template = left.profile.template_signature == right.profile.template_signature
            if not exact_content and not exact_template and not similarity["near_duplicate"]:
                continue
            union.union(left.unit_id, right.unit_id)
            overlaps.append({
                "left_unit_id": left.unit_id,
                "right_unit_id": right.unit_id,
                "left_cohort": left.cohort,
                "right_cohort": right.cohort,
                "cross_cohort": left.cohort != right.cohort,
                "exact_content": exact_content,
                "exact_template": exact_template,
                **similarity,
            })

    members: dict[str, list[str]] = defaultdict(list)
    for unit in units:
        members[union.find(unit.unit_id)].append(unit.unit_id)
    cluster_by_unit: dict[str, str] = {}
    for values in members.values():
        cluster_id = "structure:" + stable_hash(sorted(values))
        for value in values:
            cluster_by_unit[value] = cluster_id
    return cluster_by_unit, sorted(
        overlaps,
        key=lambda row: (str(row["left_unit_id"]), str(row["right_unit_id"])),
    )


def _unique_id_check(rows: Sequence[Mapping[str, str]], *, name: str) -> None:
    values = [row["instance_id"] for row in rows]
    if len(values) != len(set(values)):
        raise ValueError(f"{name} has duplicate instance_id values")


def _git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def build_audit(
    *,
    public_root: Path,
    public_manifest: Path,
    historical_root: Path,
    historical_manifest: Path,
    enron_root: Path,
    enron_manifest: Path,
    output_dir: Path,
    expected: Mapping[str, int] = EXPECTED_COUNTS,
    forbidden_prefixes: Sequence[Path] | None = None,
) -> dict[str, object]:
    forbidden = tuple(forbidden_prefixes or (ROOT / value for value in FORBIDDEN_DATASET_PREFIXES))
    ledger = InputLedger(
        (public_root, historical_root, enron_root),
        forbidden,
    )
    public_rows = ledger.csv(public_manifest)
    historical_rows = ledger.csv(historical_manifest)
    enron_rows = ledger.csv(enron_manifest)
    require_columns(
        public_rows,
        {"instance_id", "corpus_id", "workbook", "original_workbook", "case_kind", "include"},
        name="public manifest",
    )
    require_columns(
        historical_rows,
        {"instance_id", "workbook"},
        name="historical manifest",
    )
    require_columns(
        enron_rows,
        {"instance_id", "workbook", "include"},
        name="Enron manifest",
    )
    public_rows = [row for row in public_rows if row["include"] == "1"]
    enron_rows = [row for row in enron_rows if row["include"] == "1"]
    _unique_id_check(public_rows, name="public manifest")
    _unique_id_check(historical_rows, name="historical manifest")
    _unique_id_check(enron_rows, name="Enron manifest")

    instances: list[dict[str, object]] = []
    units: dict[str, ProvenanceUnit] = {}

    public_group_kinds: dict[str, set[str]] = defaultdict(set)
    for row in public_rows:
        workbook = safe_path(public_root, row["workbook"])
        original = safe_path(public_root, row["original_workbook"])
        observed_profile = ledger.profile(workbook)
        original_profile = ledger.profile(original)
        provenance = "public-original:" + original_profile.workbook_sha256
        unit_id = provenance
        public_group_kinds[provenance].add(row["case_kind"])
        units.setdefault(unit_id, ProvenanceUnit(
            unit_id=unit_id,
            cohort=f"public:{row['corpus_id']}",
            provenance_group_id=provenance,
            workbook_path=original,
            profile=original_profile,
        ))
        instances.append({
            "cohort_instance_id": f"public::{row['instance_id']}",
            "instance_id": row["instance_id"],
            "cohort": f"public:{row['corpus_id']}",
            "workbook": relative_display(workbook),
            "workbook_sha256": observed_profile.workbook_sha256,
            "provenance_group_id": provenance,
            "unit_id": unit_id,
        })

    for row in historical_rows:
        workbook = safe_path(historical_root, row["workbook"])
        profile = ledger.profile(workbook)
        provenance = "historical-workbook:" + profile.workbook_sha256
        unit_id = provenance
        units.setdefault(unit_id, ProvenanceUnit(
            unit_id=unit_id,
            cohort="historical_100",
            provenance_group_id=provenance,
            workbook_path=workbook,
            profile=profile,
        ))
        instances.append({
            "cohort_instance_id": f"historical_100::{row['instance_id']}",
            "instance_id": row["instance_id"],
            "cohort": "historical_100",
            "workbook": relative_display(workbook),
            "workbook_sha256": profile.workbook_sha256,
            "provenance_group_id": provenance,
            "unit_id": unit_id,
        })

    for row in enron_rows:
        workbook = safe_path(enron_root, row["workbook"])
        profile = ledger.profile(workbook)
        provenance = "enron-workbook:" + profile.workbook_sha256
        unit_id = provenance
        units.setdefault(unit_id, ProvenanceUnit(
            unit_id=unit_id,
            cohort="enron",
            provenance_group_id=provenance,
            workbook_path=workbook,
            profile=profile,
        ))
        instances.append({
            "cohort_instance_id": f"enron::{row['instance_id']}",
            "instance_id": row["instance_id"],
            "cohort": "enron",
            "workbook": relative_display(workbook),
            "workbook_sha256": profile.workbook_sha256,
            "provenance_group_id": provenance,
            "unit_id": unit_id,
        })

    unit_values = sorted(units.values(), key=lambda unit: unit.unit_id)
    clusters, overlaps = structural_clusters(unit_values)
    cluster_sizes = Counter(clusters.values())
    for row in instances:
        structure_cluster = clusters[str(row.pop("unit_id"))]
        row["structure_cluster_id"] = structure_cluster
        row["outer_group_id"] = (
            structure_cluster
            if cluster_sizes[structure_cluster] > 1
            else row["provenance_group_id"]
        )
    instances.sort(key=lambda row: str(row["cohort_instance_id"]))

    profile_rows = [
        {
            "unit_id": unit.unit_id,
            "cohort": unit.cohort,
            "provenance_group_id": unit.provenance_group_id,
            "structure_cluster_id": clusters[unit.unit_id],
            **unit.profile.public_row(path=relative_display(unit.workbook_path)),
        }
        for unit in unit_values
    ]
    input_rows = [
        {"path": relative_display(path), "sha256": digest}
        for path, digest in sorted(ledger.files.items(), key=lambda item: relative_display(item[0]))
    ]

    groups_path = output_dir / "scoring_groups.csv"
    profiles_path = output_dir / "workbook_profiles.csv"
    overlaps_path = output_dir / "structural_overlap.csv"
    inputs_path = output_dir / "input_inventory.csv"
    _write_csv(groups_path, instances, (
        "cohort_instance_id", "instance_id", "cohort", "workbook",
        "workbook_sha256", "provenance_group_id", "structure_cluster_id",
        "outer_group_id",
    ))
    _write_csv(profiles_path, profile_rows, (
        "unit_id", "cohort", "provenance_group_id", "structure_cluster_id",
        "path", "workbook_sha256", "formula_count", "nonempty_cell_count",
        "sheet_count", "unsupported_formula_count", "exact_layout_signature",
        "normalized_layout_signature", "formula_multiset_signature",
        "degree_histogram_signature", "sheet_structure_signature",
        "template_signature",
    ))
    overlap_fields = (
        "left_unit_id", "right_unit_id", "left_cohort", "right_cohort",
        "cross_cohort", "exact_content", "exact_template", "formula_count_ratio",
        "formula_multiset_jaccard", "normalized_layout_jaccard",
        "degree_histogram_jaccard", "near_duplicate",
    )
    _write_csv(overlaps_path, overlaps, overlap_fields)
    _write_csv(inputs_path, input_rows, ("path", "sha256"))

    public_error_groups = {
        group for group, kinds in public_group_kinds.items() if "error" in kinds
    }
    public_control_groups = {
        group for group, kinds in public_group_kinds.items() if "control" in kinds
    }
    cross_cohort_overlaps = [row for row in overlaps if bool(row["cross_cohort"])]
    historical_units = [unit for unit in unit_values if unit.cohort == "historical_100"]
    historical_clusters = {clusters[unit.unit_id] for unit in historical_units}
    enron_units = [unit for unit in unit_values if unit.cohort == "enron"]

    facts = {
        "public_events": len(public_rows),
        "public_errors": sum(row["case_kind"] == "error" for row in public_rows),
        "public_controls": sum(row["case_kind"] == "control" for row in public_rows),
        "public_error_provenance_groups": len(public_error_groups),
        "public_control_provenance_groups": len(public_control_groups),
        "public_shared_error_control_groups": len(public_error_groups & public_control_groups),
        "historical_events": len(historical_rows),
        "historical_provenance_groups": len(historical_units),
        "historical_structure_clusters": len(historical_clusters),
        "enron_events": len(enron_rows),
        "enron_workbook_groups": len(enron_units),
        "all_provenance_units": len(unit_values),
        "all_structure_clusters": len(set(clusters.values())),
        "structural_overlap_pairs": len(overlaps),
        "cross_cohort_structural_overlap_pairs": len(cross_cohort_overlaps),
        "cross_cohort_exact_content_pairs": sum(
            bool(row["exact_content"]) for row in cross_cohort_overlaps
        ),
    }
    gates = {
        key: facts[key] == expected[key]
        for key in expected
    }
    gates.update({
        "public_shared_groups_remain_in_one_outer_fold": all(
            len({
                str(row["outer_group_id"])
                for row in instances
                if row["provenance_group_id"] == group
            }) == 1
            for group in public_error_groups & public_control_groups
        ),
        "all_instances_have_outer_group": all(row["outer_group_id"] for row in instances),
        "all_workbooks_profiled": len(profile_rows) == len(unit_values),
        "cross_cohort_exact_content_overlap_absent": (
            facts["cross_cohort_exact_content_pairs"] == 0
        ),
        "forbidden_dataset_inputs_unread": not any(
            any(path == prefix or prefix in path.parents for prefix in ledger.forbidden_prefixes)
            for path in ledger.files
        ),
        "scoring_group_export_has_no_labels": not bool(
            {"source_cell", "source_cells", "case_kind", "error_type", "correct_formula"}
            & set(instances[0])
        ),
    })
    artifacts = {
        path.name: sha256(path)
        for path in (groups_path, profiles_path, overlaps_path, inputs_path)
    }
    audit: dict[str, object] = {
        "protocol": PROTOCOL,
        "git_commit": _git_commit(),
        "audit_source": relative_display(Path(__file__)),
        "audit_source_sha256": sha256(Path(__file__)),
        "plan": "research/V5_CORE_REASSESSMENT_AND_CORE_RESET_B_PLAN.md",
        "plan_sha256": sha256(ROOT / "research/V5_CORE_REASSESSMENT_AND_CORE_RESET_B_PLAN.md"),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "near_duplicate_thresholds": NEAR_DUPLICATE_THRESHOLDS,
        "facts": facts,
        "gates": gates,
        "gate_0_passed": all(gates.values()),
        "artifacts": artifacts,
        "dataset_input_files": len(input_rows),
        "dataset_input_inventory_sha256": artifacts[inputs_path.name],
        "forbidden_dataset_prefixes": [relative_display(path) for path in forbidden],
        "forbidden_dataset_inputs_read": [],
        "data_roles": {
            "public_60_plus_30": "revealed_development",
            "historical_100": "revealed_development",
            "enron_30": "revealed_development",
            "existing_synthetic": "engineering_only",
            "old_240_plus_120": "revealed_trial_unread_until_candidate_lock",
            "new_custodian_240_plus_120": "final_blind_unread_until_prediction_lock",
        },
        "grouping_policy": {
            "public": "original_workbook_content_sha256",
            "historical": "workbook_sha256_then_structural_near_duplicate_cluster",
            "enron": "workbook_content_sha256",
            "outer_fold": "structure_cluster_when_shared_else_provenance_group",
            "leave_one_corpus_out": (
                "exclude training units sharing the held-out structure_cluster_id"
            ),
        },
        "historical_template_identity": {
            "explicit_template_ids_available": False,
            "fallback": "workbook identity plus fixed structural near-duplicate clustering",
            "limitation": (
                "No producer template IDs or original workbooks are present; undetected common "
                "generation ancestry remains an external-validity threat."
            ),
        },
    }
    _write_json(output_dir / "data_audit.json", audit)
    return audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--public-root", type=Path,
        default=ROOT / "results/v5_psl_pressure_inputs",
    )
    parser.add_argument(
        "--public-manifest", type=Path,
        default=ROOT / "results/v5_psl_pressure_inputs/public_pressure_manifest.csv",
    )
    parser.add_argument(
        "--historical-root", type=Path,
        default=ROOT / "data/v4_v52_blind/public",
    )
    parser.add_argument(
        "--historical-manifest", type=Path,
        default=ROOT / "data/v4_v52_blind/public/manifest.csv",
    )
    parser.add_argument(
        "--enron-root", type=Path,
        default=ROOT / "data/external/enron",
    )
    parser.add_argument(
        "--enron-manifest", type=Path,
        default=ROOT / "data/external/enron/manifest.csv",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=ROOT / "results/core_reset_b_phase0",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audit = build_audit(
        public_root=args.public_root,
        public_manifest=args.public_manifest,
        historical_root=args.historical_root,
        historical_manifest=args.historical_manifest,
        enron_root=args.enron_root,
        enron_manifest=args.enron_manifest,
        output_dir=args.output_dir,
    )
    print(json.dumps({
        "output": relative_display(args.output_dir / "data_audit.json"),
        "gate_0_passed": audit["gate_0_passed"],
        "facts": audit["facts"],
    }, ensure_ascii=False, indent=2))
    if audit["gate_0_passed"] is not True:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
