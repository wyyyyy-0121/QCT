"""Validate and package the external V5-PSL 240+120 confirmation corpus.

This utility never generates workbooks and never invokes a FormulaGuard
diagnostic method.  It is intended to be run by the independent custodian on
workbook pairs prepared outside this repository.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.formula import FormulaSyntaxError, formula_fingerprint, normalized_formula
from formulaguard.v5_psl_protocol import (
    CASE_FIELDS,
    PUBLIC_FIELDS,
    aggregate_file_sha256,
    audit_design,
    canonical_cell,
    canonical_json_sha256,
    deterministic_zip,
    parse_source_cells,
    read_csv,
    safe_path,
    sha256,
)
from formulaguard.workbook import CellKey, WorkbookModel


PACKAGE_VERSION = "v5_psl_single_custodian_pack_v2"
SECRET_COMPONENTS = (
    "cases.csv",
    "third_party_declaration.json",
    "design_audit.json",
    "case_validation.csv",
    "custodian_id_mapping.csv",
)


def write_csv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _formula_signature(formula: str, address: str) -> str:
    try:
        return formula_fingerprint(formula, address)
    except FormulaSyntaxError:
        return "UNSUPPORTED:" + normalized_formula(formula)


def formula_change_signature(
    original: WorkbookModel,
    changed: WorkbookModel,
    cells: Iterable[CellKey],
) -> str:
    rows = []
    for sheet, address in sorted(cells):
        rows.append({
            "sheet": sheet,
            "original": _formula_signature(original.formulas[(sheet, address)], address),
            "changed": _formula_signature(changed.formulas[(sheet, address)], address),
        })
    return canonical_json_sha256(rows)


def _has_forbidden_package_parts(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        names = {name.lower() for name in archive.namelist()}
        forbidden = [
            name for name in names
            if "vbaproject" in name
            or name.startswith("xl/externallinks/")
            or name == "xl/connections.xml"
        ]
    return sorted(forbidden)


def _same_nonformula_content(left: WorkbookModel, right: WorkbookModel) -> bool:
    formula_cells = set(left.formulas) | set(right.formulas)
    left_values = {key: value for key, value in left.cells.items() if key not in formula_cells}
    right_values = {key: value for key, value in right.cells.items() if key not in formula_cells}
    if left_values != right_values or left.sheet_visibility != right.sheet_visibility:
        return False
    all_cells = set(left.cells) | set(right.cells) | formula_cells
    return all(
        left.is_visible(key) == right.is_visible(key)
        and left.number_format(key) == right.number_format(key)
        for key in all_cells
    )


def _evaluation_evidence(original: WorkbookModel, changed: WorkbookModel) -> dict[str, object]:
    original_values, original_errors = original.evaluate()
    changed_values, changed_errors = changed.evaluate()
    formula_cells = set(changed.formulas)
    covered = formula_cells - set(original_errors) - set(changed_errors)
    changed_values_count = sum(
        original_values.get(cell) != changed_values.get(cell)
        for cell in covered
    )
    return {
        "internal_formula_coverage": len(covered) / max(1, len(formula_cells)),
        "internal_original_errors": len(set(original_errors) & formula_cells),
        "internal_changed_errors": len(set(changed_errors) & formula_cells),
        "internally_observed_changed_formula_values": changed_values_count,
    }


def validate_case_pair(
    row: Mapping[str, str],
    raw_root: Path,
    *,
    development_signatures: set[str],
    workbook_root: Path | None = None,
    original_root: Path | None = None,
) -> dict[str, object]:
    instance_id = str(row["instance_id"])
    workbook_path = safe_path(workbook_root or raw_root, str(row["workbook"]))
    original_path = safe_path(original_root or raw_root, str(row["original_workbook"]))
    if workbook_path.suffix.lower() != ".xlsx" or original_path.suffix.lower() != ".xlsx":
        raise ValueError(f"{instance_id}: only macro-free .xlsx workbook pairs are accepted")
    forbidden = _has_forbidden_package_parts(workbook_path) + _has_forbidden_package_parts(original_path)
    if forbidden:
        raise ValueError(f"{instance_id}: macro, connection, or external-link parts found: {forbidden[:5]}")

    try:
        changed = WorkbookModel.from_xlsx(workbook_path)
        original = WorkbookModel.from_xlsx(original_path)
    except Exception as exc:
        raise ValueError(f"{instance_id}: workbook parse failed: {exc}") from exc
    if not changed.formulas:
        raise ValueError(f"{instance_id}: workbook contains no formula cells")
    if any("[" in formula or "]" in formula for formula in (*changed.formulas.values(), *original.formulas.values())):
        raise ValueError(f"{instance_id}: formulas contain an external-workbook reference")
    if set(changed.formulas) != set(original.formulas):
        raise ValueError(f"{instance_id}: formula-cell set differs from the original")
    if not _same_nonformula_content(changed, original):
        raise ValueError(f"{instance_id}: non-formula content, visibility, or number formats changed")

    differences = {
        key for key in changed.formulas
        if normalized_formula(changed.formulas[key]) != normalized_formula(original.formulas[key])
    }
    declared = {
        tuple(canonical_cell(value).rsplit("!", 1))
        for value in parse_source_cells(str(row.get("source_cells", "")))
    }
    kind = row["case_kind"]
    if kind == "control" and differences:
        raise ValueError(f"{instance_id}: control workbook differs at {len(differences)} formulas")
    if kind == "error" and differences != declared:
        observed = sorted(f"{sheet}!{address}" for sheet, address in differences)
        expected = sorted(f"{sheet}!{address}" for sheet, address in declared)
        raise ValueError(f"{instance_id}: formula differences {observed} != declared sources {expected}")

    signature = formula_change_signature(original, changed, differences) if differences else ""
    if signature and signature in development_signatures:
        raise ValueError(f"{instance_id}: formula transformation overlaps the development inventory")
    evidence = _evaluation_evidence(original, changed)
    if kind == "error" and evidence["internal_formula_coverage"] == 1.0:
        if evidence["internally_observed_changed_formula_values"] == 0:
            raise ValueError(f"{instance_id}: injected formula change has no internally observable effect")
    if kind == "control" and evidence["internal_formula_coverage"] == 1.0:
        if evidence["internally_observed_changed_formula_values"] != 0:
            raise ValueError(f"{instance_id}: unchanged control recalculates differently from its original")

    return {
        "instance_id": instance_id,
        "workbook_path": workbook_path,
        "original_path": original_path,
        "workbook_sha256": sha256(workbook_path),
        "original_sha256": sha256(original_path),
        "formula_count": len(changed.formulas),
        "changed_formula_count": len(differences),
        "formula_change_signature": signature,
        **evidence,
    }


def _read_development_signatures(path: Path) -> set[str]:
    result = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = line.strip().lower()
        if not value or value.startswith("#"):
            continue
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError(f"Invalid development signature at line {line_number}")
        result.add(value)
    if not result:
        raise ValueError("Development signature inventory must not be empty")
    return result


def _opaque_ids(rows: Sequence[Mapping[str, str]], key: bytes) -> dict[str, str]:
    result = {
        str(row["instance_id"]): "psl_" + hmac.new(
            key, str(row["instance_id"]).encode("utf-8"), hashlib.sha256,
        ).hexdigest()[:16]
        for row in rows
    }
    if len(set(result.values())) != len(rows):
        raise ValueError("Opaque identifier collision")
    return result


def build_packages(
    raw_root: Path,
    output: Path,
    *,
    pseudonym_key: bytes,
    development_signatures: set[str],
) -> dict[str, object]:
    if len(pseudonym_key) < 32:
        raise ValueError("Pseudonym key must contain at least 32 bytes")
    stage = output / "stage"
    if stage.exists() or output.joinpath("FormulaGuard_V5_PSL_PUBLIC_360.zip").exists():
        raise ValueError(f"Refusing to overwrite an existing package stage: {output}")

    cases = read_csv(raw_root / "cases.csv", exact_fields=CASE_FIELDS)
    declaration_value = json.loads(
        (raw_root / "third_party_declaration.json").read_text(encoding="utf-8")
    )
    if not isinstance(declaration_value, dict):
        raise ValueError("third_party_declaration.json must contain a JSON object")
    declaration: dict[str, object] = declaration_value
    design_audit = audit_design(cases, declaration)
    mapping = _opaque_ids(cases, pseudonym_key)

    public_root = stage / "PUBLIC"
    secret_root = stage / "SECRET"
    (public_root / "workbooks").mkdir(parents=True)
    (secret_root / "originals").mkdir(parents=True)
    packaged_cases: list[dict[str, str]] = []
    public_rows: list[dict[str, str]] = []
    public_hash_rows: list[dict[str, str]] = []
    validation_rows: list[dict[str, object]] = []
    seen_workbook_hashes: set[str] = set()

    for index, row in enumerate(cases, 1):
        evidence = validate_case_pair(
            row, raw_root, development_signatures=development_signatures,
        )
        if evidence["workbook_sha256"] in seen_workbook_hashes:
            raise ValueError(f"{row['instance_id']}: duplicate public workbook bytes")
        seen_workbook_hashes.add(str(evidence["workbook_sha256"]))
        opaque_id = mapping[row["instance_id"]]
        public_name = f"workbooks/{opaque_id}.xlsx"
        original_name = f"originals/{opaque_id}.xlsx"
        shutil.copyfile(Path(evidence["workbook_path"]), public_root / public_name)
        shutil.copyfile(Path(evidence["original_path"]), secret_root / original_name)
        public_rows.append({"instance_id": opaque_id, "workbook": public_name})
        public_hash_rows.append({
            "instance_id": opaque_id,
            "workbook": public_name,
            "sha256": str(evidence["workbook_sha256"]),
        })
        packaged = dict(row)
        packaged.update({
            "instance_id": opaque_id,
            "workbook": public_name,
            "original_workbook": original_name,
        })
        packaged_cases.append(packaged)
        validation_rows.append({
            key: value for key, value in {**evidence, "instance_id": opaque_id}.items()
            if key not in {"workbook_path", "original_path"}
        })
        if index % 25 == 0 or index == len(cases):
            print(f"[{index}/{len(cases)}] external workbook pairs validated", flush=True)

    packaged_cases.sort(key=lambda row: row["instance_id"])
    public_rows.sort(key=lambda row: row["instance_id"])
    public_hash_rows.sort(key=lambda row: row["instance_id"])
    validation_rows.sort(key=lambda row: str(row["instance_id"]))

    write_csv(public_root / "manifest.csv", PUBLIC_FIELDS, public_rows)
    write_csv(
        public_root / "workbook_hashes.csv",
        ("instance_id", "workbook", "sha256"),
        public_hash_rows,
    )
    write_csv(secret_root / "cases.csv", CASE_FIELDS, packaged_cases)
    write_json(secret_root / "third_party_declaration.json", declaration)
    write_json(secret_root / "design_audit.json", design_audit)
    write_csv(
        secret_root / "case_validation.csv",
        tuple(validation_rows[0]),
        validation_rows,
    )
    write_csv(
        secret_root / "custodian_id_mapping.csv",
        ("custodian_instance_id", "public_instance_id"),
        [
            {"custodian_instance_id": raw_id, "public_instance_id": public_id}
            for raw_id, public_id in sorted(mapping.items(), key=lambda item: item[1])
        ],
    )

    secret_zip = output / "FormulaGuard_V5_PSL_SECRET_360.zip"
    output.mkdir(parents=True, exist_ok=True)
    deterministic_zip(secret_zip, secret_root)
    commitments = {
        name: sha256(secret_root / name)
        for name in SECRET_COMPONENTS
    }
    commitments["SECRET.zip"] = sha256(secret_zip)
    commitment_text = "".join(
        f"{digest}  {name}\n" for name, digest in sorted(commitments.items())
    )
    (public_root / "secret_precommit_sha256.txt").write_text(commitment_text, encoding="utf-8")

    public_metadata = {
        "protocol": PACKAGE_VERSION,
        "case_count": len(public_rows),
        "manifest_sha256": sha256(public_root / "manifest.csv"),
        "workbook_hashes_sha256": sha256(public_root / "workbook_hashes.csv"),
        "workbooks_aggregate_sha256": aggregate_file_sha256(
            (row["workbook"], public_root / row["workbook"]) for row in public_rows
        ),
        "secret_precommit_sha256": sha256(public_root / "secret_precommit_sha256.txt"),
        "public_manifest_fields": list(PUBLIC_FIELDS),
        "labels_in_public_manifest": [],
        "opaque_identifiers": True,
        "raw_filenames_disclosed": False,
    }
    write_json(public_root / "public_metadata.json", public_metadata)
    public_zip = output / "FormulaGuard_V5_PSL_PUBLIC_360.zip"
    deterministic_zip(public_zip, public_root)
    receipt = {
        "protocol": PACKAGE_VERSION,
        "public_archive": public_zip.name,
        "public_archive_sha256": sha256(public_zip),
        "secret_archive": secret_zip.name,
        "secret_archive_sha256": sha256(secret_zip),
        "public_manifest_sha256": public_metadata["manifest_sha256"],
        "secret_precommit_sha256": public_metadata["secret_precommit_sha256"],
        "design_audit_sha256": sha256(secret_root / "design_audit.json"),
        "development_signature_inventory_sha256": canonical_json_sha256(
            sorted(development_signatures)
        ),
        "case_count": len(public_rows),
        "model_invocations": [],
        "custodian_releases_before_candidate_lock": [
            "public_archive_sha256", "secret_archive_sha256",
        ],
    }
    write_json(output / "package_receipt.json", receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Package a single-custodian V5-PSL 240+120 confirmation corpus",
    )
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pseudonym-key-file", type=Path, required=True)
    parser.add_argument("--development-signatures", type=Path, required=True)
    args = parser.parse_args()
    try:
        key = args.pseudonym_key_file.read_bytes()
        signatures = _read_development_signatures(args.development_signatures)
        receipt = build_packages(
            args.raw.resolve(), args.output.resolve(),
            pseudonym_key=key,
            development_signatures=signatures,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise SystemExit(f"V5-PSL third-party packaging refused: {exc}") from exc
    print(args.output / "package_receipt.json")
    print(f"PUBLIC SHA-256: {receipt['public_archive_sha256']}")
    print(f"SECRET SHA-256: {receipt['secret_archive_sha256']}")


if __name__ == "__main__":
    main()
