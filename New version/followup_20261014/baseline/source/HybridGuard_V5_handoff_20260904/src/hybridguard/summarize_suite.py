"""Aggregate a multi-workbook StructuralGuard / FormulaGuard V5 experiment."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


def _top(evaluation: dict[str, object], k: int) -> dict[str, object]:
    rows = evaluation["top_k"]
    return next((row for row in rows if row["k"] == k), {"hits": None, "precision": None, "recall": None})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("suite_dir", type=Path)
    parser.add_argument("--results-dir", type=Path)
    args = parser.parse_args(argv)
    results_dir = args.results_dir or args.suite_dir / "results_v5"

    rows: list[dict[str, object]] = []
    run_rows: list[dict[str, object]] = []
    for result_path in sorted(results_dir.glob("*/hierarchical_results.json")):
        scenario = result_path.parent.name
        result = json.loads(result_path.read_text(encoding="utf-8"))
        truth = json.loads((args.suite_dir / f"{scenario}_truth.json").read_text(encoding="utf-8"))
        total_wall = sum(item["wall_seconds"] for item in result["performance"].values())
        peak_memory = max(item["process_peak_working_set_mib"] for item in result["performance"].values())
        run_rows.append({
            "scenario": scenario,
            "family": truth["family"],
            "seed": truth["seed"],
            "formula_cells": truth["formula_cells"],
            "error_cells": truth["error_cells"],
            "error_rate": truth["error_rate"],
            "truth_groups": len(truth["groups"]),
            "detected_groups": result["groups_detected"],
            "validated_groups": result["groups_validated"],
            "representatives_checked": result["representatives_checked"],
            "total_wall_seconds": total_wall,
            "peak_memory_mib": peak_memory,
        })
        for evaluation in result["evaluations"]:
            top10, top100, top500 = (_top(evaluation, k) for k in (10, 100, 500))
            matched_budget = _top(evaluation, int(truth["error_cells"]))
            rows.append({
                "scenario": scenario,
                "family": truth["family"],
                "seed": truth["seed"],
                "model": evaluation["model"],
                "error_cells": truth["error_cells"],
                "error_rate": truth["error_rate"],
                "average_precision": evaluation["average_precision"],
                "top10_hits": top10["hits"],
                "top10_recall": top10["recall"],
                "top100_hits": top100["hits"],
                "top100_recall": top100["recall"],
                "top500_hits": top500["hits"],
                "top500_recall": top500["recall"],
                "matched_budget_hits": matched_budget["hits"],
                "matched_budget_recall": matched_budget["recall"],
                "exact_repairs": evaluation["exact_repairs"],
            })

    if not rows:
        raise SystemExit("No experiment results found")

    aggregate: list[dict[str, object]] = []
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["family"]), str(row["model"]))].append(row)
    for (family, model), items in sorted(grouped.items()):
        aggregate.append({
            "family": family,
            "model": model,
            "runs": len(items),
            "mean_average_precision": statistics.fmean(float(x["average_precision"]) for x in items),
            "min_average_precision": min(float(x["average_precision"]) for x in items),
            "max_average_precision": max(float(x["average_precision"]) for x in items),
            "mean_top100_recall": statistics.fmean(float(x["top100_recall"]) for x in items),
            "mean_matched_budget_recall": statistics.fmean(float(x["matched_budget_recall"]) for x in items),
            "total_exact_repairs": sum(int(x["exact_repairs"]) for x in items),
            "total_errors": sum(int(x["error_cells"]) for x in items),
        })

    def write_csv(path: Path, data: list[dict[str, object]]) -> None:
        with path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)

    write_csv(results_dir / "per_model_results.csv", rows)
    write_csv(results_dir / "per_run_performance.csv", run_rows)
    write_csv(results_dir / "aggregate_by_family.csv", aggregate)
    payload = {"protocol": "multi_workbook_v5_experiment_summary_v1", "runs": run_rows, "per_model": rows, "aggregate": aggregate}
    (results_dir / "suite_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    labels = {
        "StructuralGuard": "StructuralGuard",
        "FormulaGuard V5 structural-semantic guard": "FormulaGuard V5",
        "Hierarchical HybridGuard V5 (group representative validation)": "HybridGuard V5",
    }
    lines = [
        "# 六工作簿多轮实验报告（FormulaGuard V5）", "",
        "每份工作簿包含75,000个非空单元格和7,505个公式。稀疏组分别注入12、30、60个随机单点错误；系统性组注入多个连续块或整列错误。", "",
        "## 分组汇总", "",
        "| 场景族 | 模型 | 运行数 | 平均AP | AP范围 | 等错误数预算平均召回 | 正确修复 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for item in aggregate:
        lines.append(
            f"| {item['family']} | {labels.get(item['model'], item['model'])} | {item['runs']} | "
            f"{item['mean_average_precision']:.4f} | {item['min_average_precision']:.4f}–{item['max_average_precision']:.4f} | "
            f"{item['mean_matched_budget_recall']:.4f} | {item['total_exact_repairs']}/{item['total_errors']} |"
        )
    lines.extend(["", "## 单次运行", "", "| 工作簿 | 类型 | 错误数 | 错误率 | 检出/真实组 | 代表点 | 总耗时 | 峰值内存 |", "|---|---|---:|---:|---:|---:|---:|---:|"])
    for row in run_rows:
        lines.append(
            f"| {row['scenario']} | {row['family']} | {row['error_cells']} | {100*row['error_rate']:.3f}% | "
            f"{row['detected_groups']}/{row['truth_groups']} | {row['representatives_checked']} | "
            f"{row['total_wall_seconds']:.2f}秒 | {row['peak_memory_mib']:.2f} MiB |"
        )
    lines.extend([
        "", "## 解释边界", "",
        "V5对稀疏单点错误的排名很强；在本套连续块和整列公式中，V5单独运行仍会遗漏大量组内单元格。Hybrid的系统性优势来自跨平行表多数共识和组级传播，V5主要增强局部排名与候选生成。稀疏seed202和seed303各有一对相邻单点被检测器合并为一个连续组，因此检测组数少1，但错误单元格与修复均未遗漏。所有答案键只用于事后评分。", "",
    ])
    (results_dir / "MULTI_EXPERIMENT_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
