"""Command-line interface for diagnosing one workbook."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .localize import localize
from .workbook import WorkbookModel


def build_parser():
    parser = argparse.ArgumentParser(description="Rank silent spreadsheet formula root causes")
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--method", default="formulaguard")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--candidate-limit", type=int, default=15)
    parser.add_argument("--config", type=Path, help="Frozen FormulaGuard JSON configuration")
    parser.add_argument("--json", dest="json_path", type=Path)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    gir_weights = (0.35, 0.50, 0.10, 0.05)
    if args.config:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        args.candidate_limit = int(config["candidate_limit"])
        gir_weights = tuple(float(value) for value in config["gir_weights"])
    model = WorkbookModel.from_xlsx(args.workbook)
    results = localize(model, args.method, candidate_limit=args.candidate_limit, gir_weights=gir_weights)
    graph = model.dependency_graph()
    formula_set = set(model.formula_cells)
    sinks = graph.sinks(model.formula_cells)
    payload = []
    for rank, result in enumerate(results[: args.top], 1):
        descendants = graph.descendants(result.cell)
        affected_formula_cells = sorted(descendants & formula_set)
        impact_paths = []
        for sink in sinks:
            path = graph.shortest_path(result.cell, sink)
            if path and len(path) > 1:
                impact_paths.append([f"{sheet}!{address}" for sheet, address in path])
            if len(impact_paths) >= 3:
                break
        row = {
            "rank": rank,
            "cell": result.cell_label,
            "formula": model.formulas[result.cell],
            "score": result.score,
            "candidate_formula": result.candidate_formula,
            "affected_formula_count": len(affected_formula_cells),
            "impact_paths": impact_paths,
            "evidence": result.evidence,
        }
        payload.append(row)
        path_text = " -> ".join(impact_paths[0]) if impact_paths else "-"
        print(f"{rank:>2}. {row['cell']:<24} score={row['score']:.8f} repair: {row['candidate_formula'] or '-'}")
        print(f"    affected={row['affected_formula_count']} impact={path_text}")
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
