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
from formulaguard.formula import FormulaSyntaxError, normalized_formula, parse_formula
from formulaguard.localize import localize
from formulaguard.workbook import WorkbookModel


METHODS = [
    "random",
    "excel_like",
    "pattern",
    "graph",
    "behavior",
    "excelint_like",
    "warder_like",
    "formulaguard",
    "formulaguard_v3",
    "formulaguard_v3_real",
]


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
    required = {"instance_id", "workbook"}
    missing = required - fieldnames
    if missing:
        raise SystemExit(f"Manifest is missing required columns: {', '.join(sorted(missing))}")
    if "source_cell" not in fieldnames and "source_cells" not in fieldnames:
        raise SystemExit("Manifest must contain source_cell or source_cells")
    rows = []
    exclusions = []
    result_cache = {}
    runtime_cache = {}
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
            source_labels = [
                label.strip() for label in instance.get("source_cells", "").split(";")
                if label.strip()
            ] or [instance.get("source_cell", "").strip()]
            sources = {parse_cell_label(label) for label in source_labels if label}
            model = WorkbookModel.from_xlsx(workbook_path)
        except Exception as exc:
            exclusions.append({"instance_id": instance["instance_id"], "reason": f"load_error:{type(exc).__name__}:{exc}"})
            continue
        formula_sources = sources & set(model.formulas)
        if not formula_sources:
            exclusions.append({
                "instance_id": instance["instance_id"],
                "reason": "no_labeled_source_cell_is_a_formula",
            })
            continue
        supported_formula_count = 0
        for formula in model.formulas.values():
            try:
                parse_formula(formula)
                supported_formula_count += 1
            except FormulaSyntaxError:
                pass
        supported_sources = set()
        source_parse_errors = []
        for source in formula_sources:
            try:
                parse_formula(model.formulas[source])
                supported_sources.add(source)
            except FormulaSyntaxError as exc:
                source_parse_errors.append(str(exc))
        if not supported_sources:
            exclusions.append({
                "instance_id": instance["instance_id"],
                "reason": f"all_source_formulas_unsupported:{' | '.join(source_parse_errors[:3])}",
            })
            continue
        parser_coverage = supported_formula_count / max(1, len(model.formulas))
        for method in METHODS:
            cache_key = (workbook_path, method, args.candidate_limit)
            if cache_key not in result_cache:
                started = time.perf_counter()
                result_cache[cache_key] = localize(
                    model, method, candidate_limit=args.candidate_limit
                )
                runtime_cache[cache_key] = time.perf_counter() - started
            results = result_cache[cache_key]
            elapsed = runtime_cache[cache_key]
            ranked_hits = [
                (i, result) for i, result in enumerate(results, 1)
                if result.cell in supported_sources
            ]
            rank, source_result = min(
                ranked_hits,
                default=(len(results) + 1, None),
                key=lambda item: item[0],
            )
            repair = source_result.candidate_formula if source_result else None
            correct = instance.get("correct_formula", "")
            repair_exact = bool(
                len(supported_sources) == 1 and correct and repair
                and normalized_formula(correct) == normalized_formula(repair)
            )
            rows.append({
                "instance_id": instance["instance_id"],
                "workbook": instance["workbook"],
                "error_event": instance.get("error_event", ""),
                "error_type": instance.get("error_type", ""),
                "error_subtype": instance.get("error_subtype", ""),
                "method": method,
                "formula_count": len(model.formulas),
                "supported_formula_count": supported_formula_count,
                "parser_coverage": parser_coverage,
                "labeled_cell_count": len(sources),
                "labeled_formula_count": len(formula_sources),
                "supported_source_formula_count": len(supported_sources),
                "source_parser_coverage": len(supported_sources) / max(1, len(formula_sources)),
                "rank": rank,
                "top1": int(rank <= 1),
                "top3": int(rank <= 3),
                "top5": int(rank <= 5),
                "mrr": 1 / rank,
                "exam": rank / max(1, len(model.formulas)),
                "repair_exact": int(repair_exact),
                "repair_evaluable": int(bool(correct)),
                "source_score": source_result.score if source_result else 0.0,
                "candidate_formula": repair or "",
                "candidate_evidence": (
                    source_result.evidence.get("candidate_evidence", "") if source_result else ""
                ),
                "net_gain": source_result.evidence.get("net_gain", "") if source_result else "",
                "structure_reliability": (
                    source_result.evidence.get("structure_reliability", "") if source_result else ""
                ),
                "diagnostic_status": (
                    source_result.evidence.get("diagnostic_status", "") if source_result else ""
                ),
                "counterfactual_evidence_strength": (
                    source_result.evidence.get("counterfactual_evidence_strength", "")
                    if source_result else ""
                ),
                "base_rank": source_result.evidence.get("base_rank", "") if source_result else "",
                "car_rank": source_result.evidence.get("car_rank", "") if source_result else "",
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
        fields = [
            "method", "instances", "workbooks", "top1", "top3", "top5", "mrr", "exam",
            "parser_coverage_median", "repair_evaluable", "repair_exact", "runtime_median",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for method in METHODS:
            group = [row for row in rows if row["method"] == method]
            repair_rows = [row for row in group if row["repair_evaluable"]]
            writer.writerow({
                "method": method,
                "instances": len(group),
                "workbooks": len({row["workbook"] for row in group}),
                "top1": statistics.fmean(row["top1"] for row in group),
                "top3": statistics.fmean(row["top3"] for row in group),
                "top5": statistics.fmean(row["top5"] for row in group),
                "mrr": statistics.fmean(row["mrr"] for row in group),
                "exam": statistics.fmean(row["exam"] for row in group),
                "parser_coverage_median": statistics.median(row["parser_coverage"] for row in group),
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
        "parser_coverage_must_be_reported": True,
        "unsupported_source_formulas_are_excluded": True,
        "external_models_under_test": ["formulaguard_v3", "formulaguard_v3_real"],
    }
    (args.output / "external_dataset_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
