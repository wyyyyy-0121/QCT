"""Shared contracts for the V5-PSL independent confirmation protocol."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence


PUBLIC_FIELDS = ("instance_id", "workbook")
CASE_FIELDS = (
    "instance_id",
    "template_id",
    "creator_id",
    "workbook",
    "original_workbook",
    "case_kind",
    "error_type",
    "source_cells",
    "identifiability",
    "control_subtype",
    "challenge_stratum",
    "template_origin",
    "license_id",
)
REVIEW_FIELDS = (
    "instance_id",
    "reviewer_id",
    "source_guess",
    "unique_source",
    "confidence",
    "notes",
)
ERROR_TYPES = (
    "absolute_reference",
    "copy_offset",
    "function_replacement",
    "operator_replacement",
    "range_boundary",
    "reference_shift",
)
EXPECTED_COUNTS = {
    "total": 360,
    "error": 240,
    "control": 120,
    "identifiable": 180,
    "ambiguous": 60,
    "regular_control": 60,
    "legal_exception_control": 60,
    "single_source_exception_like": 30,
    "symmetric_multi_source": 30,
    "templates": 30,
    "creators": 6,
    "self_authored_templates": 20,
    "licensed_public_templates": 10,
}
PREDICTION_METHODS = (
    "v4_r1",
    "v4_2_review_b",
    "v4_3_semantic_c",
    "v5_psl_dev1",
)
ACTION_STATES = {"localized", "review"}
DIAGNOSTIC_STATES = {
    "localized", "review", "abstain_unidentifiable", "unsupported",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def model_output_projection(value: object) -> object:
    """Remove runtime-only fields while preserving every diagnostic decision."""
    if isinstance(value, Mapping):
        return {
            str(key): model_output_projection(item)
            for key, item in value.items()
            if key not in {
                "elapsed_seconds", "localization_seconds", "runtime_seconds",
            }
        }
    if isinstance(value, (list, tuple)):
        return [model_output_projection(item) for item in value]
    return value


def aggregate_file_sha256(files: Iterable[tuple[str, Path]]) -> str:
    """Hash an ordered name/file inventory without depending on absolute paths."""
    digest = hashlib.sha256()
    for name, path in sorted(files):
        if not name or "\\" in name or Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError(f"Unsafe aggregate file name: {name!r}")
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def deterministic_zip(output: Path, root: Path) -> None:
    """Write the canonical archive format used for third-party commitments."""
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9,
    ) as archive:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            name = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def deterministic_zip_sha256(root: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="v5_psl_zip_hash_") as directory:
        output = Path(directory) / "archive.zip"
        deterministic_zip(output, root)
        return sha256(output)


def read_sha256_commitments(
    path: Path,
    *,
    required_names: Iterable[str] | None = None,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise ValueError(f"Malformed commitment at line {line_number}")
        digest, name = parts[0].lower(), parts[1].strip()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"Invalid SHA-256 at line {line_number}")
        if not name or name in result or "\\" in name or Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError(f"Unsafe or duplicate commitment name: {name!r}")
        result[name] = digest
    if required_names is not None and set(result) != set(required_names):
        raise ValueError(
            f"Commitment names differ: expected={sorted(required_names)}, "
            f"observed={sorted(result)}"
        )
    return result


def read_csv(path: Path, *, exact_fields: Sequence[str] | None = None) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if exact_fields is not None and tuple(reader.fieldnames or ()) != tuple(exact_fields):
            raise ValueError(
                f"{path.name} must contain exactly {','.join(exact_fields)}; "
                f"found {','.join(reader.fieldnames or ())}"
            )
        return list(reader)


def safe_path(root: Path, relative: str) -> Path:
    if not relative or "\\" in relative or Path(relative).is_absolute():
        raise ValueError(f"Non-portable path: {relative!r}")
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Path escapes root: {relative}") from exc
    if not path.is_file():
        raise ValueError(f"Missing file: {relative}")
    return path


def canonical_cell(value: str) -> str:
    if "!" not in value:
        raise ValueError(f"Cell must be sheet-qualified: {value}")
    sheet, address = value.rsplit("!", 1)
    sheet = sheet.strip()
    if len(sheet) >= 2 and sheet.startswith(chr(39)) and sheet.endswith(chr(39)):
        sheet = sheet[1:-1].replace("''", "'")
    address = address.strip().replace("$", "").upper()
    if not sheet or not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]*", address):
        raise ValueError(f"Invalid cell address: {value}")
    return f"{sheet}!{address}"


def parse_source_cells(value: str) -> tuple[str, ...]:
    result = []
    for item in value.split(";"):
        item = item.strip()
        if not item:
            continue
        result.append(canonical_cell(item))
    return tuple(sorted(set(result)))


def validate_public_manifest(path: Path, root: Path, *, expected_count: int = 360) -> list[dict[str, str]]:
    rows = read_csv(path, exact_fields=PUBLIC_FIELDS)
    if len(rows) != expected_count:
        raise ValueError(f"Public manifest must contain {expected_count} rows")
    identifiers = [row["instance_id"] for row in rows]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Public manifest instance_id values must be unique")
    workbook_names = [row["workbook"] for row in rows]
    if len(set(workbook_names)) != len(workbook_names):
        raise ValueError("Public manifest workbook paths must be unique")
    for row in rows:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", row["instance_id"]):
            raise ValueError(f"Unsafe instance_id: {row['instance_id']}")
        workbook = safe_path(root, row["workbook"])
        if workbook.suffix.lower() != ".xlsx":
            raise ValueError(f"Only macro-free .xlsx files are accepted: {row['workbook']}")
    return rows


def audit_design(
    cases: Sequence[Mapping[str, str]],
    reviews: Sequence[Mapping[str, str]],
    declaration: Mapping[str, object],
) -> dict[str, object]:
    identifiers = [row.get("instance_id", "") for row in cases]
    if len(cases) != EXPECTED_COUNTS["total"] or len(set(identifiers)) != len(cases):
        raise ValueError("Design requires exactly 360 unique instances")
    if any(not re.fullmatch(r"[A-Za-z0-9._-]+", value) for value in identifiers):
        raise ValueError("Every instance_id must be portable and non-empty")

    kinds = Counter(row.get("case_kind") for row in cases)
    if kinds != Counter({"error": 240, "control": 120}):
        raise ValueError(f"Expected 240 error and 120 control cases; found {dict(kinds)}")
    errors = [row for row in cases if row.get("case_kind") == "error"]
    controls = [row for row in cases if row.get("case_kind") == "control"]
    error_types = Counter(row.get("error_type") for row in errors)
    if error_types != Counter({name: 40 for name in ERROR_TYPES}):
        raise ValueError(f"Each error type must contain 40 cases; found {dict(error_types)}")
    identities = Counter(row.get("identifiability") for row in errors)
    if identities != Counter({"identifiable": 180, "ambiguous": 60}):
        raise ValueError(f"Expected 180 identifiable and 60 ambiguous errors; found {dict(identities)}")
    control_types = Counter(row.get("control_subtype") for row in controls)
    if control_types != Counter({"regular": 60, "legal_exception": 60}):
        raise ValueError(f"Control balance is invalid: {dict(control_types)}")
    ambiguous_types = Counter(
        row.get("challenge_stratum") for row in errors if row.get("identifiability") == "ambiguous"
    )
    if ambiguous_types != Counter({"single_source_exception_like": 30, "symmetric_multi_source": 30}):
        raise ValueError(f"Ambiguity strata are invalid: {dict(ambiguous_types)}")

    sources_by_id: dict[str, tuple[str, ...]] = {}
    for row in cases:
        instance_id = str(row.get("instance_id", ""))
        try:
            sources = parse_source_cells(str(row.get("source_cells", "")))
        except ValueError as exc:
            raise ValueError(f"Invalid source_cells for {instance_id}: {exc}") from exc
        sources_by_id[instance_id] = sources
        if row.get("case_kind") == "control":
            if sources:
                raise ValueError(f"Control {instance_id} must not declare source cells")
            if row.get("error_type") not in {"", None, "not_applicable"}:
                raise ValueError(f"Control {instance_id} must not declare an error type")
            if row.get("identifiability") not in {"", None, "not_applicable"}:
                raise ValueError(f"Control {instance_id} must not declare identifiability")
            if row.get("challenge_stratum") not in {"", None, "not_applicable"}:
                raise ValueError(f"Control {instance_id} must not declare a challenge stratum")
            continue
        if row.get("control_subtype") not in {"", None, "not_applicable"}:
            raise ValueError(f"Error {instance_id} must not declare a control subtype")
        identity = row.get("identifiability")
        challenge = row.get("challenge_stratum")
        if identity == "identifiable" and len(sources) != 1:
            raise ValueError(f"Identifiable error {instance_id} requires exactly one source cell")
        if identity == "identifiable" and challenge not in {"", None, "not_applicable"}:
            raise ValueError(f"Identifiable error {instance_id} must not use an ambiguity stratum")
        if challenge == "single_source_exception_like" and len(sources) != 1:
            raise ValueError(f"Single-source ambiguity {instance_id} requires one changed source")
        if challenge == "symmetric_multi_source" and not 2 <= len(sources) <= 5:
            raise ValueError(f"Symmetric ambiguity {instance_id} requires 2 to 5 sources")

    by_template: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    creator_templates: dict[str, set[str]] = defaultdict(set)
    for row in cases:
        by_template[row.get("template_id", "")].append(row)
        creator_templates[row.get("creator_id", "")].add(row.get("template_id", ""))
    if "" in by_template or "" in creator_templates:
        raise ValueError("Every template and creator identifier must be non-empty")
    if len(by_template) != 30 or any(len(rows) != 12 for rows in by_template.values()):
        raise ValueError("Design requires 30 templates with exactly 12 cases each")
    if len(creator_templates) != 6 or any(len(values) != 5 for values in creator_templates.values()):
        raise ValueError("Design requires 6 creators with exactly 5 templates each")
    for template_id, rows in by_template.items():
        if len({row.get("creator_id") for row in rows}) != 1:
            raise ValueError(f"Template {template_id} has multiple creators")
        if len({row.get("template_origin") for row in rows}) != 1:
            raise ValueError(f"Template {template_id} has inconsistent provenance")
        if len({row.get("license_id") for row in rows}) != 1:
            raise ValueError(f"Template {template_id} has inconsistent license identifiers")
        template_kinds = Counter(row.get("case_kind") for row in rows)
        template_identity = Counter(
            row.get("identifiability") for row in rows if row.get("case_kind") == "error"
        )
        template_controls = Counter(
            row.get("control_subtype") for row in rows if row.get("case_kind") == "control"
        )
        if template_kinds != Counter({"error": 8, "control": 4}):
            raise ValueError(f"Template {template_id} must contain 8 errors and 4 controls")
        if template_identity != Counter({"identifiable": 6, "ambiguous": 2}):
            raise ValueError(f"Template {template_id} must contain 6 identifiable and 2 ambiguous errors")
        if template_controls != Counter({"regular": 2, "legal_exception": 2}):
            raise ValueError(f"Template {template_id} control composition is invalid")

    origins = Counter({
        template_id: rows[0].get("template_origin", "")
        for template_id, rows in by_template.items()
    }.values())
    if origins != Counter({"self_authored": 20, "licensed_public": 10}):
        raise ValueError(f"Template provenance must be 20 self-authored and 10 public; found {dict(origins)}")
    if any(not rows[0].get("license_id") for rows in by_template.values()):
        raise ValueError("Every template requires a license or creator-permission identifier")

    error_ids = {row["instance_id"] for row in errors}
    review_counts = Counter(row.get("instance_id") for row in reviews)
    if set(review_counts) != error_ids or any(count != 2 for count in review_counts.values()):
        raise ValueError("Every error case requires exactly two independent review records")
    reviews_by_id: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in reviews:
        if row.get("unique_source") not in {"0", "1"}:
            raise ValueError("Review unique_source must be 0 or 1")
        if not row.get("reviewer_id"):
            raise ValueError("Review reviewer_id must be non-empty")
        reviews_by_id[str(row.get("instance_id", ""))].append(row)
    reviewer_ids = {row.get("reviewer_id") for row in reviews}
    if len(reviewer_ids) < 2:
        raise ValueError("At least two reviewers are required")
    overlapping_roles = set(creator_templates) & reviewer_ids
    if overlapping_roles:
        raise ValueError(
            "Creators and reviewers must be disjoint identities: "
            + ", ".join(sorted(str(value) for value in overlapping_roles))
        )
    cases_by_id = {str(row["instance_id"]): row for row in cases}
    for instance_id, rows in reviews_by_id.items():
        if len({row.get("reviewer_id") for row in rows}) != 2:
            raise ValueError(f"Error {instance_id} requires two distinct reviewers")
        case = cases_by_id[instance_id]
        expected_unique = "1" if case.get("identifiability") == "identifiable" else "0"
        if any(row.get("unique_source") != expected_unique for row in rows):
            raise ValueError(f"Review uniqueness disagrees with design for {instance_id}")
        if expected_unique == "1":
            expected_sources = set(sources_by_id[instance_id])
            for review in rows:
                guesses = set(parse_source_cells(str(review.get("source_guess", ""))))
                if guesses != expected_sources:
                    raise ValueError(f"Reviewer source guess disagrees for {instance_id}")

    required_declaration = {
        "independent_custodian": True,
        "model_was_run": False,
        "labels_withheld_until_prediction_lock": True,
        "permissions_and_anonymization_checked": True,
        "all_cases_recalculated_without_runtime_errors": True,
        "reviewers_worked_independently": True,
        "creators_did_not_serve_as_reviewers": True,
        "creators_and_reviewers_received_no_model_outputs": True,
    }
    for field, expected in required_declaration.items():
        if declaration.get(field) is not expected:
            raise ValueError(f"Declaration requires {field}={expected}")
    required_declaration_text = (
        "custodian_id", "calculation_engine", "calculation_engine_version",
    )
    if any(not str(declaration.get(field, "")).strip() for field in required_declaration_text):
        raise ValueError("Declaration must identify the custodian and calculation engine")
    custodian_id = str(declaration["custodian_id"])
    if custodian_id in set(creator_templates) | reviewer_ids:
        raise ValueError("Custodian, creator, and reviewer identities must be disjoint")
    for field in ("permission_evidence_sha256", "anonymization_evidence_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(declaration.get(field, ""))):
            raise ValueError(f"Declaration requires a valid {field}")

    return {
        "protocol": "v5_psl_third_party_design_audit_v1",
        "passed": True,
        "counts": {
            "total": len(cases),
            "errors": len(errors),
            "controls": len(controls),
            "templates": len(by_template),
            "creators": len(creator_templates),
            "reviews": len(reviews),
        },
        "error_types": dict(sorted(error_types.items())),
        "identifiability": dict(sorted(identities.items())),
        "control_subtypes": dict(sorted(control_types.items())),
        "template_origins": dict(sorted(origins.items())),
        "declaration_sha256": canonical_json_sha256(declaration),
    }


def source_rank(ranking: Iterable[Mapping[str, object]], sources: set[str]) -> int | None:
    canonical_sources = {canonical_cell(item) for item in sources}
    ranks = [
        int(row["rank"])
        for row in ranking
        if canonical_cell(str(row.get("cell", ""))) in canonical_sources
    ]
    return min(ranks) if ranks else None


def validate_complete_ranking(
    ranking: Sequence[Mapping[str, object]],
    formula_cells: Iterable[str],
) -> None:
    expected = {canonical_cell(cell) for cell in formula_cells}
    ranks = [row.get("rank") for row in ranking]
    if ranks != list(range(1, len(ranking) + 1)):
        raise ValueError("Ranking positions must be consecutive integers starting at 1")
    observed = [canonical_cell(str(row.get("cell", ""))) for row in ranking]
    if len(observed) != len(set(observed)):
        raise ValueError("Ranking contains duplicate formula cells")
    if set(observed) != expected:
        raise ValueError(
            f"Ranking is incomplete: missing={len(expected - set(observed))}, "
            f"extra={len(set(observed) - expected)}"
        )


def combined_shards_sha256(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


__all__ = [
    "ACTION_STATES", "CASE_FIELDS", "DIAGNOSTIC_STATES", "ERROR_TYPES",
    "EXPECTED_COUNTS", "PREDICTION_METHODS", "PUBLIC_FIELDS", "REVIEW_FIELDS",
    "aggregate_file_sha256", "audit_design", "canonical_cell",
    "canonical_json_sha256", "combined_shards_sha256", "deterministic_zip",
    "deterministic_zip_sha256", "model_output_projection", "parse_source_cells", "read_csv",
    "read_sha256_commitments", "safe_path", "sha256", "source_rank",
    "validate_complete_ranking", "validate_public_manifest",
]
