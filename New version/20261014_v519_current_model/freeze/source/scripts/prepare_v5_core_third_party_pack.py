"""Validate and package 600 third-party V5-Core cases without running a model."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.a1 import parse_address
from formulaguard.formula import normalized_formula, translate_formula
from formulaguard.workbook import WorkbookModel
from scripts.build_v5_core_dataset import ERROR_TYPES, sha256


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def csv_bytes(rows: list[dict], fields: list[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader(); writer.writerows({key: row.get(key, "") for key in fields} for row in rows)
    return stream.getvalue().encode("utf-8-sig")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_input_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if root.resolve() not in path.parents or not path.is_file():
        raise SystemExit(f"Missing or escaping third-party file: {relative}")
    return path


def values_differ(left: object, right: object) -> bool:
    try:
        return not math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9)
    except (TypeError, ValueError):
        return left != right


def cell_key(label: str) -> tuple[str, str]:
    if "!" not in label:
        raise SystemExit(f"Invalid sheet-qualified cell: {label}")
    return tuple(label.rsplit("!", 1))  # type: ignore[return-value]


def simple_neighbor_can_reproduce(
    model: WorkbookModel,
    source: tuple[str, str],
    correct_formula: str,
) -> bool:
    anchor = parse_address(source[1])
    for peer, formula in model.formulas.items():
        if peer == source or peer[0] != source[0]:
            continue
        address = parse_address(peer[1])
        if abs(address.row - anchor.row) + abs(address.col - anchor.col) != 1:
            continue
        try:
            proposal = translate_formula(formula, peer[1], source[1])
        except Exception:  # noqa: BLE001, S112 intentional compatibility or fallback boundary; preserve runtime behavior
            continue
        if normalized_formula(proposal) == normalized_formula(correct_formula):
            return True
    return False


def validate_pair(root: Path, row: dict, label: dict) -> tuple[Path, Path, bool]:
    instance_id = row["instance_id"]
    if not re.fullmatch(r"[A-Za-z0-9._-]+", instance_id):
        raise SystemExit(f"Unsafe third-party instance id: {instance_id}")
    mutant = safe_input_path(root, row["mutant_workbook"])
    original_relative = label.get("original_workbook") or f"originals/{instance_id}.xlsx"
    original = safe_input_path(root, original_relative)
    mutant_model = WorkbookModel.from_xlsx(mutant)
    original_model = WorkbookModel.from_xlsx(original)
    mutant_values, mutant_errors = mutant_model.evaluate()
    original_values, original_errors = original_model.evaluate()
    if mutant_errors or original_errors:
        raise SystemExit(f"Explicit calculation error in third-party case: {instance_id}")
    source = cell_key(label["source_cell"])
    sink = cell_key(label["sink_cell"])
    if set(mutant_model.formulas) != set(original_model.formulas) or source not in mutant_model.formulas:
        raise SystemExit(f"Formula coordinate mismatch in third-party case: {instance_id}")
    changed = {
        cell for cell in mutant_model.formulas
        if normalized_formula(mutant_model.formulas[cell])
        != normalized_formula(original_model.formulas[cell])
    }
    if changed != {source}:
        raise SystemExit(f"Third-party case must inject exactly one source formula: {instance_id}")
    if normalized_formula(original_model.formulas[source]) != normalized_formula(label["correct_formula"]):
        raise SystemExit(f"Correct formula does not match original: {instance_id}")
    if normalized_formula(mutant_model.formulas[source]) != normalized_formula(label["mutated_formula"]):
        raise SystemExit(f"Mutated formula does not match workbook: {instance_id}")
    descendants = mutant_model.dependency_graph().descendants(source) & set(mutant_model.formula_cells)
    if sink not in descendants or not values_differ(original_values.get(sink), mutant_values.get(sink)):
        raise SystemExit(f"Third-party mutation does not propagate to its sink: {instance_id}")
    depth = mutant_model.dependency_graph().shortest_path_length(source, sink)
    if depth != int(label["actual_depth"]):
        raise SystemExit(f"Third-party propagation depth mismatch: {instance_id}")
    try:
        float(mutant_values[source])
    except (TypeError, ValueError, KeyError) as exc:
        raise SystemExit(f"Third-party source is not a silent numeric error: {instance_id}") from exc
    non_neighbor_repair = not simple_neighbor_can_reproduce(
        original_model, source, label["correct_formula"],
    )
    return mutant, original, non_neighbor_repair


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="Third-party generated V5-Core dataset root")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    input_root = args.input.resolve()
    try:
        input_root.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise SystemExit("Third-party evidence must be prepared outside the project repository")
    provenance_path = input_root / "third_party_provenance.json"
    if not provenance_path.exists():
        raise SystemExit("Missing third_party_provenance.json from the independent preparer")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    required_declarations = (
        "prepared_by_independent_person",
        "project_localizer_results_not_seen",
        "secret_seed_withheld",
        "templates_unseen_by_project",
        "all_valid_cases_retained",
    )
    if any(provenance.get(field) is not True for field in required_declarations):
        raise SystemExit("Independent provenance declarations are incomplete or false")
    if not str(provenance.get("preparer_role", "")).strip():
        raise SystemExit("Independent provenance must state the preparer's role")
    instances = read_jsonl(input_root / "instances.jsonl")
    labels = read_jsonl(input_root / "evaluation_labels.jsonl")
    by_id = {row["instance_id"]: row for row in labels}
    instance_ids = [row["instance_id"] for row in instances]
    label_ids = [row["instance_id"] for row in labels]
    if (
        len(instances) != 600 or len(labels) != 600
        or len(set(instance_ids)) != 600 or len(set(label_ids)) != 600
        or set(by_id) != set(instance_ids)
    ):
        raise SystemExit("Third-party pack must contain exactly 600 matched events")
    counts = Counter(row["mutation_type"] for row in labels)
    if set(counts) != set(ERROR_TYPES) or set(counts.values()) != {100}:
        raise SystemExit(f"Six error types must have 100 cases each: {dict(counts)}")
    ledger = []
    resolved_pairs: dict[str, tuple[Path, Path, bool]] = {}
    for row in instances:
        label = by_id[row["instance_id"]]
        resolved_pairs[row["instance_id"]] = validate_pair(input_root, row, label)
        ledger.append({
            "instance_id": row["instance_id"],
            "template_family": row["template_family"],
            "topology": row["topology_id"],
            "regime": row["regime"],
            "manual_or_semi_manual": row.get("ambiguity") in {
                "manual", "semi_manual", "semi_manual_exception",
            },
            "cross_sheet_or_long_chain": row["topology_id"] == "cross_sheet" or int(label.get("actual_depth") or 0) >= 4,
            "non_neighbor_repair": resolved_pairs[row["instance_id"]][2],
            "contains_legitimate_exception": (
                row.get("regime") == "mixed_exception"
                or row.get("ambiguity") in {"legitimate_summary", "legitimate_exception", "semi_manual_exception"}
            ),
        })
    if sum(row["manual_or_semi_manual"] for row in ledger) < 120:
        raise SystemExit("At least 120 cases must be manual or semi-manual")
    manual_by_type = Counter(
        by_id[row["instance_id"]]["mutation_type"]
        for row in ledger if row["manual_or_semi_manual"]
    )
    if any(manual_by_type[error_type] < 20 for error_type in ERROR_TYPES):
        raise SystemExit(f"Each error type needs at least 20 manual/semi-manual cases: {dict(manual_by_type)}")
    if sum(row["cross_sheet_or_long_chain"] for row in ledger) < 100:
        raise SystemExit("At least 100 cases must be cross-sheet or long-chain")
    if sum(row["non_neighbor_repair"] for row in ledger) < 100:
        raise SystemExit("At least 100 cases must not be simple neighbor translations")
    if sum(row["contains_legitimate_exception"] for row in ledger) < 60:
        raise SystemExit("At least 60 cases must contain a legitimate special formula or complex summary")

    labels_csv = csv_bytes(labels, [
        "instance_id", "source_cell", "mutation_type", "correct_formula",
        "mutated_formula", "sink_cell", "actual_depth",
    ])
    exceptions_csv = csv_bytes([], ["instance_id", "reason", "notes"])
    ledger_csv = csv_bytes(ledger, list(ledger[0]))
    args.output.mkdir(parents=True, exist_ok=True)
    secret_zip = args.output / "FormulaGuard_V5_SECRET_600.zip"
    with zipfile.ZipFile(secret_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("labels.csv", labels_csv)
        archive.writestr("exceptions.csv", exceptions_csv)
        archive.writestr("design_ledger.csv", ledger_csv)
        for row in instances:
            original = resolved_pairs[row["instance_id"]][1]
            archive.write(original, f"originals/{row['instance_id']}.xlsx")
    precommit = {
        "secret_zip_sha256": sha256(secret_zip),
        "labels_csv_sha256": digest_bytes(labels_csv),
        "exceptions_csv_sha256": digest_bytes(exceptions_csv),
        "design_ledger_csv_sha256": digest_bytes(ledger_csv),
        "provenance_sha256": sha256(provenance_path),
    }
    precommit_text = "".join(f"{key}={value}\n" for key, value in precommit.items())
    public_zip = args.output / "FormulaGuard_V5_PUBLIC_600.zip"
    manifest_rows = [
        {"instance_id": row["instance_id"], "workbook": f"workbooks/{row['instance_id']}.xlsx"}
        for row in instances
    ]
    manifest_csv = csv_bytes(manifest_rows, ["instance_id", "workbook"])
    with zipfile.ZipFile(public_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.csv", manifest_csv)
        archive.writestr("secret_precommit_sha256.txt", precommit_text.encode("utf-8"))
        for row in instances:
            mutant = resolved_pairs[row["instance_id"]][0]
            archive.write(mutant, f"workbooks/{row['instance_id']}.xlsx")
    receipt = {
        "protocol": "v5_core_third_party_precommit_v1",
        "public_zip": str(public_zip.resolve()),
        "public_zip_sha256": sha256(public_zip),
        **precommit,
        "cases": 600,
        "model_was_run": False,
        "independent_provenance_verified": True,
        "single_injection_and_propagation_audit_passed": True,
    }
    (args.output / "third_party_precommit.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(public_zip); print(secret_zip); print(args.output / "third_party_precommit.json")


if __name__ == "__main__":
    main()
