from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def load_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def pct(value):
    return f"{100 * float(value):.1f}%"


def main():
    parser = argparse.ArgumentParser(description="Create a Markdown experiment report from measured CSV files")
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    summary = load_csv(args.results / "summary.csv")
    topology_rows = load_csv(args.results / "by_topology.csv")
    comparison = json.loads((args.results / "paired_comparison.json").read_text(encoding="utf-8"))
    quality = json.loads((args.validation / "dataset_quality.json").read_text(encoding="utf-8"))
    clean = json.loads((args.results / "clean_summary.json").read_text(encoding="utf-8"))
    failure_rows = load_csv(args.results / "failure_cases.csv")
    output = args.output or args.results / "REPORT.md"

    lines = [
        "# FormulaGuard 实验结果（脚本自动生成）",
        "",
        "> 本报告中的数字来自原始CSV，是当前代码和当前数据版本的测量结果，不代表竞赛获奖保证。",
        "",
        "## 1. 数据有效性",
        "",
        f"- 生成实例：{quality['total']}",
        f"- 有效实例：{quality['valid']}",
        f"- 排除实例：{quality['excluded']}",
        f"- 有效率：{pct(quality['valid_rate'])}",
        f"- 深度分布：{json.dumps(quality.get('by_depth', {}), ensure_ascii=False)}",
        f"- 错误类型分布：{json.dumps(quality.get('by_mutation_type', {}), ensure_ascii=False)}",
        f"- 数据分区：{json.dumps(quality.get('by_split', {}), ensure_ascii=False)}",
        "",
        "## 2. 主结果",
        "",
        "| 方法 | 实例 | Top-1 | Top-3 | Top-5 | MRR | EXAM | 修复Top-1 | Coverage@10 | Coverage@15 | 中位耗时/s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary:
        lines.append(
            f"| {row['method']} | {row['instances']} | {pct(row['top1'])} | {pct(row['top3'])} | "
            f"{pct(row['top5'])} | {float(row['mrr']):.3f} | {float(row['exam']):.3f} | "
            f"{pct(row['repair_exact'])} | {pct(row['candidate_coverage_at_10'])} | "
            f"{pct(row['candidate_coverage_at_15'])} | {float(row['runtime_median']):.4f} |"
        )

    lines += [
        "",
        "## 3. 与最强无真值基线的配对比较",
        "",
        f"- 最强无真值基线：`{comparison['strongest_no_oracle_baseline']}`",
        f"- 配对实例数：{comparison['paired_instances']}",
        f"- FormulaGuard平均MRR差：{comparison['mean_mrr_difference']:.4f}",
        f"- Bootstrap 95% CI：[{comparison['bootstrap_95_ci'][0]:.4f}, {comparison['bootstrap_95_ci'][1]:.4f}]",
        f"- FormulaGuard更优比例：{pct(comparison['formula_guard_better_fraction'])}",
        "",
        "## 4. 按依赖拓扑分层",
        "",
        "| 拓扑 | 方法 | 实例 | Top-1 | Top-5 | MRR |",
        "|---|---|---:|---:|---:|---:|",
    ]
    selected_methods = {"formulaguard", comparison["strongest_no_oracle_baseline"]}
    for row in topology_rows:
        if row["method"] in selected_methods:
            lines.append(
                f"| {row['topology_id']} | {row['method']} | {row['instances']} | "
                f"{pct(row['top1'])} | {pct(row['top5'])} | {float(row['mrr']):.3f} |"
            )

    lines += [
        "",
        "## 5. 干净工作簿与失败案例",
        "",
        f"- 干净合成工作簿数：{clean['clean_workbooks']}",
        f"- 目标错误召回率：{pct(clean['target_mutant_recall'])}",
        f"- 校准错误召回率：{pct(clean['calibration_mutant_recall'])}",
        f"- 校准干净表报警率：{pct(clean['calibration_clean_alarm_rate'])}",
        f"- 当前数据干净表报警率：{pct(clean['alarm_rate'])}",
        f"- 阈值验收通过：{clean['threshold_gate_passed']}",
        f"- FormulaGuard落后于最强无真值基线的实例数：{len(failure_rows)}",
        "- 失败实例详见 `failure_cases.csv`。",
        "",
        "## 6. 写论文前必须检查",
        "",
        "1. 若置信区间跨过0，不得写成稳定优于基线。",
        "2. 合成数据与真实错误数据必须分表报告。",
        "3. `-like`基线不得冒充原作者完整实现。",
        "4. 同时检查错误类型、深度、族、拓扑和失败实例，不只看总体均值。",
        "5. 所有论文表格由这些CSV重新生成，禁止手工修改数字。",
        "",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
