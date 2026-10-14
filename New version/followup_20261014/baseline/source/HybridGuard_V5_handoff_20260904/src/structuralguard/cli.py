from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .detector import DetectorConfig, analyze_workbook, save_json


def _write_csv(report: dict[str, object], path: Path) -> None:
    rows = list(report["results"])
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "rank", "sheet", "cell", "status", "structural_score", "raw_evidence_score",
        "empirical_tail_p", "bh_q_value", "local_role_support", "original_formula",
        "suggested_formula", "suggestion_source", "repair_consensus", "evidence",
        "automatic_edit_applied",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            output = {field: row.get(field) for field in fields}
            output["evidence"] = json.dumps(row.get("evidence", []), ensure_ascii=False)
            writer.writerow(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explainable structure-only Excel formula anomaly detection")
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("results") / "structuralguard")
    parser.add_argument("--exclude-sheet", action="append", default=[])
    parser.add_argument("--top-k", type=int, default=25)
    parser.add_argument("--local-radius", type=int, default=5)
    parser.add_argument("--review-score", type=float, default=0.55)
    parser.add_argument("--repair-score", type=float, default=0.72)
    parser.add_argument(
        "--disable-signal",
        action="append",
        default=[],
        choices=[
            "local_column_disagreement", "singleton_run_break", "hierarchical_role_rarity",
            "constant_signature_novelty", "dependency_topology_rarity", "row_disagreement",
            "block_disagreement", "hard_integrity_violation",
        ],
        help="disable one structural signal for an ablation run (repeatable)",
    )
    args = parser.parse_args(argv)
    config = DetectorConfig(
        local_radius=args.local_radius,
        review_score=args.review_score,
        repair_score=args.repair_score,
        disabled_signals=tuple(args.disable_signal),
    )
    report = analyze_workbook(args.workbook, exclude_sheets=args.exclude_sheet, config=config)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    save_json(report, args.output_dir / "report.json")
    _write_csv(report, args.output_dir / "formula_review.csv")
    summary = report["summary"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nTop candidates:")
    for row in list(report["results"])[: max(0, args.top_k)]:
        print(f"{row['rank']:>4} {row['structural_score']:.4f} {row['status']:<16} {row['sheet']}!{row['cell']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
