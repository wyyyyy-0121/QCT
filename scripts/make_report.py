from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def load_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def pct(value):
    if value in (None, ""):
        return "—"
    return f"{100 * float(value):.1f}%"


def decimal(value, digits=3):
    if value in (None, ""):
        return "—"
    return f"{float(value):.{digits}f}"


def main():
    parser = argparse.ArgumentParser(description="Create a measured Markdown report from experiment CSV files")
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
    primary = "formulaguard_v3" if any(row["method"] == "formulaguard_v3" for row in summary) else "formulaguard"

    lines = [
        "# FormulaGuard 实验结果（脚本自动生成）",
        "",
        "> 本报告中的数字均由原始 CSV 自动计算。Smoke 结果只用于工程验收，不代表正式论文结论或获奖保证。",
        "",
        "## 1. 数据有效性",
        "",
        f"- 总实例：{quality['total']}；有效：{quality['valid']}；排除：{quality['excluded']}；有效率：{pct(quality['valid_rate'])}",
        f"- 传播深度：`{json.dumps(quality.get('by_depth', {}), ensure_ascii=False)}`",
        f"- 错误类型：`{json.dumps(quality.get('by_mutation_type', {}), ensure_ascii=False)}`",
        f"- 数据分区：`{json.dumps(quality.get('by_split', {}), ensure_ascii=False)}`",
        "",
        "## 2. 总体结果",
        "",
        "| 方法 | 实例 | Top-1 | Top-5 | MRR | EXAM | 修复准确率 | Coverage@15 | Source-first | Path coverage | Repair safety | 中位耗时/s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary:
        lines.append(
            f"| {row['method']} | {row['instances']} | {pct(row['top1'])} | {pct(row['top5'])} | "
            f"{decimal(row['mrr'])} | {decimal(row['exam'])} | {pct(row['repair_exact'])} | "
            f"{pct(row['candidate_coverage_at_15'])} | {pct(row.get('source_first_in_causal_cone'))} | "
            f"{pct(row.get('path_coverage'))} | {pct(row.get('repair_safety'))} | {decimal(row['runtime_median'], 4)} |"
        )

    ci = comparison["bootstrap_95_ci"]
    lines += [
        "",
        "## 3. 与最强无真值基线的配对比较",
        "",
        f"- 主模型：`{primary}`；最强无真值基线：`{comparison['strongest_no_oracle_baseline']}`",
        f"- 配对实例：{comparison['paired_instances']}；平均 MRR 差：{comparison['mean_mrr_difference']:.4f}",
        f"- Bootstrap 95% CI：[{ci[0]:.4f}, {ci[1]:.4f}]",
        f"- 主模型更优比例：{pct(comparison['formula_guard_better_fraction'])}",
    ]

    v3_path = args.results / "v3_vs_v2.json"
    if v3_path.is_file():
        v3 = json.loads(v3_path.read_text(encoding="utf-8"))
        v3_ci = v3["bootstrap_95_ci"]
        lines += [
            "",
            "## 4. v3 与冻结 v2 的同数据配对比较",
            "",
            f"- 配对实例：{v3['paired_instances']}；平均 MRR 差（v3-v2）：{v3['mean_mrr_difference_v3_minus_v2']:.4f}",
            f"- Bootstrap 95% CI：[{v3_ci[0]:.4f}, {v3_ci[1]:.4f}]",
            f"- v3 更优比例：{pct(v3['v3_better_fraction'])}；相同比例：{pct(v3['v3_equal_fraction'])}",
        ]

    section_number = 5 if v3_path.is_file() else 4
    lines += [
        "",
        f"## {section_number}. 拓扑分层",
        "",
        "| 拓扑 | 方法 | 实例 | Top-1 | Top-5 | MRR |",
        "|---|---|---:|---:|---:|---:|",
    ]
    selected = {primary, comparison["strongest_no_oracle_baseline"]}
    for row in topology_rows:
        if row["method"] in selected:
            lines.append(
                f"| {row['topology_id']} | {row['method']} | {row['instances']} | "
                f"{pct(row['top1'])} | {pct(row['top5'])} | {decimal(row['mrr'])} |"
            )

    lines += [
        "",
        f"## {section_number + 1}. 干净工作簿报警与失败案例",
        "",
        f"- 干净工作簿：{clean['clean_workbooks']}；报警分数：`{clean.get('alarm_score', 'source_score')}`",
        f"- 校准错误召回率：{pct(clean['calibration_mutant_recall'])}；校准干净表报警率：{pct(clean['calibration_clean_alarm_rate'])}",
        f"- 当前干净表报警率：{pct(clean['alarm_rate'])}；阈值门槛通过：{clean['threshold_gate_passed']}",
        f"- 主模型落后于最强基线的实例数：{len(failure_rows)}；详见 `failure_cases.csv`。",
        "",
        f"## {section_number + 2}. 结论使用规则",
        "",
        "1. 只有配对差值为正且 95% 置信区间不跨 0，论文才写“稳定优于”。",
        "2. 合成数据与 Enron 真实错误必须分开报告。",
        "3. `-like` 基线不得表述为原作者完整实现。",
        "4. Full 结果产生后不得根据测试集调整权重、阈值或核心逻辑。",
        "5. 所有论文表格和图必须能从本目录原始 CSV 自动重建。",
        "",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
