"""Explain the V5-Core Enron safety-gate failure without changing the model.

This is a post-hoc, label-aware diagnostic.  It reads only already-written
rankings and the fixed Enron manifest; it is never imported by a localizer.
The outputs separate parser coverage from ranking generalization so that an
unsupported Excel construct cannot be used as a blanket explanation for a
model-level regression.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


METHODS = ("v4", "v5_rule", "v5_learned")


def parse_sources(text: str) -> set[str]:
    result: set[str] = set()
    for value in (text or "").split(";"):
        value = value.strip()
        if "!" not in value:
            continue
        sheet, address = value.rsplit("!", 1)
        result.add(f"{sheet.strip(chr(39))}!{address.replace('$', '').upper()}")
    return result


def mean(rows: list[dict], key: str) -> float:
    return statistics.fmean(float(row[key]) for row in rows) if rows else 0.0


def summarize(rows: list[dict]) -> dict:
    payload: dict[str, object] = {"events": len(rows)}
    for method in METHODS:
        payload[method] = {
            "top5": mean(rows, f"{method}_top5"),
            "mrr": mean(rows, f"{method}_mrr"),
            "exam": mean(rows, f"{method}_exam"),
        }
    payload["rule_minus_v4_mrr"] = mean(rows, "rule_minus_v4_mrr")
    payload["learned_minus_v4_mrr"] = mean(rows, "learned_minus_v4_mrr")
    return payload


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write empty table: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("data/external/enron/manifest.csv"))
    parser.add_argument("--raw", type=Path, default=Path("results/v5_core_development/enron/enron_raw.csv"))
    parser.add_argument("--shards", type=Path, default=Path("results/v5_core_development/enron/shards"))
    parser.add_argument("--summary", type=Path, default=Path("results/v5_core_development/enron/enron_summary.json"))
    parser.add_argument("--output", type=Path, default=Path("results/v5_core_development/enron_failure"))
    parser.add_argument("--research-report", type=Path, default=Path("research/V5_CORE_ENRON_FAILURE_DIAGNOSIS.md"))
    args = parser.parse_args()

    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        events = [row for row in csv.DictReader(handle) if row.get("include", "1") == "1"]
    if len(events) != 30:
        raise SystemExit(f"Expected the fixed 30 Enron events; found {len(events)}")

    with args.raw.open("r", encoding="utf-8-sig", newline="") as handle:
        raw = list(csv.DictReader(handle))
    metric_lookup = {(row["instance_id"], row["method"]): row for row in raw}
    if len(metric_lookup) != len(events) * len(METHODS):
        raise SystemExit("Raw Enron table is incomplete or contains duplicate event-method rows")

    workbooks = sorted({row["workbook"] for row in events})
    shard_paths = sorted(args.shards.glob("workbook_*.json"))
    if len(shard_paths) != len(workbooks):
        raise SystemExit(f"Expected {len(workbooks)} shards; found {len(shard_paths)}")
    records = {
        relative: json.loads(path.read_text(encoding="utf-8"))
        for relative, path in zip(workbooks, shard_paths, strict=True)
    }
    for relative, record in records.items():
        if record["workbook"] != relative:
            raise SystemExit(f"Shard/workbook mapping mismatch: {relative} != {record['workbook']}")

    diagnostics: list[dict] = []
    for event in events:
        record = records[event["workbook"]]
        sources = parse_sources(event.get("source_cells") or event.get("source_cell", ""))
        unsupported = set(record.get("unsupported_formula_cells", []))
        unsupported_sources = sorted(sources & unsupported)
        source_count = len(sources)
        workbook_unsupported_count = int(record.get("unsupported_formula_count", 0))
        row: dict[str, object] = {
            "instance_id": event["instance_id"],
            "workbook": event["workbook"],
            "source_cells": ";".join(sorted(sources)),
            "source_count": source_count,
            "source_grain": "single_source" if source_count == 1 else "multi_source",
            "error_type": event.get("error_type", ""),
            "error_subtype": event.get("error_subtype", ""),
            "change": event.get("change", ""),
            "description": event.get("error_description", ""),
            "formula_count": int(record["formula_count"]),
            "workbook_unsupported_count": workbook_unsupported_count,
            "workbook_has_unsupported": int(workbook_unsupported_count > 0),
            "source_unsupported_count": len(unsupported_sources),
            "source_has_unsupported": int(bool(unsupported_sources)),
            "unsupported_source_cells": ";".join(unsupported_sources),
        }
        for method in METHODS:
            metric = metric_lookup[(event["instance_id"], method)]
            row[f"{method}_rank"] = int(metric["rank"])
            row[f"{method}_top5"] = int(metric["top5"])
            row[f"{method}_mrr"] = float(metric["mrr"])
            row[f"{method}_exam"] = float(metric["exam"])
        row["rule_minus_v4_mrr"] = float(row["v5_rule_mrr"]) - float(row["v4_mrr"])
        row["learned_minus_v4_mrr"] = float(row["v5_learned_mrr"]) - float(row["v4_mrr"])
        row["rule_outcome"] = (
            "win" if row["rule_minus_v4_mrr"] > 1e-12
            else "loss" if row["rule_minus_v4_mrr"] < -1e-12
            else "tie"
        )
        row["learned_outcome"] = (
            "win" if row["learned_minus_v4_mrr"] > 1e-12
            else "loss" if row["learned_minus_v4_mrr"] < -1e-12
            else "tie"
        )
        diagnostics.append(row)

    cohorts = {
        "all_events": diagnostics,
        "fully_supported_workbook": [r for r in diagnostics if not r["workbook_has_unsupported"]],
        "complex_workbook_supported_source": [
            r for r in diagnostics if r["workbook_has_unsupported"] and not r["source_has_unsupported"]
        ],
        "unsupported_true_source": [r for r in diagnostics if r["source_has_unsupported"]],
        "single_source": [r for r in diagnostics if r["source_grain"] == "single_source"],
        "multi_source": [r for r in diagnostics if r["source_grain"] == "multi_source"],
    }
    cohort_summary = {name: summarize(rows) for name, rows in cohorts.items()}

    cohort_rows: list[dict] = []
    for cohort, rows in cohorts.items():
        summary = cohort_summary[cohort]
        for method in METHODS:
            values = summary[method]
            cohort_rows.append({
                "cohort": cohort,
                "events": len(rows),
                "method": method,
                "top5": values["top5"],
                "mrr": values["mrr"],
                "exam": values["exam"],
                "mrr_minus_v4": values["mrr"] - summary["v4"]["mrr"],
            })

    stated = json.loads(args.summary.read_text(encoding="utf-8"))["summary"]
    recomputed = cohort_summary["all_events"]
    reconciliation = {}
    for method in METHODS:
        reconciliation[method] = {
            key: abs(float(stated[method][key]) - float(recomputed[method][key]))
            for key in ("top5", "mrr", "exam")
        }
    summary_reconciled = all(
        value <= 1e-12
        for method in reconciliation.values()
        for value in method.values()
    )
    if not summary_reconciled:
        raise SystemExit("Event diagnostics do not reconcile to enron_summary.json")

    outcome_counts = {}
    for head, column in (("rule", "rule_outcome"), ("learned", "learned_outcome")):
        outcome_counts[head] = {
            label: sum(row[column] == label for row in diagnostics)
            for label in ("win", "tie", "loss")
        }
    largest_losses = {
        head: [
            {
                "instance_id": row["instance_id"],
                "workbook": row["workbook"],
                "source_grain": row["source_grain"],
                "source_has_unsupported": bool(row["source_has_unsupported"]),
                "v4_rank": row["v4_rank"],
                "v5_rank": row[f"v5_{head}_rank"],
                "mrr_delta": row[f"{head}_minus_v4_mrr"],
            }
            for row in sorted(diagnostics, key=lambda item: item[f"{head}_minus_v4_mrr"])[:8]
        ]
        for head in ("rule", "learned")
    }
    largest_wins = {
        head: [
            {
                "instance_id": row["instance_id"],
                "workbook": row["workbook"],
                "source_grain": row["source_grain"],
                "source_has_unsupported": bool(row["source_has_unsupported"]),
                "v4_rank": row["v4_rank"],
                "v5_rank": row[f"v5_{head}_rank"],
                "mrr_delta": row[f"{head}_minus_v4_mrr"],
            }
            for row in sorted(
                diagnostics, key=lambda item: item[f"{head}_minus_v4_mrr"], reverse=True
            )[:8]
        ]
        for head in ("rule", "learned")
    }

    unsupported_events = cohorts["unsupported_true_source"]
    supported_events = [row for row in diagnostics if not row["source_has_unsupported"]]
    conclusion = {
        "unsupported_true_source_events": len(unsupported_events),
        "supported_true_source_events": len(supported_events),
        "ranking_regression_persists_on_supported_sources": bool(
            supported_events
            and (
                mean(supported_events, "rule_minus_v4_mrr") < -0.01
                or mean(supported_events, "learned_minus_v4_mrr") < -0.01
            )
        ),
        "parser_coverage_is_sufficient_explanation": bool(
            unsupported_events
            and len(unsupported_events) == len(diagnostics)
        ),
        "development_gate_passed": False,
        "promotion_allowed": False,
        "recommended_next_evidence": "run_locked_validation_as_diagnostic_not_as_rescue",
    }

    payload = {
        "protocol": "v5_core_enron_failure_diagnosis_v1",
        "post_hoc_label_aware_diagnostic": True,
        "does_not_modify_or_select_model": True,
        "summary_reconciled": summary_reconciled,
        "reconciliation_absolute_error": reconciliation,
        "cohorts": cohort_summary,
        "outcome_counts": outcome_counts,
        "largest_losses": largest_losses,
        "largest_wins": largest_wins,
        "conclusion": conclusion,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    write_csv(args.output / "event_diagnostics.csv", diagnostics)
    write_csv(args.output / "cohort_metrics.csv", cohort_rows)
    (args.output / "driver_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    all_values = cohort_summary["all_events"]
    supported = summarize(supported_events)
    report = [
        "# V5-Core Enron 失败机制诊断",
        "",
        "> 结论先行：Enron 安全门槛确实失败，当前 V5-Core 不能取代 V4。"
        "本报告是揭晓标签后的回顾性诊断，只解释失败，不参与模型训练、调参或选择。",
        "",
        "## 1. 总体结果",
        "",
        "| 方法 | Top-5 | MRR | EXAM |",
        "|---|---:|---:|---:|",
    ]
    for method, label in (("v4", "V4"), ("v5_rule", "V5-Core Rule"), ("v5_learned", "V5-Core Learned")):
        values = all_values[method]
        report.append(f"| {label} | {pct(values['top5'])} | {values['mrr']:.4f} | {values['exam']:.4f} |")
    report.extend([
        "",
        f"规则头相对 V4 的 MRR 差为 **{all_values['rule_minus_v4_mrr']:.4f}**；"
        f"学习头差为 **{all_values['learned_minus_v4_mrr']:.4f}**。两者都超过预登记允许的 -0.01 退化。",
        "",
        "## 2. 解析覆盖与主排序泛化",
        "",
        f"- 30 个事件中，真实源包含不支持语法的事件为 **{len(unsupported_events)}** 个；"
        f"真实源仍受支持的事件为 **{len(supported_events)}** 个。",
        f"- 7 个工作簿共出现 826 个不支持公式；兼容适配器只把这些公式放到完整排名尾部，"
        "没有改动冻结的 V5-Core 核心。",
        f"- 在真实源受支持的 {len(supported_events)} 个事件上，V4/Rule/Learned 的 MRR 分别为 "
        f"**{supported['v4']['mrr']:.4f} / {supported['v5_rule']['mrr']:.4f} / "
        f"{supported['v5_learned']['mrr']:.4f}**。",
        "",
    ])
    if conclusion["ranking_regression_persists_on_supported_sources"]:
        report.append(
            "因此，退化不能只归因于 Excel 语法覆盖；即便真实源公式可解析，"
            "候选中心证据在真实表格上的排序泛化仍然不足。"
        )
    else:
        report.append(
            "受支持真实源上的退化没有超过 0.01；当前证据更倾向于语法覆盖造成主要损失。"
        )
    report.extend([
        "",
        "## 3. 事件级升降",
        "",
        f"- 规则头：{outcome_counts['rule']['win']} 胜 / {outcome_counts['rule']['tie']} 平 / "
        f"{outcome_counts['rule']['loss']} 负。",
        f"- 学习头：{outcome_counts['learned']['win']} 胜 / {outcome_counts['learned']['tie']} 平 / "
        f"{outcome_counts['learned']['loss']} 负。",
        "",
        "最大退化事件如下（MRR 差为 V5-Core − V4）：",
        "",
        "| 头 | 事件 | V4名次 | V5名次 | MRR差 | 源公式不支持 |",
        "|---|---|---:|---:|---:|---:|",
    ])
    for head, label in (("rule", "Rule"), ("learned", "Learned")):
        for item in largest_losses[head][:5]:
            report.append(
                f"| {label} | {item['instance_id']} | {item['v4_rank']} | {item['v5_rank']} | "
                f"{item['mrr_delta']:.4f} | {'是' if item['source_has_unsupported'] else '否'} |"
            )
    report.extend([
        "",
        "## 4. 研究决策",
        "",
        "1. 不修改 V5-Core 权重、阈值或候选规则来迎合 Enron；Enron 已经是回顾性安全集。",
        "2. 当前开发审计保持失败，V5-Core 暂不允许取代 V4，也不生成成功冻结标签。",
        "3. 仍运行预先设计的 480 例锁定内部验证，但其定位为**独立诊断证据**，"
        "不是用来覆盖或‘救回’已经失败的 Enron 门槛。",
        "4. 若锁定验证明显优于 V4，则论文应同时报告‘合成泛化强、真实语料安全性不足’；"
        "若锁定验证也退化，则 V5-Core 作为有完整机制与负结果的核心重构保留。",
        "",
        "## 5. 可复算文件",
        "",
        "- `results/v5_core_development/enron_failure/event_diagnostics.csv`",
        "- `results/v5_core_development/enron_failure/cohort_metrics.csv`",
        "- `results/v5_core_development/enron_failure/driver_summary.json`",
    ])
    args.research_report.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(args.output / "driver_summary.json")
    print(args.research_report)


if __name__ == "__main__":
    main()
