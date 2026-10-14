"""Label-aware retrospective audit of v4 base fusion rules (no interventions)."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.benchmark import parse_cell_label
from formulaguard.localize import (
    _competition_ranks,
    behavior_anomaly_scores,
    formula_anomaly_scores,
    graph_anomaly_scores,
    localize,
)
from formulaguard.workbook import WorkbookModel


def _sequential_ranks(cells, key):
    return {cell: rank for rank, cell in enumerate(sorted(cells, key=key), 1)}


def analyze_workbook(model: WorkbookModel) -> dict[str, dict[tuple[str, str], int]]:
    cells = list(model.formula_cells)
    formula = formula_anomaly_scores(model)
    raw_graph = graph_anomaly_scores(model)
    behavior = behavior_anomaly_scores(model)
    legacy = {
        cell: 0.45 * formula[cell] + 0.25 * raw_graph[cell] + 0.30 * behavior[cell]
        for cell in cells
    }
    formula_rank = _competition_ranks(formula)
    raw_graph_rank = _competition_ranks(raw_graph)
    legacy_rank = _competition_ranks(legacy)
    graph_results = localize(model, "graph")
    graph_rank = {result.cell: rank for rank, result in enumerate(graph_results, 1)}

    current_score = {
        cell: sum(1.0 / (60 + rank) for rank in (
            formula_rank[cell], raw_graph_rank[cell], legacy_rank[cell]
        ))
        for cell in cells
    }
    current_rank = _sequential_ranks(
        cells,
        lambda cell: (-current_score[cell], -raw_graph[cell], -formula[cell], -legacy[cell], cell),
    )
    unified_score = {
        cell: sum(1.0 / (60 + rank) for rank in (
            formula_rank[cell], graph_rank[cell], legacy_rank[cell]
        ))
        for cell in cells
    }
    unified_rank = _sequential_ranks(
        cells,
        lambda cell: (-unified_score[cell], graph_rank[cell], formula_rank[cell], legacy_rank[cell], cell),
    )
    safe_rank = _sequential_ranks(
        cells,
        lambda cell: (
            min(graph_rank[cell], unified_rank[cell]),
            graph_rank[cell] + unified_rank[cell],
            graph_rank[cell],
            unified_rank[cell],
            cell,
        ),
    )
    screening_rank = _sequential_ranks(
        cells,
        lambda cell: (
            min(current_rank[cell], safe_rank[cell]),
            current_rank[cell] + safe_rank[cell],
            safe_rank[cell],
            current_rank[cell],
            cell,
        ),
    )
    return {
        "graph": graph_rank,
        "current_rrf": current_rank,
        "unified_graph_rrf": unified_rank,
        "graph_safe_two_lane": safe_rank,
        "two_lane_screening": screening_rank,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit fixed v4 base-fusion alternatives")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [
            row for row in csv.DictReader(handle)
            if row.get("include", "1").strip().lower() not in {"0", "false", "no", "exclude"}
        ]
    grouped: dict[Path, list[dict[str, str]]] = {}
    for row in rows:
        workbook = (args.manifest.parent / row["workbook"]).resolve()
        grouped.setdefault(workbook, []).append(row)
    event_rows = []
    for index, (workbook, events) in enumerate(sorted(grouped.items()), 1):
        model = WorkbookModel.from_xlsx(workbook)
        ranks = analyze_workbook(model)
        for event in events:
            labels = [
                value.strip() for value in (
                    event.get("source_cells", "") or event.get("source_cell", "")
                ).split(";") if value.strip()
            ]
            sources = {parse_cell_label(label) for label in labels} & set(model.formula_cells)
            if not sources:
                continue
            item = {
                "instance_id": event["instance_id"],
                "formula_count": len(model.formula_cells),
            }
            for method, rank_map in ranks.items():
                item[method] = min(rank_map[source] for source in sources)
            event_rows.append(item)
        print(f"[{index}/{len(grouped)}] {workbook.name}", flush=True)

    summaries = {}
    for method in (
        "graph", "current_rrf", "unified_graph_rrf", "graph_safe_two_lane",
        "two_lane_screening",
    ):
        values = [int(row[method]) for row in event_rows]
        summaries[method] = {
            "events": len(values),
            "top1": sum(rank <= 1 for rank in values) / len(values),
            "top5": sum(rank <= 5 for rank in values) / len(values),
            "mrr": statistics.fmean(1.0 / rank for rank in values),
            "selected_at_100": sum(rank <= 100 for rank in values),
            "severe_drop_gt20_vs_graph": sum(
                int(row[method]) - int(row["graph"]) > 20 for row in event_rows
            ),
        }
    payload = {
        "scope": "retrospective_development_diagnostic_not_confirmatory",
        "rules": {
            "current_rrf": "formula + raw graph anomaly + legacy prior",
            "unified_graph_rrf": "formula + full graph review rank + legacy prior",
            "graph_safe_two_lane": "best rank from full graph and unified RRF; sum then graph as tie-breaks",
            "two_lane_screening": "best rank from old consensus and graph-safe base within one fixed budget",
        },
        "summary": summaries,
        "events": event_rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
