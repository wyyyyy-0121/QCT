"""Validate and package the final, genuinely third-party V6 600-case corpus.

Final mode never calls the FormulaGuard synthetic generator.  It only validates
workbooks and labels prepared outside the project, then creates the public and
secret archives.  Non-final mode remains a small engineering fixture generator
for testing the archive protocol; it must never be described as independent.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import shutil
import sys
import zipfile
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build_v6_dataset import (
    Case,
    COMPLEXITIES,
    DEPTHS,
    ERROR_TYPES,
    TOPOLOGIES,
    build_case,
    write_xlsx,
)
from formulaguard.formula import normalized_formula
from formulaguard.workbook import WorkbookModel


TRUTHY = {"1", "yes", "true", "y"}
FINAL_CASE_FIELDS = {
    "instance_id", "template_id", "error_type", "topology", "complexity",
    "depth", "construction_mode", "non_simple_neighbor_shift",
    "mutant_workbook", "original_workbook", "source_cell", "correct_formula",
    "mutated_formula", "sink_cell", "source_origin", "notes",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise SystemExit(f"CSV has no header: {path}")
        return list(reader)


def zip_tree(output: Path, files: list[tuple[Path, str]]):
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for source, name in sorted(files, key=lambda item: item[1]):
            archive.write(source, name)


def cell_key(text: str) -> tuple[str, str]:
    if "!" not in text:
        raise ValueError(f"cell must include a worksheet: {text}")
    sheet, address = text.rsplit("!", 1)
    return sheet.strip("'"), address.replace("$", "").upper()


def same_constants(left: WorkbookModel, right: WorkbookModel) -> bool:
    formula_cells = set(left.formulas) | set(right.formulas)
    left_values = {key: value for key, value in left.cells.items() if key not in formula_cells}
    right_values = {key: value for key, value in right.cells.items() if key not in formula_cells}
    return left_values == right_values


def validate_external_case(row: dict[str, str], descriptor_ids: set[str]) -> dict[str, object]:
    missing = sorted(FINAL_CASE_FIELDS - set(row))
    if missing:
        raise SystemExit(f"Final case manifest is missing columns: {missing}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", row["instance_id"]):
        raise SystemExit(f"Unsafe instance_id: {row['instance_id']}")
    for field in (
        "template_id", "error_type", "topology", "complexity", "depth",
        "construction_mode", "mutant_workbook", "original_workbook", "source_cell",
        "correct_formula", "mutated_formula", "sink_cell", "source_origin",
    ):
        if not row[field].strip():
            raise SystemExit(f"Empty required field {field}: {row['instance_id']}")
    if row["template_id"] not in descriptor_ids:
        raise SystemExit(f"Unknown template_id for {row['instance_id']}: {row['template_id']}")
    if row["error_type"] not in ERROR_TYPES:
        raise SystemExit(f"Invalid error_type for {row['instance_id']}")
    if row["topology"] not in TOPOLOGIES or row["complexity"] not in COMPLEXITIES or row["depth"] not in DEPTHS:
        raise SystemExit(f"Invalid topology, complexity, or depth for {row['instance_id']}")
    if row["construction_mode"] not in {"programmatic", "semi_manual"}:
        raise SystemExit(f"Invalid construction_mode for {row['instance_id']}")
    mutant_path = Path(row["mutant_workbook"]).expanduser().resolve()
    original_path = Path(row["original_workbook"]).expanduser().resolve()
    if mutant_path.suffix.lower() != ".xlsx" or original_path.suffix.lower() != ".xlsx":
        raise SystemExit(f"Only .xlsx workbooks are accepted: {row['instance_id']}")
    if not mutant_path.is_file() or not original_path.is_file():
        raise SystemExit(f"Missing third-party workbook pair: {row['instance_id']}")

    try:
        mutant = WorkbookModel.from_xlsx(mutant_path)
        original = WorkbookModel.from_xlsx(original_path)
        source = cell_key(row["source_cell"])
        sink = cell_key(row["sink_cell"])
    except Exception as exc:
        raise SystemExit(f"Cannot parse third-party case {row['instance_id']}: {exc}") from exc
    if set(mutant.formulas) != set(original.formulas):
        raise SystemExit(f"Formula-cell set changed in {row['instance_id']}")
    differences = [
        key for key in mutant.formulas
        if normalized_formula(mutant.formulas[key]) != normalized_formula(original.formulas[key])
    ]
    if differences != [source]:
        raise SystemExit(
            f"Exactly one formula at source_cell must differ in {row['instance_id']}; "
            f"observed={differences[:5]}"
        )
    if not same_constants(mutant, original):
        raise SystemExit(f"Non-formula input values changed in {row['instance_id']}")
    if normalized_formula(original.formulas[source]) != normalized_formula(row["correct_formula"]):
        raise SystemExit(f"correct_formula does not match original workbook: {row['instance_id']}")
    if normalized_formula(mutant.formulas[source]) != normalized_formula(row["mutated_formula"]):
        raise SystemExit(f"mutated_formula does not match public workbook: {row['instance_id']}")
    if normalized_formula(row["correct_formula"]) == normalized_formula(row["mutated_formula"]):
        raise SystemExit(f"Mutation is formula-equivalent: {row['instance_id']}")
    original_values, original_errors = original.evaluate()
    mutant_values, mutant_errors = mutant.evaluate()
    if original_errors or mutant_errors:
        raise SystemExit(f"Case is not a silent calculable error: {row['instance_id']}")
    if source not in mutant_values or sink not in mutant_values:
        raise SystemExit(f"Source or sink is not calculable: {row['instance_id']}")
    graph = mutant.dependency_graph()
    path = graph.shortest_path(source, sink)
    path_length = len(path) - 1 if path else None
    if path_length is None or path_length < 1:
        raise SystemExit(f"Source has no declared downstream propagation: {row['instance_id']}")
    depth_bin = "shallow" if path_length <= 2 else "medium" if path_length <= 5 else "deep"
    if depth_bin != row["depth"]:
        raise SystemExit(
            f"Declared depth does not match dependency graph: {row['instance_id']} "
            f"{row['depth']}!={depth_bin}"
        )
    if row["topology"] == "cross_sheet" and len({cell[0] for cell in path}) < 2:
        raise SystemExit(f"Declared cross_sheet path stays on one sheet: {row['instance_id']}")
    if original_values.get(sink) == mutant_values.get(sink):
        raise SystemExit(f"Injected error does not change the declared sink: {row['instance_id']}")
    return {
        "mutant_path": mutant_path,
        "original_path": original_path,
        "mutant_sha256": sha256(mutant_path),
        "original_sha256": sha256(original_path),
        "actual_depth": path_length,
        "formula_count": len(mutant.formulas),
    }


def validate_final_design(rows, descriptors, review):
    if len(rows) != 600 or len({row["instance_id"] for row in rows}) != 600:
        raise SystemExit("Final pack requires exactly 600 unique instance_id values")
    descriptor_ids = {str(row["template_id"]) for row in descriptors}
    if len(descriptor_ids) < 30:
        raise SystemExit("At least 30 unique third-party template IDs are required")
    counts = Counter(row["error_type"] for row in rows)
    modes = Counter(row["construction_mode"] for row in rows)
    semi_by_type = Counter(row["error_type"] for row in rows if row["construction_mode"] == "semi_manual")
    gates = {
        "six_types_100_each": all(counts[error] == 100 for error in ERROR_TYPES),
        "programmatic_exactly_480": modes["programmatic"] == 480,
        "semi_manual_exactly_120": modes["semi_manual"] == 120,
        "semi_manual_each_type_at_least_20": all(semi_by_type[error] >= 20 for error in ERROR_TYPES),
        "cross_sheet_or_deep_at_least_100": sum(
            row["topology"] == "cross_sheet" or row["depth"] == "deep" for row in rows
        ) >= 100,
        "non_simple_at_least_100": sum(
            row["non_simple_neighbor_shift"].strip().lower() in TRUTHY for row in rows
        ) >= 100,
    }
    if not all(gates.values()):
        raise SystemExit("Final pack design gates failed: " + json.dumps(gates, ensure_ascii=False))
    for row in rows:
        if row["construction_mode"] != "semi_manual":
            continue
        item = review.get(row["instance_id"])
        if (
            not item
            or item.get("accepted", "").strip().lower() not in TRUTHY
            or not item.get("reviewer", "").strip()
            or not item.get("manual_change", "").strip()
        ):
            raise SystemExit(f"Semi-manual review evidence missing for {row['instance_id']}")
    return descriptor_ids, gates


def package_final(args, descriptors, public_dir, secret_dir):
    if not args.case_manifest or not args.review_ledger:
        raise SystemExit("Final mode requires --case-manifest and --review-ledger")
    rows = read_csv(args.case_manifest)
    review_rows = read_csv(args.review_ledger)
    if len(review_rows) != len({row.get("instance_id") for row in review_rows}):
        raise SystemExit("Review ledger contains duplicate instance_id values")
    review = {row["instance_id"]: row for row in review_rows}
    descriptor_ids, design_gates = validate_final_design(rows, descriptors, review)
    workbooks, originals = public_dir / "workbooks", secret_dir / "originals"
    public_rows, labels, design = [], [], []
    seen_mutant_hashes = set()
    seed_commitment = hashlib.sha256(str(args.secret_seed).encode()).hexdigest()
    for index, row in enumerate(rows, 1):
        evidence = validate_external_case(row, descriptor_ids)
        if evidence["mutant_sha256"] in seen_mutant_hashes:
            raise SystemExit(f"Duplicate public workbook bytes: {row['instance_id']}")
        seen_mutant_hashes.add(evidence["mutant_sha256"])
        public_name = f"workbooks/{row['instance_id']}.xlsx"
        original_name = f"originals/{row['instance_id']}.xlsx"
        shutil.copy2(evidence["mutant_path"], public_dir / public_name)
        shutil.copy2(evidence["original_path"], secret_dir / original_name)
        public_rows.append({"instance_id": row["instance_id"], "workbook": public_name})
        labels.append({
            "instance_id": row["instance_id"],
            "source_cell": row["source_cell"],
            "error_type": row["error_type"],
            "correct_formula": row["correct_formula"],
            "mutated_formula": row["mutated_formula"],
            "sink_cell": row["sink_cell"],
            "source_origin": row["source_origin"],
            "notes": row["notes"],
        })
        review_item = review.get(row["instance_id"], {})
        design.append({
            "instance_id": row["instance_id"],
            "template_id": row["template_id"],
            "topology": row["topology"],
            "complexity": row["complexity"],
            "declared_depth": row["depth"],
            "actual_depth": evidence["actual_depth"],
            "formula_count": evidence["formula_count"],
            "construction_mode": row["construction_mode"],
            "non_simple_neighbor_shift": row["non_simple_neighbor_shift"],
            "reviewer": review_item.get("reviewer", ""),
            "manual_change": review_item.get("manual_change", ""),
            "accepted": review_item.get("accepted", ""),
            "source_origin": row["source_origin"],
            "mutant_sha256": evidence["mutant_sha256"],
            "original_sha256": evidence["original_sha256"],
            "secret_seed_commitment": seed_commitment,
        })
        if index % 25 == 0 or index == len(rows):
            print(f"[{index}/{len(rows)}] independently prepared cases validated", flush=True)
    return public_rows, labels, design, design_gates


def package_engineering_fixture(args, descriptors, public_dir, secret_dir):
    """Small internal fixture only; its metadata explicitly forbids independent claims."""
    workbooks, originals = public_dir / "workbooks", secret_dir / "originals"
    rng = random.Random(args.secret_seed)
    public_rows, labels, design = [], [], []
    limit = args.limit or 6
    for index in range(limit):
        error_type = ERROR_TYPES[index % len(ERROR_TYPES)]
        descriptor = descriptors[index % len(descriptors)]
        instance_id = f"v6_fixture_{index + 1:04d}"
        case = Case(
            instance_id, "third_party", error_type, descriptor["topology"],
            descriptor["complexity"], DEPTHS[index % 3],
            "engineering_fixture", rng.randrange(10_000_000, 2_000_000_000),
        )
        mutant_sheets, source, correct, mutant, sink = build_case(case)
        clean_sheets, *_ = build_case(case, clean_only=True)
        mutant_path = workbooks / f"{instance_id}.xlsx"
        clean_path = originals / f"{instance_id}.xlsx"
        write_xlsx(mutant_path, mutant_sheets)
        write_xlsx(clean_path, clean_sheets)
        public_rows.append({"instance_id": instance_id, "workbook": f"workbooks/{instance_id}.xlsx"})
        labels.append({
            "instance_id": instance_id, "source_cell": source, "error_type": error_type,
            "correct_formula": correct, "mutated_formula": mutant, "sink_cell": sink,
            "source_origin": "internal_engineering_fixture_not_independent",
            "notes": "PROTOCOL TEST ONLY",
        })
        design.append({
            "instance_id": instance_id, "template_id": descriptor["template_id"],
            "topology": descriptor["topology"], "complexity": descriptor["complexity"],
            "declared_depth": DEPTHS[index % 3], "actual_depth": "",
            "formula_count": "", "construction_mode": "engineering_fixture",
            "non_simple_neighbor_shift": "", "reviewer": "", "manual_change": "",
            "accepted": "", "source_origin": "internal_fixture",
            "mutant_sha256": sha256(mutant_path), "original_sha256": sha256(clean_path),
            "secret_seed_commitment": hashlib.sha256(str(args.secret_seed).encode()).hexdigest(),
        })
    return public_rows, labels, design, {"engineering_fixture_only": True, "independent_claim_forbidden": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--secret-seed", type=int, required=True)
    parser.add_argument("--template-config", type=Path, required=True)
    parser.add_argument("--case-manifest", type=Path,
                        help="Secret 600-row manifest of externally prepared workbook pairs")
    parser.add_argument("--review-ledger", type=Path,
                        help="Secret review evidence for all 120 semi-manual cases")
    parser.add_argument("--final", action="store_true")
    parser.add_argument("--limit", type=int, help="Engineering fixture only; forbidden with --final")
    args = parser.parse_args()
    if args.final and args.limit:
        raise SystemExit("--limit is forbidden for a final independent pack")
    if args.final and (not args.case_manifest or not args.review_ledger):
        raise SystemExit("Final mode requires --case-manifest and --review-ledger")
    descriptors = json.loads(args.template_config.read_text(encoding="utf-8"))
    required_descriptor = {"template_id", "topology", "complexity", "description"}
    if not isinstance(descriptors, list) or len(descriptors) < 30:
        raise SystemExit("At least 30 secret third-party template descriptors are required")
    if any(not required_descriptor <= set(row) for row in descriptors):
        raise SystemExit(f"Each template descriptor requires: {sorted(required_descriptor)}")
    if any(row["topology"] not in TOPOLOGIES or row["complexity"] not in COMPLEXITIES for row in descriptors):
        raise SystemExit("Invalid topology or complexity in secret template configuration")

    stage = args.output / "stage"
    if stage.exists():
        raise SystemExit(f"Refusing to overwrite existing stage: {stage}")
    public_dir, secret_dir = stage / "PUBLIC", stage / "SECRET"
    (public_dir / "workbooks").mkdir(parents=True)
    (secret_dir / "originals").mkdir(parents=True)
    if args.final:
        public_rows, labels, design, gates = package_final(args, descriptors, public_dir, secret_dir)
    else:
        public_rows, labels, design, gates = package_engineering_fixture(args, descriptors, public_dir, secret_dir)

    write_csv(public_dir / "manifest.csv", public_rows, ["instance_id", "workbook"])
    write_csv(secret_dir / "labels.csv", labels, list(labels[0]))
    write_csv(secret_dir / "exceptions.csv", [], ["instance_id", "exception_type", "notes"])
    write_csv(secret_dir / "design_ledger.csv", design, list(design[0]))
    (secret_dir / "design_gates.json").write_text(
        json.dumps({"final": args.final, "gates": gates}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    secret_zip = args.output / "FormulaGuard_V6_SECRET_600.zip"
    secret_files = [(path, path.relative_to(secret_dir).as_posix()) for path in secret_dir.rglob("*") if path.is_file()]
    zip_tree(secret_zip, secret_files)
    commitments = {
        "labels.csv": sha256(secret_dir / "labels.csv"),
        "exceptions.csv": sha256(secret_dir / "exceptions.csv"),
        "SECRET.zip": sha256(secret_zip),
    }
    commitment_text = "\n".join(f"{digest}  {name}" for name, digest in commitments.items()) + "\n"
    (args.output / "secret_precommit_sha256.txt").write_text(commitment_text, encoding="utf-8")
    (public_dir / "secret_precommit_sha256.txt").write_text(commitment_text, encoding="utf-8")
    public_zip = args.output / "FormulaGuard_V6_PUBLIC_600.zip"
    public_files = [(path, path.relative_to(public_dir).as_posix()) for path in public_dir.rglob("*") if path.is_file()]
    zip_tree(public_zip, public_files)
    print(public_zip)
    print(secret_zip)
    print(args.output / "secret_precommit_sha256.txt")
    if not args.final:
        print("ENGINEERING FIXTURE ONLY: independent-result claims are forbidden.")


if __name__ == "__main__":
    main()
