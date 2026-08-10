from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.benchmark import parse_cell_label
from formulaguard.formula import normalized_formula
from formulaguard.localize import localize
from formulaguard.workbook import WorkbookModel


METHODS = ["random", "excel_like", "pattern", "graph", "behavior", "excelint_like", "warder_like", "formulaguard"]


def main():
    parser = argparse.ArgumentParser(description="Evaluate labeled real workbooks such as the Enron Error Corpus")
    parser.add_argument("--manifest", type=Path, required=True, help="CSV: instance_id,workbook,source_cell[,correct_formula]")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-limit", type=int, default=15)
    args = parser.parse_args()
    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        instances = list(reader)
        fieldnames = set(reader.fieldnames or [])
    if not instances:
        raise SystemExit(f"No labeled instances found in: {args.manifest}")
    required = {"instance_id", "workbook", "source_cell"}
    missing = required - fieldnames
    if missing:
        raise SystemExit(f"Manifest is missing required columns: {', '.join(sorted(missing))}")
    rows = []
    exclusions = []
    for index, instance in enumerate(instances, 1):
        include = instance.get("include", "1").strip().lower() not in {"0", "false", "no", "exclude"}
        if not include:
            exclusions.append({
                "instance_id": instance["instance_id"],
                "reason": instance.get("exclusion_reason", "excluded_in_manifest") or "excluded_in_manifest",
            })
            continue
        workbook_path = (args.manifest.parent / instance["workbook"]).resolve()
        if not workbook_path.is_file():
            exclusions.append({"instance_id": instance["instance_id"], "reason": f"workbook_not_found:{workbook_path}"})
            continue
        try:
            source = parse_cell_label(instance["source_cell"])
            model = WorkbookModel.from_xlsx(workbook_path)
        except Exception as exc:
            exclusions.append({"instance_id": instance["instance_id"], "reason": f"load_error:{type(exc).__name__}:{exc}"})
            continue
        if source not in model.formulas:
            exclusions.append({"instance_id": instance["instance_id"], "reason": "source_cell_is_not_a_formula"})
            continue
        for method in METHODS:
            started = time.perf_counter()
            results = localize(model, method, candidate_limit=args.candidate_limit)
            elapsed = time.perf_counter() - started
            rank = next((i for i, result in enumerate(results, 1) if result.cell == source), len(results) + 1)
            source_result = next((result for result in results if result.cell == source), None)
            repair = source_result.candidate_formula if source_result else None
            correct = instance.get("correct_formula", "")
            repair_exact = bool(correct and repair and normalized_formula(correct) == normalized_formula(repair))
            rows.append({
                "instance_id": instance["instance_id"],
                "method": method,
                "formula_count": len(model.formulas),
                "rank": rank,
                "top1": int(rank <= 1),
                "top3": int(rank <= 3),
                "top5": int(rank <= 5),
                "mrr": 1 / rank,
                "exam": rank / max(1, len(model.formulas)),
                "repair_exact": int(repair_exact),
                "repair_evaluable": int(bool(correct)),
                "runtime_seconds": elapsed,
            })
        print(f"[{index}/{len(instances)}] {instance['instance_id']}", flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "external_exclusions.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["instance_id", "reason"])
        writer.writeheader()
        writer.writerows(exclusions)
    if not rows:
        raise SystemExit("No external instances could be evaluated. See external_exclusions.csv.")
    with (args.output / "external_raw.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (args.output / "external_summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["method", "instances", "top1", "top3", "top5", "mrr", "exam", "repair_evaluable", "repair_exact", "runtime_median"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for method in METHODS:
            group = [row for row in rows if row["method"] == method]
            repair_rows = [row for row in group if row["repair_evaluable"]]
            writer.writerow({
                "method": method,
                "instances": len(group),
                "top1": statistics.fmean(row["top1"] for row in group),
                "top3": statistics.fmean(row["top3"] for row in group),
                "top5": statistics.fmean(row["top5"] for row in group),
                "mrr": statistics.fmean(row["mrr"] for row in group),
                "exam": statistics.fmean(row["exam"] for row in group),
                "repair_evaluable": len(repair_rows),
                "repair_exact": statistics.fmean(row["repair_exact"] for row in repair_rows) if repair_rows else "",
                "runtime_median": statistics.median(row["runtime_seconds"] for row in group),
            })
    audit = {
        "manifest_rows": len(instances),
        "evaluated_instances": len({row["instance_id"] for row in rows}),
        "excluded_instances": len(exclusions),
        "quantitative_reporting_allowed": len({row["instance_id"] for row in rows}) >= 15,
        "reporting_rule": "Use aggregate external metrics only with at least 15 supported faults; otherwise report exploratory cases.",
        "methods": METHODS,
        "synthetic_results_must_remain_separate": True,
    }
    (args.output / "external_dataset_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
