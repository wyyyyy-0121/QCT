from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.benchmark import load_jsonl, parse_cell_label
from formulaguard.localize import localize
from formulaguard.workbook import WorkbookModel


def label(key):
    return f"{key[0]}!{key[1]}"


def main():
    parser = argparse.ArgumentParser(description="Create a reproducible 3-minute FormulaGuard demonstration case")
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--instance-id")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--model-version", choices=("v2", "v3"), default="v2")
    args = parser.parse_args()
    validation = args.benchmark / "validation" / "validated_instances.jsonl"
    instances = list(load_jsonl(validation))
    if not instances:
        raise SystemExit(f"No validated instances found in: {validation}")
    if args.instance_id:
        selected = next((row for row in instances if row["instance_id"] == args.instance_id), None)
        if selected is None:
            raise SystemExit(f"Unknown instance id: {args.instance_id}")
    else:
        selected = next((row for row in instances if row.get("depth_bin") == "deep"), instances[0])

    workbook_path = args.benchmark / selected["mutant_workbook"]
    model = WorkbookModel.from_xlsx(workbook_path)
    graph = model.dependency_graph()
    ranking = localize(model, "formulaguard_v3" if args.model_version == "v3" else "formulaguard")
    source = parse_cell_label(selected["source_cell"])
    source_rank = next((index for index, result in enumerate(ranking, 1) if result.cell == source), len(ranking) + 1)
    top_rows = []
    sinks = graph.sinks(model.formula_cells)
    for index, result in enumerate(ranking[: args.top], 1):
        paths = []
        for sink in sinks:
            path = graph.shortest_path(result.cell, sink)
            if path and len(path) > 1:
                paths.append([label(key) for key in path])
            if len(paths) >= 2:
                break
        top_rows.append({
            "rank": index,
            "cell": result.cell_label,
            "formula": model.formulas[result.cell],
            "score": result.score,
            "candidate_formula": result.candidate_formula,
            "affected_formula_count": len(graph.descendants(result.cell) & set(model.formula_cells)),
            "impact_paths": paths,
        })
    payload = {
        "instance_id": selected["instance_id"],
        "workbook": str(workbook_path),
        "formula_count": len(model.formulas),
        "known_source_for_evaluation_only": selected["source_cell"],
        "source_rank": source_rank,
        "correct_formula_for_evaluation_only": selected["correct_formula"],
        "mutated_formula": selected["mutated_formula"],
        "top_results": top_rows,
        "truth_isolation_note": "The source and correct formula were read only after the oracle-free ranking was produced.",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "demo_case.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# FormulaGuard 三分钟演示案例",
        "",
        f"- 实例：`{selected['instance_id']}`",
        f"- 公式数：{len(model.formulas)}",
        f"- 源错误真实排名：{source_rank}",
        "- 排名阶段没有读取源错误或正确公式；真值只在排名完成后用于展示评价。",
        "",
        "| 排名 | 单元格 | 当前公式 | 候选修复 | 受影响公式数 |",
        "|---:|---|---|---|---:|",
    ]
    for row in top_rows:
        lines.append(f"| {row['rank']} | {row['cell']} | `{row['formula']}` | `{row['candidate_formula'] or '-'}` | {row['affected_formula_count']} |")
    lines += ["", "详细影响路径见 `demo_case.json`。", ""]
    (args.output / "demo_case.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
