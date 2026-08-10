from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.localize import localize
from formulaguard.workbook import WorkbookModel


def main():
    parser = argparse.ArgumentParser(description="Measure parsing and localization runtime on scaling workbooks")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--methods", default="pattern,graph,formulaguard")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--candidate-limit", type=int, default=5)
    args = parser.parse_args()
    methods = [item.strip() for item in args.methods.split(",") if item.strip()]
    manifest = json.loads((args.input / "scaling_manifest.json").read_text(encoding="utf-8"))
    if not manifest.get("records"):
        raise SystemExit(f"No scaling records found in: {args.input / 'scaling_manifest.json'}")
    rows = []
    for record in manifest["records"]:
        workbook_path = args.input / record["workbook"]
        for repeat in range(args.repeats):
            started = time.perf_counter()
            model = WorkbookModel.from_xlsx(workbook_path)
            parse_seconds = time.perf_counter() - started
            for method in methods:
                method_started = time.perf_counter()
                results = localize(model, method, candidate_limit=args.candidate_limit)
                rows.append({
                    "target_formula_count": record["target_formula_count"],
                    "actual_formula_count": len(model.formulas),
                    "repeat": repeat + 1,
                    "method": method,
                    "parse_seconds": parse_seconds,
                    "localization_seconds": time.perf_counter() - method_started,
                    "returned_cells": len(results),
                })
            print(f"size={record['target_formula_count']} repeat={repeat + 1}", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary_path = args.output.with_name(args.output.stem + "_summary.csv")
    with summary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["target_formula_count", "method", "parse_median", "localization_median", "localization_p95"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for size in sorted({row["target_formula_count"] for row in rows}):
            for method in methods:
                group = [row for row in rows if row["target_formula_count"] == size and row["method"] == method]
                timings = sorted(row["localization_seconds"] for row in group)
                p95 = timings[max(0, int(0.95 * len(timings) + 0.999999) - 1)]
                writer.writerow({
                    "target_formula_count": size,
                    "method": method,
                    "parse_median": statistics.median(row["parse_seconds"] for row in group),
                    "localization_median": statistics.median(timings),
                    "localization_p95": p95,
                })


if __name__ == "__main__":
    main()
