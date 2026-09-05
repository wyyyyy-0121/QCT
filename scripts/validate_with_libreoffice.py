from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.benchmark import load_jsonl
from formulaguard.workbook import WorkbookModel


def find_soffice(explicit):
    candidates = [
        explicit,
        shutil.which("soffice"),
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
        Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def close_enough(left, right, tolerance=1e-7):
    try:
        return math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)
    except (TypeError, ValueError):
        return left == right


def main():
    parser = argparse.ArgumentParser(description="Cross-check the internal evaluator against LibreOffice cached values")
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--soffice", type=Path)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--required", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    soffice = find_soffice(args.soffice)
    if soffice is None:
        audit = {"status": "unavailable", "reason": "LibreOffice soffice executable not found"}
        (args.output / "cross_engine_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
        if args.required:
            raise SystemExit(audit["reason"])
        print(audit["reason"])
        return

    instances = list(load_jsonl(args.benchmark / "validation" / "validated_instances.jsonl"))
    selected = instances[: args.limit] if args.limit else instances
    paths = []
    for row in selected:
        paths.extend([args.benchmark / row["clean_workbook"], args.benchmark / row["mutant_workbook"]])
    unique_paths = list(dict.fromkeys(path.resolve() for path in paths))
    recalc_dir = args.output / "libreoffice_recalculated"
    recalc_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, source_path in enumerate(unique_paths, 1):
        target_name = f"{index:04d}_{source_path.name}"
        staged_input = recalc_dir / target_name
        shutil.copy2(source_path, staged_input)
        converted_dir = recalc_dir / f"converted_{index:04d}"
        converted_dir.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [str(soffice), "--headless", "--convert-to", "xlsx", "--outdir", str(converted_dir), str(staged_input)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        recalculated = converted_dir / target_name
        if completed.returncode != 0 or not recalculated.is_file():
            rows.append({
                "workbook": str(source_path), "formula_cells": 0, "cached_values": 0,
                "matches": 0, "mismatches": 0, "status": "conversion_failed",
                "detail": (completed.stdout + completed.stderr).strip(),
            })
            continue
        original = WorkbookModel.from_xlsx(source_path)
        recalculated_model = WorkbookModel.from_xlsx(recalculated)
        internal_values, internal_errors = original.evaluate()
        checked = matches = mismatches = 0
        for key in original.formula_cells:
            if key in internal_errors or key not in recalculated_model.cells:
                continue
            checked += 1
            if close_enough(internal_values.get(key), recalculated_model.cells.get(key)):
                matches += 1
            else:
                mismatches += 1
        rows.append({
            "workbook": str(source_path), "formula_cells": len(original.formulas), "cached_values": checked,
            "matches": matches, "mismatches": mismatches,
            "status": "ok" if mismatches == 0 and checked else "mismatch_or_no_cache", "detail": "",
        })
        print(f"[{index}/{len(unique_paths)}] {source_path.name}", flush=True)

    with (args.output / "cross_engine_results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["workbook", "status"])
        writer.writeheader()
        writer.writerows(rows)
    audit = {
        "status": "completed",
        "soffice": str(soffice),
        "workbooks": len(rows),
        "workbooks_with_mismatch_or_no_cache": sum(row["status"] != "ok" for row in rows),
        "checked_formula_values": sum(int(row["cached_values"]) for row in rows),
        "matching_formula_values": sum(int(row["matches"]) for row in rows),
        "mismatching_formula_values": sum(int(row["mismatches"]) for row in rows),
    }
    (args.output / "cross_engine_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
