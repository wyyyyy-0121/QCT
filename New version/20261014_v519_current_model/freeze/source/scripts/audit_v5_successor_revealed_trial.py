"""Audit the historical V5-PSL v1 package without extracting or running models."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import stat
import sys
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v5_psl_protocol import (
    PUBLIC_FIELDS,
    canonical_json_sha256,
    parse_source_cells,
    sha256,
)
from scripts.freeze_v5_psl_candidate import _git

PROTOCOL = "v5_successor_revealed_trial_intake_v1"
V1_PACKAGE_PROTOCOL = "v5_psl_third_party_pack_v1"
ALLOWED_ROOT = (ROOT / "data/external/v5_psl/revealed_trial").resolve()
CASE_FIELDS_V1 = (
    "instance_id", "template_id", "creator_id", "workbook",
    "original_workbook", "case_kind", "error_type", "source_cells",
    "identifiability", "control_subtype", "challenge_stratum",
    "template_origin", "license_id",
)
REVIEW_FIELDS_V1 = (
    "instance_id", "reviewer_id", "source_guess", "unique_source",
    "confidence", "notes",
)
ERROR_TYPES = (
    "absolute_reference", "copy_offset", "function_replacement", "operator_replacement",
    "range_boundary", "reference_shift",
)
SECRET_COMPONENTS_V1 = (
    "cases.csv", "reviews.csv", "third_party_declaration.json",
    "design_audit.json", "case_validation.csv", "custodian_id_mapping.csv",
)
MAX_METADATA_BYTES = 64 * 1024 * 1024


def _safe_member_name(name: str) -> str:
    if not name or "\\" in name or name.startswith("/"):
        raise ValueError(f"Unsafe ZIP member path: {name!r}")
    raw_parts = name.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError(f"Unsafe ZIP member path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute():
        raise ValueError(f"Unsafe ZIP member path: {name!r}")
    return path.as_posix()


def archive_inventory(path: Path) -> list[dict[str, object]]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError(f"ZIP contains duplicate member names: {path.name}")
        result = []
        for info in archive.infolist():
            name = _safe_member_name(info.filename)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError(f"ZIP contains a symbolic link: {name}")
            result.append({
                "name": name,
                "size": info.file_size,
                "compressed_size": info.compress_size,
                "is_directory": info.is_dir(),
            })
        return result


def _member_bytes(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise ValueError(f"Archive is missing {name}") from exc
    if info.file_size > MAX_METADATA_BYTES:
        raise ValueError(f"Metadata member is unexpectedly large: {name}")
    return archive.read(info)


def _member_sha256(archive: zipfile.ZipFile, name: str) -> str:
    digest = hashlib.sha256()
    try:
        handle = archive.open(name)
    except KeyError as exc:
        raise ValueError(f"Archive is missing {name}") from exc
    with handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv_member(
    archive: zipfile.ZipFile,
    name: str,
    exact_fields: Sequence[str] | None = None,
) -> list[dict[str, str]]:
    text = _member_bytes(archive, name).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fields = tuple(reader.fieldnames or ())
    if exact_fields is not None and fields != tuple(exact_fields):
        raise ValueError(
            f"{name} fields differ: expected={','.join(exact_fields)}; "
            f"observed={','.join(fields)}"
        )
    return list(reader)


def _read_json_member(archive: zipfile.ZipFile, name: str) -> dict[str, object]:
    value = json.loads(_member_bytes(archive, name).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{name} must contain a JSON object")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    return value


def _read_precommit(value: bytes) -> dict[str, str]:
    result = {}
    for line_number, line in enumerate(value.decode("utf-8").splitlines(), 1):
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.+-]+)", line)
        if not match or match.group(2) in result:
            raise ValueError(f"Invalid secret precommit line {line_number}")
        result[match.group(2)] = match.group(1)
    expected = set(SECRET_COMPONENTS_V1) | {"SECRET.zip"}
    if set(result) != expected:
        raise ValueError("Secret precommit component inventory differs from v1")
    return result


def _audit_public(path: Path) -> tuple[dict[str, object], dict[str, str]]:
    inventory = archive_inventory(path)
    files = {str(row["name"]) for row in inventory if not row["is_directory"]}
    fixed = {
        "manifest.csv", "workbook_hashes.csv", "public_metadata.json",
        "secret_precommit_sha256.txt",
    }
    workbooks = sorted(name for name in files if name.startswith("workbooks/"))
    if len(workbooks) != 360 or any(not name.endswith(".xlsx") for name in workbooks):
        raise ValueError(f"PUBLIC must contain exactly 360 .xlsx workbooks; found {len(workbooks)}")
    if files != fixed | set(workbooks):
        raise ValueError("PUBLIC archive contains unexpected or missing files")
    with zipfile.ZipFile(path) as archive:
        manifest = _read_csv_member(archive, "manifest.csv", PUBLIC_FIELDS)
        hashes = _read_csv_member(
            archive, "workbook_hashes.csv", ("instance_id", "workbook", "sha256"),
        )
        metadata = _read_json_member(archive, "public_metadata.json")
        precommit_bytes = _member_bytes(archive, "secret_precommit_sha256.txt")
        precommit = _read_precommit(precommit_bytes)
        if len(manifest) != 360 or len({row["instance_id"] for row in manifest}) != 360:
            raise ValueError("PUBLIC manifest must contain 360 unique instances")
        if len({row["workbook"] for row in manifest}) != 360:
            raise ValueError("PUBLIC manifest workbook paths must be unique")
        hash_by_id = {row["instance_id"]: row for row in hashes}
        if len(hash_by_id) != 360 or set(hash_by_id) != {row["instance_id"] for row in manifest}:
            raise ValueError("PUBLIC workbook hash ledger differs from manifest")
        for row in manifest:
            ledger = hash_by_id[row["instance_id"]]
            if ledger["workbook"] != row["workbook"] or row["workbook"] not in workbooks:
                raise ValueError(f"PUBLIC workbook ledger mismatch: {row['instance_id']}")
            actual = _member_sha256(archive, row["workbook"])
            if ledger["sha256"] != actual:
                raise ValueError(f"PUBLIC workbook hash mismatch: {row['instance_id']}")
        if (
            metadata.get("protocol") != V1_PACKAGE_PROTOCOL
            or metadata.get("case_count") != 360
            or metadata.get("labels_in_public_manifest") != []
            or metadata.get("manifest_sha256")
            != hashlib.sha256(_member_bytes(archive, "manifest.csv")).hexdigest()
            or metadata.get("workbook_hashes_sha256")
            != hashlib.sha256(_member_bytes(archive, "workbook_hashes.csv")).hexdigest()
            or metadata.get("secret_precommit_sha256")
            != hashlib.sha256(precommit_bytes).hexdigest()
        ):
            raise ValueError("PUBLIC metadata does not reproduce")
    return {
        "instances": 360,
        "workbooks": 360,
        "member_count": len(files),
        "uncompressed_bytes": sum(int(row["size"]) for row in inventory),
        "manifest_instance_ids_sha256": canonical_json_sha256(
            sorted(row["instance_id"] for row in manifest)
        ),
    }, precommit


def _audit_case_design(cases: Sequence[Mapping[str, str]]) -> dict[str, object]:
    if len(cases) != 360 or len({row["instance_id"] for row in cases}) != 360:
        raise ValueError("SECRET cases must contain 360 unique instances")
    kinds = Counter(row["case_kind"] for row in cases)
    errors = [row for row in cases if row["case_kind"] == "error"]
    controls = [row for row in cases if row["case_kind"] == "control"]
    error_types = Counter(row["error_type"] for row in errors)
    identities = Counter(row["identifiability"] for row in errors)
    control_types = Counter(row["control_subtype"] for row in controls)
    challenge = Counter(row["challenge_stratum"] for row in errors if row["identifiability"] == "ambiguous")
    templates = Counter(row["template_id"] for row in cases)
    creators = {row["creator_id"] for row in cases}
    expected = {
        "kinds": kinds == Counter({"error": 240, "control": 120}),
        "error_types": error_types == Counter({name: 40 for name in ERROR_TYPES}),
        "identifiability": identities == Counter({"identifiable": 180, "ambiguous": 60}),
        "controls": control_types == Counter({"regular": 60, "legal_exception": 60}),
        "challenge": challenge == Counter({
            "single_source_exception_like": 30, "symmetric_multi_source": 30,
        }),
        "templates": len(templates) == 30 and set(templates.values()) == {12},
        "creator_ids": len(creators) == 6,
    }
    if not all(expected.values()):
        raise ValueError(f"SECRET v1 design counts failed: {expected}")
    for row in cases:
        sources = parse_source_cells(row["source_cells"])
        if row["case_kind"] == "control" and sources:
            raise ValueError(f"Control declares source cells: {row['instance_id']}")
        if row["case_kind"] == "error" and not sources:
            raise ValueError(f"Error lacks source cells: {row['instance_id']}")
    return {
        "case_kind_counts": dict(sorted(kinds.items())),
        "error_type_counts": dict(sorted(error_types.items())),
        "identifiability_counts": dict(sorted(identities.items())),
        "control_subtype_counts": dict(sorted(control_types.items())),
        "challenge_stratum_counts": dict(sorted(challenge.items())),
        "templates": len(templates),
        "declared_creator_ids": len(creators),
    }


def _audit_reviews(
    cases: Sequence[Mapping[str, str]],
    reviews: Sequence[Mapping[str, str]],
) -> dict[str, object]:
    errors = {row["instance_id"]: row for row in cases if row["case_kind"] == "error"}
    grouped: dict[str, list[Mapping[str, str]]] = {instance_id: [] for instance_id in errors}
    for row in reviews:
        if row["instance_id"] not in grouped:
            raise ValueError(f"Review references a non-error case: {row['instance_id']}")
        grouped[row["instance_id"]].append(row)
    if len(reviews) != 480 or any(len(rows) != 2 for rows in grouped.values()):
        raise ValueError("Every error must have exactly two v1 reviews")
    for instance_id, rows in grouped.items():
        if len({row["reviewer_id"] for row in rows}) != 2:
            raise ValueError(f"Reviewers are not distinct: {instance_id}")
        identifiable = errors[instance_id]["identifiability"] == "identifiable"
        expected_unique = "1" if identifiable else "0"
        if any(row["unique_source"] != expected_unique for row in rows):
            raise ValueError(f"Review uniqueness differs from case design: {instance_id}")
        if identifiable:
            declared = set(parse_source_cells(errors[instance_id]["source_cells"]))
            if any(set(parse_source_cells(row["source_guess"])) != declared for row in rows):
                raise ValueError(f"Reviewer source differs from declared source: {instance_id}")
    creators = {row["creator_id"] for row in cases}
    reviewers = {row["reviewer_id"] for row in reviews}
    if creators & reviewers:
        raise ValueError("Declared creator and reviewer IDs overlap")
    return {
        "reviews": len(reviews),
        "declared_reviewer_ids": len(reviewers),
        "two_reviews_per_error": True,
        "declared_creator_reviewer_ids_disjoint": True,
    }


def _audit_secret(
    path: Path,
    precommit: Mapping[str, str],
    public_ids_sha256: str,
) -> dict[str, object]:
    inventory = archive_inventory(path)
    files = {str(row["name"]) for row in inventory if not row["is_directory"]}
    originals = sorted(name for name in files if name.startswith("originals/"))
    if len(originals) != 360 or any(not name.endswith(".xlsx") for name in originals):
        raise ValueError(f"SECRET must contain exactly 360 original workbooks; found {len(originals)}")
    if files != set(SECRET_COMPONENTS_V1) | set(originals):
        raise ValueError("SECRET archive contains unexpected or missing files")
    with zipfile.ZipFile(path) as archive:
        for name in SECRET_COMPONENTS_V1:
            if _member_sha256(archive, name) != precommit[name]:
                raise ValueError(f"SECRET component differs from PUBLIC precommit: {name}")
        cases = _read_csv_member(archive, "cases.csv", CASE_FIELDS_V1)
        reviews = _read_csv_member(archive, "reviews.csv", REVIEW_FIELDS_V1)
        declaration = _read_json_member(archive, "third_party_declaration.json")
        _read_json_member(archive, "design_audit.json")
        validation = _read_csv_member(archive, "case_validation.csv")
        mapping = _read_csv_member(
            archive, "custodian_id_mapping.csv",
            ("custodian_instance_id", "public_instance_id"),
        )
    design = _audit_case_design(cases)
    review_audit = _audit_reviews(cases, reviews)
    case_ids = {row["instance_id"] for row in cases}
    if canonical_json_sha256(sorted(case_ids)) != public_ids_sha256:
        raise ValueError("SECRET case IDs differ from PUBLIC manifest IDs")
    if {row["workbook"] for row in cases} != {
        name.replace("originals/", "workbooks/", 1) for name in originals
    }:
        raise ValueError("SECRET case workbook paths differ from PUBLIC workbook inventory")
    if {row["original_workbook"] for row in cases} != set(originals):
        raise ValueError("SECRET original paths differ from archive inventory")
    if len(validation) != 360 or {row.get("instance_id") for row in validation} != case_ids:
        raise ValueError("SECRET case validation ledger differs from cases")
    if len(mapping) != 360 or {row["public_instance_id"] for row in mapping} != case_ids:
        raise ValueError("SECRET custodian mapping differs from cases")
    return {
        **design,
        **review_audit,
        "original_workbooks": len(originals),
        "member_count": len(files),
        "uncompressed_bytes": sum(int(row["size"]) for row in inventory),
        "declaration_fields": sorted(declaration),
        "identity_claims_verified_from_external_evidence": False,
    }


def directory_inventory(root: Path) -> list[dict[str, object]]:
    result = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Trial package contains a symbolic link: {path}")
        if not path.is_file():
            continue
        result.append({
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    if not result:
        raise ValueError("Trial package directory is empty")
    return result


def audit_package(root: Path) -> dict[str, object]:
    root = root.resolve()
    try:
        root.relative_to(ALLOWED_ROOT)
    except ValueError as exc:
        raise ValueError(f"Trial package must be under {ALLOWED_ROOT}") from exc
    if not root.is_dir():
        raise ValueError(f"Trial package directory does not exist: {root}")
    inventory = directory_inventory(root)
    receipts = [row for row in inventory if PurePosixPath(str(row["path"])).name == "package_receipt.json"]
    if len(receipts) != 1:
        raise ValueError(f"Expected one package_receipt.json; found {len(receipts)}")
    receipt_path = root / str(receipts[0]["path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict) or receipt.get("protocol") != V1_PACKAGE_PROTOCOL:
        raise ValueError("Historical package receipt protocol is not v1")
    receipt_dir = receipt_path.parent
    archive_paths = {}
    for role, name_field, hash_field in (
        ("public", "public_archive", "public_archive_sha256"),
        ("secret", "secret_archive", "secret_archive_sha256"),
    ):
        name = str(receipt.get(name_field, ""))
        if PurePosixPath(name).name != name:
            raise ValueError(f"Receipt {name_field} must be a plain filename")
        path = receipt_dir / name
        if not path.is_file() or sha256(path) != receipt.get(hash_field):
            raise ValueError(f"Receipt {role} archive hash failed")
        archive_paths[role] = path
    public, precommit = _audit_public(archive_paths["public"])
    if precommit["SECRET.zip"] != sha256(archive_paths["secret"]):
        raise ValueError("PUBLIC precommit does not bind the SECRET archive")
    secret = _audit_secret(
        archive_paths["secret"], precommit,
        str(public["manifest_instance_ids_sha256"]),
    )
    with zipfile.ZipFile(archive_paths["secret"]) as archive:
        design_hash = _member_sha256(archive, "design_audit.json")
    if receipt.get("design_audit_sha256") != design_hash or receipt.get("case_count") != 360:
        raise ValueError("Package receipt design audit or case count differs")
    return {
        "protocol": PROTOCOL,
        "data_role": "revealed_trial",
        "package_protocol": V1_PACKAGE_PROTOCOL,
        "package_root": root.relative_to(ROOT).as_posix(),
        "git_commit": _git("rev-parse", "HEAD"),
        "package_receipt_sha256": sha256(receipt_path),
        "directory_file_count": len(inventory),
        "directory_bytes": sum(int(row["bytes"]) for row in inventory),
        "directory_inventory_sha256": canonical_json_sha256(inventory),
        "directory_inventory": inventory,
        "public_archive_sha256": sha256(archive_paths["public"]),
        "secret_archive_sha256": sha256(archive_paths["secret"]),
        "public_audit": public,
        "secret_audit": secret,
        "safe_to_begin_revealed_trial_prediction": True,
        "workbook_semantics_validated": False,
        "declared_six_creator_identity_independently_verified": False,
        "external_or_blind_claim_forbidden": True,
        "model_invocations": [],
        "held_out_successor_confirmation_files_read": [],
    }


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit the historical 240+120 package as revealed trial data",
    )
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise SystemExit("Revealed-trial intake requires a clean Git worktree")
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"Refusing to overwrite intake receipt: {output}")
    try:
        payload = audit_package(args.package_root)
        payload["source_sha256"] = sha256(Path(__file__).resolve())
        _write_json_atomic(output, payload)
    except (OSError, ValueError, KeyError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise SystemExit(f"Revealed-trial intake refused: {exc}") from exc
    print(output)


if __name__ == "__main__":
    main()
