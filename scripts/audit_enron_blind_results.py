"""Create an auditable, event-level report for the frozen Enron blind test."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

METHODS = (
    "graph",
    "pattern",
    "warder_like",
    "formulaguard",
    "formulaguard_v3",
    "formulaguard_v3_real",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metric(rows: list[dict[str, str]]) -> dict[str, float | int]:
    return {
        "events": len(rows),
        "top1": statistics.fmean(float(row["top1"]) for row in rows),
        "top3": statistics.fmean(float(row["top3"]) for row in rows),
        "top5": statistics.fmean(float(row["top5"]) for row in rows),
        "mrr": statistics.fmean(float(row["mrr"]) for row in rows),
        "exam": statistics.fmean(float(row["exam"]) for row in rows),
    }


def bootstrap_difference(values: list[float], *, draws: int = 10_000, seed: int = 20260818) -> dict[str, float | int | list[float]]:
    rng = random.Random(seed)
    estimates = []
    for _ in range(draws):
        estimates.append(statistics.fmean(values[rng.randrange(len(values))] for _ in values))
    estimates.sort()
    return {
        "events": len(values),
        "mean_mrr_difference": statistics.fmean(values),
        "bootstrap_95_ci": [estimates[int(0.025 * draws)], estimates[int(0.975 * draws)]],
        "better_events": sum(value > 0 for value in values),
        "equal_events": sum(value == 0 for value in values),
        "worse_events": sum(value < 0 for value in values),
    }


def rows_for_method(by_event: dict[str, dict[str, dict[str, str]]], method: str) -> list[dict[str, str]]:
    return [methods[method] for _, methods in sorted(by_event.items()) if method in methods]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--frozen-config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    with args.raw.open("r", encoding="utf-8-sig", newline="") as handle:
        raw = list(csv.DictReader(handle))
    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        manifest = list(csv.DictReader(handle))
    frozen = json.loads(args.frozen_config.read_text(encoding="utf-8"))
    by_event: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    duplicate_pairs = []
    for row in raw:
        key = (row["instance_id"], row["method"])
        if row["method"] in by_event[row["instance_id"]]:
            duplicate_pairs.append(key)
        by_event[row["instance_id"]][row["method"]] = row
    manifest_ids = [row["instance_id"] for row in manifest]
    method_set = sorted({row["method"] for row in raw})
    missing_pairs = [
        (instance_id, method)
        for instance_id in manifest_ids
        for method in method_set
        if method not in by_event.get(instance_id, {})
    ]

    event_rows = []
    for instance_id in sorted(by_event):
        v3 = by_event[instance_id]["formulaguard_v3"]
        row = {
            "instance_id": instance_id,
            "workbook": v3["workbook"],
            "formula_count": int(v3["formula_count"]),
            "supported_formula_count": int(v3["supported_formula_count"]),
            "parser_coverage": float(v3["parser_coverage"]),
            "supported_source_formula_count": int(v3["supported_source_formula_count"]),
            "intervention_scope_fraction": min(1.0, 100 / max(1, int(v3["formula_count"]))),
            "intervention_scope": "full" if int(v3["formula_count"]) <= 100 else "capped_top_100",
            "v3_candidate_evidence": v3["candidate_evidence"],
            "v3_net_gain": v3["net_gain"],
        }
        for method in METHODS:
            source = by_event[instance_id][method]
            row[f"{method}_rank"] = int(source["rank"])
            row[f"{method}_mrr"] = float(source["mrr"])
            row[f"{method}_top5"] = int(source["top5"])
        event_rows.append(row)

    strata = {
        "all": event_rows,
        "full_intervention_le_100_formulas": [row for row in event_rows if row["intervention_scope"] == "full"],
        "capped_intervention_gt_100_formulas": [row for row in event_rows if row["intervention_scope"] != "full"],
    }
    by_stratum = {}
    for name, events in strata.items():
        ids = {row["instance_id"] for row in events}
        by_stratum[name] = {
            method: metric([row for row in rows_for_method(by_event, method) if row["instance_id"] in ids])
            for method in METHODS
        }

    comparisons = {}
    for left, right in (
        ("formulaguard_v3", "formulaguard"),
        ("formulaguard_v3", "graph"),
        ("formulaguard_v3", "pattern"),
        ("formulaguard_v3_real", "formulaguard"),
        ("formulaguard_v3_real", "graph"),
    ):
        values = [
            float(methods[left]["mrr"]) - float(methods[right]["mrr"])
            for _, methods in sorted(by_event.items())
        ]
        comparisons[f"{left}_minus_{right}"] = bootstrap_difference(values)

    parser_coverages = [row["parser_coverage"] for row in event_rows]
    integrity = {
        "manifest_events": len(manifest_ids),
        "raw_rows": len(raw),
        "methods_per_event_expected": len(method_set),
        "events_in_raw": len(by_event),
        "duplicate_event_method_pairs": duplicate_pairs,
        "missing_event_method_pairs": missing_pairs,
        "test_manifest_sha256": sha256(args.manifest),
        "frozen_manifest_sha256": frozen["untouched_test"]["manifest_sha256"],
        "manifest_hash_matches_freeze": sha256(args.manifest) == frozen["untouched_test"]["manifest_sha256"],
        "parser_coverage": {
            "mean": statistics.fmean(parser_coverages),
            "minimum": min(parser_coverages),
            "events_below_0_90": [
                row["instance_id"] for row in event_rows if row["parser_coverage"] < 0.90
            ],
        },
        "full_intervention_events": len(strata["full_intervention_le_100_formulas"]),
        "capped_intervention_events": len(strata["capped_intervention_gt_100_formulas"]),
    }
    graph_comparison = comparisons["formulaguard_v3_minus_graph"]
    conclusion = {
        "stable_improvement_over_v2": False,
        "stable_improvement_over_graph": False,
        "reason": (
            "The 95% bootstrap interval for v3 minus v2 crosses zero, and the "
            "v3 minus graph interval is below zero. The blind test therefore does not "
            "support a claim that the counterfactual layer improves real-workbook localization."
        ),
        "v3_minus_graph_mrr_difference": graph_comparison["mean_mrr_difference"],
        "v3_minus_graph_bootstrap_95_ci": graph_comparison["bootstrap_95_ci"],
    }
    payload = {
        "schema_version": 1,
        "dataset": "Enron Error Corpus frozen external test",
        "integrity": integrity,
        "metrics_by_intervention_scope": by_stratum,
        "paired_bootstrap_mrr": comparisons,
        "conclusion": conclusion,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "blind_result_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    event_fields = list(event_rows[0])
    with (args.output_dir / "event_detail.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=event_fields)
        writer.writeheader()
        writer.writerows(event_rows)
    report = f"""# Enron 冻结盲测审计（v3-real）

## 数据完整性

- 冻结测试清单事件：{integrity['manifest_events']}；原始结果行：{integrity['raw_rows']}；
  每事件方法数：{integrity['methods_per_event_expected']}；
- 重复 event-method 对：{len(duplicate_pairs)}；缺失对：{len(missing_pairs)}；
- 清单哈希与冻结配置一致：{integrity['manifest_hash_matches_freeze']}；
- 公式解析覆盖率平均值：{integrity['parser_coverage']['mean']:.3f}，最低值：
  {integrity['parser_coverage']['minimum']:.3f}；低于0.90的事件：
  {', '.join(integrity['parser_coverage']['events_below_0_90']) or '无'}。

## 主结果（20个未见事件）

| 方法 | Top-1 | Top-5 | MRR | EXAM |
|---|---:|---:|---:|---:|
"""
    for method, values in sorted(by_stratum["all"].items(), key=lambda item: -float(item[1]["mrr"])):
        report += f"| {method} | {values['top1']:.3f} | {values['top5']:.3f} | {values['mrr']:.3f} | {values['exam']:.3f} |\n"
    report += f"""

## 关键比较

- v3 − v2：MRR差 {comparisons['formulaguard_v3_minus_formulaguard']['mean_mrr_difference']:+.4f}，
  95% bootstrap CI {comparisons['formulaguard_v3_minus_formulaguard']['bootstrap_95_ci']}；
- v3 − 图基线：MRR差 {graph_comparison['mean_mrr_difference']:+.4f}，95% bootstrap CI
  {graph_comparison['bootstrap_95_ci']}；
- v3-real − v2：MRR差 {comparisons['formulaguard_v3_real_minus_formulaguard']['mean_mrr_difference']:+.4f}，
  95% bootstrap CI {comparisons['formulaguard_v3_real_minus_formulaguard']['bootstrap_95_ci']}。

## 规模边界

- 全量干预（不超过100个公式）：{integrity['full_intervention_events']}个事件；
- 只对局部先验Top-100做反事实干预：{integrity['capped_intervention_events']}个事件。

因此，主结论必须是：该外部盲测**不支持**“FormulaGuard v3在真实表格上
稳定优于无真值基线”的说法。可以报告其高于精确随机期望的定位表现、
可审计证据等级以及受控合成机制结果，但不能将其写成真实泛化优势。
"""
    (args.output_dir / "BLIND_RESULT_AUDIT.md").write_text(report, encoding="utf-8")
    print(args.output_dir / "blind_result_audit.json")
    print(args.output_dir / "event_detail.csv")
    print(args.output_dir / "BLIND_RESULT_AUDIT.md")


if __name__ == "__main__":
    main()
