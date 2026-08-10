from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


EXPECTED_METHODS = {
    "random", "excel_like", "pattern", "graph", "behavior",
    "excelint_like", "warder_like", "formulaguard", "sfl_oracle",
    "ablate_formula", "ablate_graph", "ablate_behavior",
    "ablate_influence", "ablate_intervention",
}


def load_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser(description="Audit whether an experiment folder is complete enough for paper drafting")
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true", help="Exit nonzero when evidence is incomplete")
    args = parser.parse_args()
    output = args.output or args.results / "completion_audit.json"
    required = [
        args.benchmark / "dataset_manifest.json",
        args.benchmark / "instances.jsonl",
        args.benchmark / "evaluation_labels.jsonl",
        args.benchmark / "validation" / "dataset_quality.json",
        args.results / "raw_results.csv",
        args.results / "summary.csv",
        args.results / "by_depth.csv",
        args.results / "by_error.csv",
        args.results / "by_family.csv",
        args.results / "by_split.csv",
        args.results / "paired_comparison.json",
        args.results / "clean_summary.json",
        args.results / "failure_cases.csv",
        args.results / "REPORT.md",
        args.results / "environment.json",
        args.results / "figures" / "main_mrr.svg",
        args.results / "figures" / "main_top5.svg",
        args.results / "figures" / "by_depth_mrr.svg",
        args.results / "figures" / "by_error_mrr.svg",
        args.results / "demo" / "demo_case.json",
        args.results / "pipeline.log",
        args.results / "results_workbook_formula_errors.ndjson",
    ]
    missing_files = [str(path) for path in required if not path.is_file()]
    checks = {}
    details = {}
    if not missing_files:
        manifest = json.loads((args.benchmark / "dataset_manifest.json").read_text(encoding="utf-8"))
        environment = json.loads((args.results / "environment.json").read_text(encoding="utf-8"))
        quality = json.loads((args.benchmark / "validation" / "dataset_quality.json").read_text(encoding="utf-8"))
        summary = load_csv(args.results / "summary.csv")
        raw = load_csv(args.results / "raw_results.csv")
        methods = {row["method"] for row in summary}
        mutation_types = {row["mutation_type"] for row in raw}
        depths = {row["depth_bin"] for row in raw}
        splits = {row.get("data_split", "") for row in raw}
        mode = manifest.get("mode", "unknown")
        minimum_instances = {"smoke": 12, "quick": 48, "full": 800}.get(mode, 1)
        expected_splits = {
            "smoke": {"development"},
            "quick": {"development", "validation"},
            "full": {"test"},
        }.get(mode, set())
        workbook_scan = [
            json.loads(line)
            for line in (args.results / "results_workbook_formula_errors.ndjson").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        checks = {
            "validation_rate_at_least_95_percent": quality["valid_rate"] >= 0.95,
            "all_six_mutation_types_present": len(mutation_types) >= 6,
            "all_three_depth_bins_present": {"shallow", "medium", "deep"}.issubset(depths),
            "all_core_methods_present": EXPECTED_METHODS.issubset(methods),
            "raw_results_nonempty": bool(raw),
            "labels_physically_separated": (args.benchmark / "evaluation_labels.jsonl").is_file(),
            "mode_instance_target_met": quality["valid"] >= minimum_instances,
            "expected_template_splits_only": not expected_splits or splits == expected_splits,
            "git_commit_recorded": bool(environment.get("git_commit")) and not str(environment["git_commit"]).startswith("unavailable:"),
            "result_workbook_has_no_formula_errors": not any(row.get("kind") == "match" for row in workbook_scan),
        }
        details = {
            "valid_instances": quality["valid"],
            "valid_rate": quality["valid_rate"],
            "mutation_types": sorted(mutation_types),
            "depth_bins": sorted(depths),
            "methods": sorted(methods),
            "data_splits": sorted(splits),
            "benchmark_mode": mode,
            "minimum_instances_for_mode": minimum_instances,
            "git_commit": environment.get("git_commit", ""),
        }
    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_complete": not missing_files and all(checks.values()),
        "missing_files": missing_files,
        "checks": checks,
        "details": details,
        "interpretation": "Evidence completeness is not the same as FormulaGuard outperforming the baselines.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = output.with_suffix(".md")
    lines = ["# FormulaGuard 实验完成度审计", "", f"- 证据链完整：{audit['evidence_complete']}"]
    if missing_files:
        lines += ["- 缺失文件："] + [f"  - `{path}`" for path in missing_files]
    else:
        lines += [f"- {name}：{value}" for name, value in checks.items()]
    lines += ["", "> 完成度通过只说明材料齐全，不说明算法已经优于基线。", ""]
    markdown.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    if args.strict and not audit["evidence_complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
