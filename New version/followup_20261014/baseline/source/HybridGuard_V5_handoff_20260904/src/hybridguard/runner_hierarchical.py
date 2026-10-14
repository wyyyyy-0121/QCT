"""Run the fast hierarchical two-stage StructuralGuard/FormulaGuard pipeline."""

from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
from pathlib import Path

from formulaguard.workbook import WorkbookModel
from formulaguard.v5_structural_guard import v5_structural_guard_scores
from structuralguard.detector import analyze_workbook

from .hybrid import build_parallel_group_evidence, fuse_hierarchical
from .representative import validate_group_representatives
from .runner import _evaluate_model, _load_truth, _measure


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    keys = [
        "rank", "cell", "hybrid_score", "status", "structural_score",
        "group_id", "group_size", "group_score",
        "formulaguard_v5_score", "formulaguard_v5_rank",
        "representative_validation_score", "group_validated",
        "suggested_formula", "suggestion_source", "is_error", "error_kind",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in keys})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook", type=Path)
    parser.add_argument("truth", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    truth, truth_groups, parallel_sheets = _load_truth(args.truth)

    structural_report, structural_perf = _measure(lambda: analyze_workbook(args.workbook))
    model, load_perf = _measure(lambda: WorkbookModel.from_xlsx(args.workbook))
    formula_results, formula_perf = _measure(
        lambda: v5_structural_guard_scores(model)
    )
    formula_rows = []
    for rank, item in enumerate(formula_results, 1):
        formula_rows.append({
            "rank": rank,
            "cell": item.cell_label,
            "score": item.score,
            "candidate_formula": item.candidate_formula,
            "evidence": item.evidence,
        })
    formulas = {f"{sheet}!{cell}": formula for (sheet, cell), formula in model.formulas.items()}
    group_result, group_perf = _measure(
        lambda: build_parallel_group_evidence(formulas, parallel_sheets)
    )
    group_by_cell, detected_groups = group_result
    validation_result, validation_perf = _measure(
        lambda: validate_group_representatives(model, detected_groups, group_by_cell)
    )
    representatives, group_validations = validation_result
    hybrid_rows, fusion_perf = _measure(
        lambda: fuse_hierarchical(
            structural_report["results"], formula_rows, formulas,
            group_by_cell, group_validations
        )
    )

    for row in hybrid_rows:
        label = str(row["cell"])
        row["is_error"] = label in truth
        row["error_kind"] = truth.get(label, {}).get("kind")

    structural_rows = []
    for row in structural_report["results"]:
        item = dict(row)
        item["cell"] = f"{row['sheet']}!{row['cell']}"
        structural_rows.append(item)
    evaluations = [
        _evaluate_model("StructuralGuard", structural_rows, truth, truth_groups),
        _evaluate_model("FormulaGuard V5 structural-semantic guard", formula_rows, truth, truth_groups),
        _evaluate_model(
        "Hierarchical HybridGuard V5 (group representative validation)",
        hybrid_rows, truth, truth_groups),
    ]
    performance = {
        "StructuralGuard": structural_perf,
        "FormulaGuard workbook load": load_perf,
        "FormulaGuard V5 ranking": formula_perf,
        "cross-sheet group detection": group_perf,
        "FormulaGuard representative validation": validation_perf,
        "hierarchical fusion": fusion_perf,
    }
    result = {
        "protocol": "hierarchical_formulaguard_v5_validation_v3",
        "workbook": str(args.workbook.resolve()),
        "truth_file": str(args.truth.resolve()),
        "python": sys.version,
        "platform": platform.platform(),
        "representatives_checked": len(representatives),
        "groups_detected": len(detected_groups),
        "groups_validated": sum(item.accepted for item in group_validations.values()),
        "performance": performance,
        "evaluations": evaluations,
        "group_validations": [item.to_dict() for item in group_validations.values()],
        "representative_validations": [item.to_dict() for item in representatives],
        "limitations": [
            "FormulaGuard V5 supplies a workbook-wide structural-semantic rank and candidate formulas.",
            "Only group representatives pass through the additional bounded candidate-safety gate.",
            "Correctness evidence for systemic groups primarily comes from cross-sheet majority consensus.",
            "Synthetic parallel-sheet workbook; real-workbook generalization remains unproven.",
        ],
    }
    (args.output_dir / "hierarchical_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_rows(args.output_dir / "hierarchical_ranking.csv", hybrid_rows)
    with (args.output_dir / "representative_validations.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as stream:
        rows = [item.to_dict() for item in representatives]
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
