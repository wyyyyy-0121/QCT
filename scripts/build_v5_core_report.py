"""Build compact Markdown and CSV evidence tables from V5-Core scoring JSON."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--title", default="FormulaGuard V5-Core experiment")
    args = parser.parse_args()
    payload = json.loads((args.results / "summary.json").read_text(encoding="utf-8"))
    summary_rows = []
    by_type_rows = []
    for method, metrics in sorted(payload["summary"].items()):
        summary_rows.append({
            "method": method,
            **{key: metrics[key] for key in (
                "events", "top1", "top3", "top5", "mrr", "exam",
                "macro_top5", "weakest_type_top5", "candidate_coverage_32", "exact_repair",
            )},
            "clean_false_alarm_rate": payload.get("clean", {}).get(method, {}).get("false_alarm_rate", ""),
        })
        for error_type, top5 in sorted(metrics.get("by_type_top5", {}).items()):
            by_type_rows.append({"method": method, "error_type": error_type, "top5": top5})
    with (args.results / "summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0])); writer.writeheader(); writer.writerows(summary_rows)
    with (args.results / "by_error.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["method", "error_type", "top5"]); writer.writeheader(); writer.writerows(by_type_rows)
    lines = [f"# {args.title}", "", "## Overall results", "", "| Method | Top-1 | Top-3 | Top-5 | MRR | Macro Top-5 | Repair | Clean FPR |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in summary_rows:
        clean = "—" if row["clean_false_alarm_rate"] == "" else f"{float(row['clean_false_alarm_rate']):.1%}"
        lines.append(
            f"| {row['method']} | {row['top1']:.1%} | {row['top3']:.1%} | {row['top5']:.1%} | "
            f"{row['mrr']:.4f} | {row['macro_top5']:.1%} | {row['exact_repair']:.1%} | {clean} |"
        )
    lines.extend(["", "## Evidence discipline", "", "- Prediction metadata records an empty label-read list.", "- Scoring opened labels only after the atomic prediction completion receipt.", "- Historical datasets are retrospective and are not used to select V5-Core.", "- Smoke and development results are diagnostic, not independent-paper conclusions.", ""])
    (args.results / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(args.results / "REPORT.md")


if __name__ == "__main__":
    main()
