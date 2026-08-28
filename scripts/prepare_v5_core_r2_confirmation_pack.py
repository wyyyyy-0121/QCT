"""Validate and package third-party R2 confirmation data without running a localizer."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import io
import json
import math
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.formula import normalized_formula
from formulaguard.workbook import WorkbookModel
from scripts.audit_v5_core_dataset import graph_formula_signature, translation_invariant_formula_pair

ERROR_STRATA = {
    "traditional": 420, "withheld_mutation": 90,
    "candidate_absent": 60, "unsupported_ambiguous": 30,
}
TRADITIONAL_TYPES = {
    "range_boundary", "operator", "function_replacement",
    "copy_offset", "absolute_reference", "reference_shift",
}
CLEAN_STRUCTURES = {"regular", "legal_exception", "periodic_2d", "cross_sheet"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def csv_bytes(rows: list[dict[str, object]], fields: list[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows({field: row.get(field, "") for field in fields} for row in rows)
    return stream.getvalue().encode("utf-8-sig")


def safe_file(root: Path, relative: str) -> Path:
    if not relative or "\\" in relative:
        raise ValueError(f"Missing or non-portable path: {relative!r}")
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Path escapes third-party root: {relative}") from exc
    if not path.is_file():
        raise ValueError(f"Missing third-party file: {relative}")
    return path


def canonical_formula(value: str) -> str:
    try:
        return normalized_formula(value)
    except Exception:
        return "".join(str(value).split()).upper()


def cell_key(value: str) -> tuple[str, str]:
    if "!" not in value:
        raise ValueError(f"Cell must be sheet-qualified: {value}")
    sheet, address = value.rsplit("!", 1)
    return sheet.strip("'"), address.replace("$", "").upper()


def source_keys(value: str) -> set[tuple[str, str]]:
    return {cell_key(item.strip()) for item in value.split(";") if item.strip()}


def values_differ(left: object, right: object) -> bool:
    try:
        return not math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9)
    except (TypeError, ValueError):
        return left != right


def validate_case(payload: tuple[str, dict[str, str], dict[str, str], dict[str, str]]) -> dict:
    root_text, manifest, label, ledger = payload
    root = Path(root_text)
    instance_id = label["instance_id"]
    if not re.fullmatch(r"[A-Za-z0-9._-]+", instance_id):
        raise ValueError(f"Unsafe instance_id: {instance_id}")
    workbook = safe_file(root, manifest["workbook"])
    mutant = WorkbookModel.from_xlsx(workbook)
    result = {
        "instance_id": instance_id, "workbook": str(workbook),
        "workbook_sha256": sha256(workbook), "formula_count": len(mutant.formulas),
        "case_kind": label["case_kind"], "challenge_stratum": label.get("challenge_stratum", ""),
        "single_injection_verified": False, "silent_numeric_verified": False,
        "downstream_propagation_verified": False, "translation_pair": None,
        "graph_formula_signature": None, "original_workbook": "",
    }
    if not mutant.formulas:
        raise ValueError(f"Workbook contains no formulas: {instance_id}")
    if label["case_kind"] == "clean":
        _, errors = mutant.evaluate()
        if errors:
            raise ValueError(f"Clean control has explicit calculation errors: {instance_id}")
        return result

    sources = source_keys(label.get("source_cells", ""))
    if not sources or not sources <= set(mutant.formulas):
        raise ValueError(f"Error source is missing or not a formula: {instance_id}")
    original_path = safe_file(root, ledger.get("original_workbook", ""))
    original = WorkbookModel.from_xlsx(original_path)
    result["original_workbook"] = str(original_path)
    if set(mutant.formulas) != set(original.formulas):
        raise ValueError(f"Original/mutant formula coordinates differ: {instance_id}")
    changed = {
        cell for cell in mutant.formulas
        if canonical_formula(mutant.formulas[cell]) != canonical_formula(original.formulas[cell])
    }
    if changed != sources:
        raise ValueError(
            f"Changed formulas differ from source_cells: {instance_id}; "
            f"changed={len(changed)}, declared={len(sources)}"
        )
    result["single_injection_verified"] = len(changed) == 1
    unsupported_allowed = label["challenge_stratum"] == "unsupported_ambiguous"
    if not unsupported_allowed and len(changed) != 1:
        raise ValueError(f"Non-ambiguous event must inject exactly one formula: {instance_id}")
    if len(changed) == 1:
        source = next(iter(changed))
        if label.get("correct_formula") and (
            canonical_formula(original.formulas[source]) != canonical_formula(label["correct_formula"])
        ):
            raise ValueError(f"Correct formula disagrees with original: {instance_id}")
        if label.get("mutated_formula") and (
            canonical_formula(mutant.formulas[source]) != canonical_formula(label["mutated_formula"])
        ):
            raise ValueError(f"Mutated formula disagrees with public workbook: {instance_id}")
        try:
            result["translation_pair"] = translation_invariant_formula_pair(
                original.formulas[source], mutant.formulas[source], f"{source[0]}!{source[1]}",
            )
        except Exception:
            pass

    mutant_values, mutant_errors = mutant.evaluate()
    original_values, original_errors = original.evaluate()
    if (mutant_errors or original_errors) and not unsupported_allowed:
        raise ValueError(f"Error event has explicit calculation errors: {instance_id}")
    if not mutant_errors and all(source in mutant_values for source in sources):
        try:
            for source in sources:
                float(mutant_values[source])
            result["silent_numeric_verified"] = True
        except (TypeError, ValueError):
            pass
    if not result["silent_numeric_verified"] and not unsupported_allowed:
        raise ValueError(f"Source is not a silent numeric error: {instance_id}")
    graph = mutant.dependency_graph()
    try:
        source_signatures = sorted(
            graph_formula_signature(mutant, f"{sheet}!{address}")
            for sheet, address in sources
        )
        result["graph_formula_signature"] = hashlib.sha256(
            json.dumps(source_signatures, sort_keys=True).encode("utf-8")
        ).hexdigest()
    except Exception:
        pass
    descendants = set().union(*(graph.descendants(source) for source in sources))
    sinks = source_keys(label.get("sink_cells", "")) if label.get("sink_cells") else {
        cell for cell in descendants if values_differ(original_values.get(cell), mutant_values.get(cell))
    }
    result["downstream_propagation_verified"] = bool(
        sinks and sinks <= descendants
        and any(values_differ(original_values.get(cell), mutant_values.get(cell)) for cell in sinks)
    )
    if not result["downstream_propagation_verified"] and not unsupported_allowed:
        raise ValueError(f"Mutation has no verified downstream effect: {instance_id}")
    return result


def development_pairs() -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for root in (
        ROOT / "data/v5_core_development", ROOT / "data/v5_core_redteam",
        ROOT / "data/v5_core_validation",
    ):
        path = root / "evaluation_labels.jsonl"
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            try:
                pairs.add(translation_invariant_formula_pair(
                    row["correct_formula"], row["mutated_formula"], row["source_cell"],
                ))
            except Exception:
                continue
    return pairs


def graph_signature_task(payload: tuple[str, str]) -> str | None:
    workbook_text, source_cell = payload
    try:
        model = WorkbookModel.from_xlsx(Path(workbook_text))
        signature = graph_formula_signature(model, source_cell)
        return hashlib.sha256(json.dumps([signature]).encode("utf-8")).hexdigest()
    except Exception:
        return None


def development_graph_signatures(workers: int) -> set[str]:
    payloads: list[tuple[str, str]] = []
    for root in (
        ROOT / "data/v5_core_development", ROOT / "data/v5_core_redteam",
        ROOT / "data/v5_core_validation",
    ):
        path = root / "evaluation_labels.jsonl"
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            workbook = root / "mutants" / f"{row['instance_id']}.xlsx"
            if workbook.is_file():
                payloads.append((str(workbook), row["source_cell"]))
    signatures: set[str] = set()
    worker_count = min(max(1, workers), max(1, len(payloads)))
    with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count) as executor:
        for value in executor.map(graph_signature_task, payloads, chunksize=8):
            if value:
                signatures.add(value)
    return signatures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()
    input_root, output_root = args.input.resolve(), args.output.resolve()
    if not input_root.is_dir():
        raise SystemExit(f"Third-party input directory does not exist: {input_root}")
    for path, label in ((input_root, "input"), (output_root, "output")):
        try:
            path.relative_to(ROOT.resolve())
        except ValueError:
            pass
        else:
            raise SystemExit(f"Third-party {label} must remain outside the project repository")
    for child, parent in ((output_root, input_root), (input_root, output_root)):
        try:
            child.relative_to(parent)
        except ValueError:
            continue
        raise SystemExit("Third-party input and output directories must not overlap")
    if output_root.exists() and any(output_root.iterdir()):
        raise SystemExit("Third-party output directory must be empty before packaging")
    declaration_path = input_root / "third_party_declaration.json"
    if not declaration_path.is_file():
        raise SystemExit("Missing third_party_declaration.json")
    declaration = json.loads(declaration_path.read_text(encoding="utf-8"))
    required_declarations = (
        "prepared_by_independent_person", "project_model_results_not_seen",
        "templates_unseen_by_project", "all_valid_cases_retained",
        "secret_labels_withheld", "development_overlap_checked",
    )
    if any(declaration.get(key) is not True for key in required_declarations):
        raise SystemExit("Third-party independence declarations are incomplete or false")
    if not str(declaration.get("preparer_role", "")).strip():
        raise SystemExit("Third-party declaration must state preparer_role")

    manifest = read_csv(input_root / "manifest.csv")
    labels = read_csv(input_root / "labels.csv")
    ledger = read_csv(input_root / "design_ledger.csv")
    provenance = read_csv(input_root / "provenance.csv")
    exceptions = read_csv(input_root / "exceptions.csv")
    tables = {"manifest": manifest, "labels": labels, "ledger": ledger, "provenance": provenance}
    identifiers = {
        name: [row.get("instance_id", "") for row in rows] for name, rows in tables.items()
    }
    expected_ids = set(identifiers["manifest"])
    if len(manifest) != 780 or len(expected_ids) != 780 or "" in expected_ids:
        raise SystemExit("manifest.csv must contain 780 unique non-empty identifiers")
    for name, values in identifiers.items():
        if len(values) != 780 or len(set(values)) != 780 or set(values) != expected_ids:
            raise SystemExit(f"{name} must cover the same 780 identifiers exactly once")
    label_by_id = {row["instance_id"]: row for row in labels}
    ledger_by_id = {row["instance_id"]: row for row in ledger}
    provenance_by_id = {row["instance_id"]: row for row in provenance}
    kind_counts = Counter(row.get("case_kind") for row in labels)
    if kind_counts != Counter({"error": 600, "clean": 180}):
        raise SystemExit(f"Expected 600 error and 180 clean cases: {dict(kind_counts)}")
    errors = [row for row in labels if row["case_kind"] == "error"]
    clean = [row for row in labels if row["case_kind"] == "clean"]
    if Counter(row.get("challenge_stratum") for row in errors) != Counter(ERROR_STRATA):
        raise SystemExit("Error challenge-stratum counts differ from protocol")
    traditional_counts = Counter(
        row.get("error_type") for row in errors if row["challenge_stratum"] == "traditional"
    )
    if set(traditional_counts) != TRADITIONAL_TYPES or set(traditional_counts.values()) != {70}:
        raise SystemExit(f"Traditional errors must be six groups of 70: {dict(traditional_counts)}")
    clean_counts = Counter(row.get("clean_structure") for row in clean)
    if set(clean_counts) != CLEAN_STRUCTURES or set(clean_counts.values()) != {45}:
        raise SystemExit(f"Clean controls must be four groups of 45: {dict(clean_counts)}")
    if any(row.get("source_cells", "").strip() for row in clean):
        raise SystemExit("Clean labels must not contain source cells")
    exception_ids = {row.get("instance_id") for row in exceptions if row.get("instance_id")}
    required_exceptions = {
        row["instance_id"] for row in errors if row["challenge_stratum"] == "unsupported_ambiguous"
    }
    if not required_exceptions <= exception_ids:
        raise SystemExit("Every unsupported/ambiguous event needs an exceptions.csv record")

    payloads = [
        (str(input_root), row, label_by_id[row["instance_id"]], ledger_by_id[row["instance_id"]])
        for row in manifest
    ]
    workers = min(max(1, args.workers), len(payloads))
    audits: list[dict] = []
    print(f"R2 third-party pack audit: {workers} workers; {len(payloads)} cases.", flush=True)
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(validate_case, payload) for payload in payloads]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            audits.append(future.result())
            if index % 25 == 0 or index == len(futures):
                print(f"[{index}/{len(futures)}] validated", flush=True)
    audits.sort(key=lambda row: row["instance_id"])
    if len({row["workbook_sha256"] for row in audits}) != 780:
        raise SystemExit("Public confirmation workbooks must be byte-distinct")
    confirmation_pairs = {
        tuple(row["translation_pair"]) for row in audits if row.get("translation_pair")
    }
    overlap = development_pairs() & confirmation_pairs
    if overlap:
        raise SystemExit(f"Confirmation formula transformations overlap development: {len(overlap)}")
    supported_errors = [
        row for row in audits if row["case_kind"] == "error"
        and row["challenge_stratum"] != "unsupported_ambiguous"
    ]
    if any(not row.get("graph_formula_signature") for row in supported_errors):
        raise SystemExit("A supported confirmation error lacks a graph/formula signature")
    confirmation_graphs = {
        row["graph_formula_signature"] for row in supported_errors
        if row.get("graph_formula_signature")
    }
    graph_overlap = development_graph_signatures(workers) & confirmation_graphs
    if graph_overlap:
        raise SystemExit(f"Confirmation graph/formula signatures overlap development: {len(graph_overlap)}")
    real_count = sum(
        ledger_by_id[identifier].get("real_structure", "").lower() in {"1", "true", "yes"}
        for identifier in expected_ids
    )
    manual_error_count = sum(
        ledger_by_id[row["instance_id"]].get("construction_mode", "").lower()
        in {"manual", "semi_manual", "semimanual"} for row in errors
    )
    if real_count < 150 or manual_error_count < 120:
        raise SystemExit(
            f"Authenticity floors failed: real={real_count}, manual_error={manual_error_count}"
        )
    if any(
        not provenance_by_id[identifier].get("license_or_permission", "").strip()
        or provenance_by_id[identifier].get("anonymized", "").lower() not in {"1", "true", "yes"}
        for identifier in expected_ids
    ):
        raise SystemExit("Every case needs permission provenance and anonymization confirmation")

    output_root.mkdir(parents=True, exist_ok=True)
    labels_bytes = csv_bytes(labels, list(labels[0]))
    ledger_bytes = csv_bytes(ledger, list(ledger[0]))
    provenance_bytes = csv_bytes(provenance, list(provenance[0]))
    exception_fields = list(exceptions[0]) if exceptions else ["instance_id", "reason", "notes"]
    exceptions_bytes = csv_bytes(exceptions, exception_fields)
    secret_zip = output_root / "FormulaGuard_R2_SECRET_780.zip"
    with zipfile.ZipFile(secret_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("labels.csv", labels_bytes)
        archive.writestr("exceptions.csv", exceptions_bytes)
        archive.writestr("design_ledger.csv", ledger_bytes)
        archive.writestr("provenance.csv", provenance_bytes)
        archive.write(declaration_path, "third_party_declaration.json")
        for row in audits:
            if row["case_kind"] == "error":
                archive.write(Path(row["original_workbook"]), f"originals/{row['instance_id']}.xlsx")
    secret_hashes = {
        "secret_zip_sha256": sha256(secret_zip),
        "labels_csv_sha256": digest_bytes(labels_bytes),
        "exceptions_csv_sha256": digest_bytes(exceptions_bytes),
        "design_ledger_csv_sha256": digest_bytes(ledger_bytes),
        "provenance_csv_sha256": digest_bytes(provenance_bytes),
        "declaration_json_sha256": sha256(declaration_path),
    }
    commitment_text = "".join(f"{name}={value}\n" for name, value in secret_hashes.items())
    manifest_rows = [
        {"instance_id": row["instance_id"], "workbook": f"workbooks/{row['instance_id']}.xlsx"}
        for row in sorted(manifest, key=lambda item: item["instance_id"])
    ]
    manifest_bytes = csv_bytes(manifest_rows, ["instance_id", "workbook"])
    audit_by_id = {row["instance_id"]: row for row in audits}
    public_zip = output_root / "FormulaGuard_R2_PUBLIC_780.zip"
    with zipfile.ZipFile(public_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.csv", manifest_bytes)
        archive.writestr("secret_precommit_sha256.txt", commitment_text.encode("utf-8"))
        for row in manifest_rows:
            archive.write(Path(audit_by_id[row["instance_id"]]["workbook"]), row["workbook"])
    precommit = {
        "protocol": "v5_core_r2_third_party_precommit_v1",
        "total_cases": 780, "error_cases": 600, "clean_cases": 180,
        "model_was_run": False, "development_overlap_audit_passed": True,
        "independent_preparer": True,
        "single_injection_and_propagation_audit_passed": True,
        "real_structure_cases": real_count, "manual_error_cases": manual_error_count,
        "public_zip_sha256": sha256(public_zip), **secret_hashes,
    }
    precommit_path = output_root / "third_party_precommit.json"
    precommit_path.write_text(json.dumps(precommit, ensure_ascii=False, indent=2), encoding="utf-8")
    audit_path = output_root / "third_party_data_audit.json"
    audit_path.write_text(json.dumps({
        "protocol": "v5_core_r2_third_party_data_audit_v1", "cases": 780,
        "formula_transformation_overlap": 0, "graph_formula_signature_overlap": 0,
        "real_structure_cases": real_count,
        "manual_error_cases": manual_error_count, "hard_gate_passed": True,
        "model_executed": False,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(public_zip)
    print(secret_zip)
    print(precommit_path)
    print(audit_path)


if __name__ == "__main__":
    main()
