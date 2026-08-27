"""Command-line interface for diagnosing one workbook."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .api import localize
from .v5 import v5_scores
from .v4x import v4_1_scores
from .workbook import WorkbookModel


def build_parser():
    parser = argparse.ArgumentParser(description="Rank silent spreadsheet formula root causes")
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--method", default="formulaguard")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--candidate-limit", type=int, default=15)
    parser.add_argument("--head", choices=("rule", "learned"))
    parser.add_argument("--config", type=Path, help="Frozen FormulaGuard JSON configuration")
    parser.add_argument("--json", dest="json_path", type=Path)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    gir_weights = (0.35, 0.50, 0.10, 0.05)
    if args.config:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        args.candidate_limit = int(config["candidate_limit"])
        if "gir_weights" in config:
            gir_weights = tuple(float(value) for value in config["gir_weights"])
    model = WorkbookModel.from_xlsx(args.workbook)
    v5_core_methods = {
        "formulaguard_v5_core", "formulaguard_v5_core_rule", "v5_core", "v5_core_rule",
        "formulaguard_v5_core_learned", "v5_core_learned",
    }
    v6_methods = {
        "v6", "formulaguard_v6", "formulaguard_v6_a",
        "formulaguard_v6_b", "formulaguard_v6_c",
    }
    v43_methods = {
        "v4.3", "v4_3", "formulaguard_v4_3", "formulaguard_v4_3_a",
        "formulaguard_v4_3_b", "formulaguard_v4_3_c",
    }
    if args.method.lower() in v5_core_methods:
        # The historical --config format is passed through for V5-Core.  V5
        # chooses its own candidate default unless the user explicitly changed
        # the legacy CLI default.
        core_config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else None
        core_head = args.head or ("learned" if args.method.lower().endswith("learned") else "rule")
        results = localize(
            model,
            args.method,
            head=core_head,
            config=core_config,
            candidate_limit=32 if args.candidate_limit == 15 else args.candidate_limit,
        )
    else:
        results = (
        v4_1_scores(model, candidate_limit=args.candidate_limit)
        if args.method.lower() in {"formulaguard_v4_1", "v4_1", "v4.1"}
        else v5_scores(model, candidate_limit=args.candidate_limit)
        if args.method.lower() in {"formulaguard_v5", "v5"}
        else localize(
            model,
            args.method,
            candidate_limit=args.candidate_limit,
            **({} if args.method.lower() in v6_methods | v43_methods else {"gir_weights": gir_weights}),
        )
        )
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
