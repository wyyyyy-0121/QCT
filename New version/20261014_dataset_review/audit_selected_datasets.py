"""Audit downloaded packages and public annotations; do not run model predictions."""

import base64
import collections
import csv
import hashlib
import json
import posixpath
import statistics
import zipfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
ARCHIVES = BASE / "archives"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def properties(raw):
    values = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", "!")) and "=" in stripped:
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def main():
    packages = []
    inventory = []
    for name in ("EUSES_modified.zip", "Info1.zip", "Integer.zip", "Payroll_Gradebook.zip"):
        path = ARCHIVES / name
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ValueError("CRC verification failed: " + name)
            files = [item for item in archive.infolist() if not item.is_dir()]
            names = {item.filename for item in files}
            by_case = {item.filename.casefold(): item.filename for item in files}
            worksheets = [item for item in files if Path(item.filename).suffix.casefold() in (".xls", ".xlsx")]
            configurations = [item for item in files if item.filename.endswith(".properties")]
            fault_counts, fault_types = [], collections.Counter()
            annotation_keys = collections.Counter()
            missing = []
            oracle_flags = 0
            for item in configurations:
                values = properties(archive.read(item))
                annotation_keys.update(values.keys())
                reference = values.get("EXCEL_SHEET", "").replace("\\", "/")
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(item.filename), reference))
                workbook = resolved if resolved in names else by_case.get(resolved.casefold())
                if workbook is None:
                    missing.append(item.filename)
                faulty = [v for k, v in values.items() if k.startswith("FAULTY_CELLS_")]
                fault_counts.append(len(faulty))
                fault_types.update(v or "blank" for k, v in values.items() if k.startswith("FAULT_TYPE_"))
                flags = sum("ORACLE_MISTAKE" in k and v.upper() in ("T", "TRUE", "1") for k, v in values.items())
                oracle_flags += flags
                inventory.append({
                    "package": name, "annotation_path": item.filename,
                    "workbook_reference": values.get("EXCEL_SHEET", ""),
                    "resolved_workbook": workbook or "", "workbook_found": workbook is not None,
                    "faulty_cell_count": len(faulty), "faulty_cells": ";".join(faulty),
                    "correct_output_labels": sum(k.startswith("CORRECT_OUTPUT_") for k in values),
                    "incorrect_output_labels": sum(k.startswith("INCORRECT_OUTPUT_") for k in values),
                    "expected_output_values": sum("OUTCELL_EXPECTED_VALUE" in k for k in values),
                    "oracle_mistake_true_flags": flags,
                })
            summary = {
                "package": name, "path": path.relative_to(BASE).as_posix(),
                "sha256": sha(path), "compressed_bytes": path.stat().st_size,
                "uncompressed_bytes": sum(item.file_size for item in files), "crc_verified": True,
                "files": len(files), "file_extensions": dict(collections.Counter(Path(i.filename).suffix.lower() for i in files)),
                "workbook_files": len(worksheets), "annotation_files": len(configurations),
                "resolved_workbook_references": len(configurations) - len(missing),
                "missing_workbook_references": missing,
                "faulty_cell_labels": sum(fault_counts),
                "faults_per_annotation": {"min": min(fault_counts), "median": statistics.median(fault_counts), "max": max(fault_counts)},
                "fault_type_counts": dict(fault_types), "oracle_mistake_true_flags": oracle_flags,
                "keys_with_formula_in_name": [key for key in annotation_keys if "FORMULA" in key],
                "truth_note": "Expected output values do not supply correct source formulas; mapping to a clean base workbook still requires verification.",
                "readme_paths": [i.filename for i in files if Path(i.filename).name.lower().startswith("readme")],
                "license_paths": [i.filename for i in files if any(term in Path(i.filename).name.lower() for term in ("license", "licence", "copyright"))],
            }
            packages.append(summary)
            for readme in summary["readme_paths"]:
                target = BASE / "sources" / (Path(name).stem + "_package_readme.txt")
                target.write_bytes(archive.read(readme))
    multi = BASE / "sources/modified_euses_multi_fault.source"
    with zipfile.ZipFile(multi) as archive:
        if archive.testzip() is not None:
            raise ValueError("Multi-fault package CRC verification failed")
        files = [i for i in archive.infolist() if not i.is_dir()]
        packages.append({
            "package": "EUSES-double-triple-faults.zip", "path": multi.relative_to(BASE).as_posix(),
            "sha256": sha(multi), "compressed_bytes": multi.stat().st_size,
            "crc_verified": True, "files": len(files),
            "uncompressed_bytes": sum(i.file_size for i in files),
            "file_extensions": dict(collections.Counter(Path(i.filename).suffix.lower() for i in files)),
        })
    formula_packages = []
    decoded_dir = BASE / "formula_repair_json"
    decoded_dir.mkdir(exist_ok=True)
    for filename, output in (("FoRepBenchmarks_blob.json", "FoRepBenchmarks.json"), ("FoRepBench_seed_blob.json", "seed_data.json")):
        blob_path = ARCHIVES / filename
        blob = json.loads(blob_path.read_text())
        decoded = base64.b64decode(blob["content"])
        assert len(decoded) == blob["size"]
        blob_hash = hashlib.sha1(b"blob " + str(len(decoded)).encode() + b"\0" + decoded).hexdigest()
        assert blob_hash == blob["sha"]
        destination = decoded_dir / output
        destination.write_bytes(decoded)
        data = json.loads(decoded)
        formula_packages.append({
            "package": output, "path": destination.relative_to(BASE).as_posix(),
            "rows": len(data), "git_blob_sha_verified": blob_hash, "sha256": sha(destination),
            "correct_formulas": sum(isinstance(r.get("correct_formula"), str) for r in data),
            "faulty_formulas": sum(isinstance(r.get("faulty_formula"), str) for r in data),
            "nonempty_runtime_error_annotations": sum(bool(r.get("runtime_errors")) for r in data),
            "runtime_error_labels": dict(collections.Counter(str(error) for r in data for error in r.get("runtime_errors", []))),
            "specified_faulty_formula_locations": sum(bool(r.get("faulty_formula_cell_location")) for r in data),
            "validity_values": dict(collections.Counter(str(r.get("is_valid")) for r in data)),
            "keys": sorted({key for r in data for key in r}),
            "task_note": "The task supplies an erroneous formula and context; runtime-error annotations are present. It is not a workbook-wide silent-source localization truth set.",
        })
    write_json(BASE / "ARCHIVE_AUDIT.json", {
        "audited_at": datetime.now(timezone.utc).isoformat(), "packages": packages,
        "formula_repair_packages": formula_packages,
        "scope": "Archive integrity and public annotation metadata only; no model run or workbook formula conversion.",
    })
    with (BASE / "ANNOTATION_INVENTORY.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(inventory[0]))
        writer.writeheader()
        writer.writerows(inventory)
    print(json.dumps({
        "packages": [{key: p.get(key) for key in ("package", "annotation_files", "workbook_files", "resolved_workbook_references", "faulty_cell_labels")} for p in packages],
        "formula_packages": [{key: p[key] for key in ("package", "rows", "nonempty_runtime_error_annotations")} for p in formula_packages],
        "annotation_inventory_rows": len(inventory),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
