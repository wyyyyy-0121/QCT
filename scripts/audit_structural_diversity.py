from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.workbook import WorkbookModel


def structural_metrics(workbook_path: Path) -> dict:
    model = WorkbookModel.from_xlsx(workbook_path)
    graph = model.dependency_graph()
    formula_cells = set(model.formula_cells)
    all_sheets = {sheet for sheet, _ in set(model.cells) | set(model.formulas)}
    auxiliary_sheets = {"Checks", "Params", "Control", "Reference"}
    core_sheets = {sheet for sheet in all_sheets if sheet not in auxiliary_sheets}
    core_formula_cells = {cell for cell in formula_cells if cell[0] in core_sheets}
    formula_edges = []
    core_formula_edges = []
    all_edges = []
    for target in formula_cells:
        for source in graph.precedents.get(target, set()):
            all_edges.append((source, target))
            if source in formula_cells:
                formula_edges.append((source, target))
                if source in core_formula_cells and target in core_formula_cells:
                    core_formula_edges.append((source, target))
    sinks = graph.sinks(formula_cells)
    depths = [graph.shortest_sink_depth(cell, formula_cells) for cell in formula_cells]
    finite_depths = [depth for depth in depths if depth is not None]
    sheet_formula_counts: dict[str, int] = {}
    for sheet, _ in formula_cells:
        sheet_formula_counts[sheet] = sheet_formula_counts.get(sheet, 0) + 1
    indegrees = sorted(sum(1 for source, target in formula_edges if target == cell) for cell in formula_cells)
    outdegrees = sorted(sum(1 for source, target in formula_edges if source == cell) for cell in formula_cells)
    signature_payload = {
        "workbook_sheet_count": len(all_sheets),
        "core_sheet_count": len(core_sheets),
        "sheet_formula_counts": sorted(sheet_formula_counts.values()),
        "formula_count": len(formula_cells),
        "formula_edge_count": len(formula_edges),
        "all_dependency_edges": len(all_edges),
        "cross_sheet_formula_edges": sum(1 for source, target in formula_edges if source[0] != target[0]),
        "core_cross_sheet_formula_edges": sum(1 for source, target in core_formula_edges if source[0] != target[0]),
        "sink_count": len(sinks),
        "max_sink_depth": max(finite_depths, default=0),
        "indegree_sequence": indegrees,
        "outdegree_sequence": outdegrees,
    }
    signature = hashlib.sha256(
        json.dumps(signature_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "sheet_count": len(all_sheets),
        "formula_sheet_count": len(sheet_formula_counts),
        "core_sheet_count": len(core_sheets),
        **signature_payload,
        "structural_signature": signature,
    }


def audit(benchmark: Path) -> dict:
    manifest = json.loads((benchmark / "dataset_manifest.json").read_text(encoding="utf-8"))
    clean_records = json.loads((benchmark / "clean_manifest.json").read_text(encoding="utf-8"))
    first_by_family = {}
    for record in clean_records:
        first_by_family.setdefault(record["family"], record)
    profiles = []
    for family in manifest["template_families"]:
        record = first_by_family[family]
        metrics = structural_metrics(benchmark / record["path"])
        profiles.append({
            "family": family,
            "declared_topology": record.get("topology_id", ""),
            "workbook": record["path"],
            **metrics,
        })
    declared = [profile["declared_topology"] for profile in profiles]
    signatures = [profile["structural_signature"] for profile in profiles]
    checks = {
        "one_profile_per_family": len(profiles) == len(manifest["template_families"]),
        "declared_topologies_all_distinct": len(set(declared)) == len(declared),
        "calculated_signatures_all_distinct": len(set(signatures)) == len(signatures),
        "contains_single_sheet_layout": any(profile["core_sheet_count"] == 1 for profile in profiles),
        "contains_multi_sheet_layout": any(profile["core_sheet_count"] > 1 for profile in profiles),
        "contains_cross_sheet_dependencies": any(profile["core_cross_sheet_formula_edges"] > 0 for profile in profiles),
        "contains_non_cross_sheet_dependencies": any(profile["core_cross_sheet_formula_edges"] == 0 for profile in profiles),
    }
    return {
        "benchmark": str(benchmark),
        "benchmark_name": manifest.get("name"),
        "mode": manifest.get("mode"),
        "families": len(profiles),
        "unique_declared_topologies": len(set(declared)),
        "unique_calculated_signatures": len(set(signatures)),
        "checks": checks,
        "passed": all(checks.values()),
        "profiles": profiles,
        "interpretation": "Distinct labels alone are insufficient; signatures are recalculated from workbook dependency graphs.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit actual dependency-graph diversity in PropagationBench V2")
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    result = audit(args.benchmark)
    output = args.output or args.benchmark / "validation" / "structural_diversity.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.strict and not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
