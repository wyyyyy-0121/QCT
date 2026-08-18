"""Paired, reproducible comparison of the initial v4 and the single v4-r1 revision."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.analyze_external_results import bootstrap_mean_difference


def _read(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _split_cells(value: str) -> set[str]:
    return {item for item in value.split(";") if item}


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare paired FormulaGuard v4 development revisions")
    parser.add_argument("--initial", type=Path, required=True)
    parser.add_argument("--revision", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    initial_rows = _read(args.initial)
    revision_rows = _read(args.revision)
    initial = {(row["instance_id"], row["method"]): row for row in initial_rows}
    revision = {(row["instance_id"], row["method"]): row for row in revision_rows}
    if set(initial) != set(revision):
        raise SystemExit("Initial and revision event-method matrices differ")
    unchanged_reference_errors = []
    for key in sorted(initial):
        if key[1] == "formulaguard_v4":
            continue
        if int(initial[key]["rank"]) != int(revision[key]["rank"]):
            unchanged_reference_errors.append({
                "instance_id": key[0], "method": key[1],
                "initial_rank": int(initial[key]["rank"]),
                "revision_rank": int(revision[key]["rank"]),
            })

    events = []
    mrr_differences = []
    rank_improvements = []
    evidence_precision = []
    for instance_id in sorted({key[0] for key in revision}):
        old = initial[(instance_id, "formulaguard_v4")]
        new = revision[(instance_id, "formulaguard_v4")]
        graph = revision[(instance_id, "graph")]
        mrr_difference = float(new["mrr"]) - float(old["mrr"])
        rank_improvement = int(old["rank"]) - int(new["rank"])
        mrr_differences.append(mrr_difference)
        rank_improvements.append(rank_improvement)
        strong = _split_cells(new.get("strong_cells", ""))
        sources = _split_cells(new.get("supported_source_cells", ""))
        strong_hits = strong & sources
        if strong:
            evidence_precision.append({
                "instance_id": instance_id,
                "strong_cells": len(strong),
                "strong_labeled_sources": len(strong_hits),
                "event_precision": len(strong_hits) / len(strong),
                "source_has_strong_evidence": new.get("diagnostic_status") == "strong_counterfactual",
            })
        events.append({
            "instance_id": instance_id,
            "formula_count": int(new["formula_count"]),
            "initial_rank": int(old["rank"]),
            "revision_rank": int(new["rank"]),
            "rank_improvement": rank_improvement,
            "graph_rank": int(graph["rank"]),
            "initial_status": old.get("diagnostic_status", ""),
            "revision_status": new.get("diagnostic_status", ""),
            "revision_base_rank": int(new.get("base_rank") or new["rank"]),
            "revision_selected": int(new.get("intervention_selected") or 0),
            "revision_strong_cell_count": int(new.get("strong_cell_count") or 0),
            "mrr_difference": mrr_difference,
        })
    old_v4 = [row for row in initial_rows if row["method"] == "formulaguard_v4"]
    new_v4 = [row for row in revision_rows if row["method"] == "formulaguard_v4"]
    by_workbook: dict[str, list[dict[str, str]]] = {}
    for row in new_v4:
        by_workbook.setdefault(row["workbook"], []).append(row)
    workbook_precision = []
    all_unique_strong: set[tuple[str, str]] = set()
    all_unique_hits: set[tuple[str, str]] = set()
    all_unique_sources: set[tuple[str, str]] = set()
    for workbook, rows in sorted(by_workbook.items()):
        strong = set().union(*(_split_cells(row.get("strong_cells", "")) for row in rows))
        sources = set().union(*(_split_cells(row.get("supported_source_cells", "")) for row in rows))
        hits = strong & sources
        all_unique_strong.update((workbook, cell) for cell in strong)
        all_unique_hits.update((workbook, cell) for cell in hits)
        all_unique_sources.update((workbook, cell) for cell in sources)
        if strong:
            workbook_precision.append({
                "workbook": workbook,
                "strong_cells": len(strong),
                "labeled_sources": len(sources),
                "strong_labeled_sources": len(hits),
                "precision": len(hits) / len(strong),
                "source_recall": len(hits) / len(sources) if sources else 0.0,
            })
    payload = {
        "scope": "retrospective_development_revision_not_confirmatory",
        "reference_rank_changes": unchanged_reference_errors,
        "comparison": {
            "events": len(events),
            "initial_mrr": statistics.fmean(float(row["mrr"]) for row in old_v4),
            "revision_mrr": statistics.fmean(float(row["mrr"]) for row in new_v4),
            "mean_mrr_difference": statistics.fmean(mrr_differences),
            "bootstrap_95_ci": bootstrap_mean_difference(mrr_differences),
            "better_events": sum(value > 0 for value in mrr_differences),
            "equal_events": sum(value == 0 for value in mrr_differences),
            "worse_events": sum(value < 0 for value in mrr_differences),
            "mean_rank_improvement": statistics.fmean(rank_improvements),
            "median_rank_improvement": statistics.median(rank_improvements),
            "initial_top1": statistics.fmean(float(row["top1"]) for row in old_v4),
            "revision_top1": statistics.fmean(float(row["top1"]) for row in new_v4),
            "initial_top5": statistics.fmean(float(row["top5"]) for row in old_v4),
            "revision_top5": statistics.fmean(float(row["top5"]) for row in new_v4),
        },
        "strong_evidence_event_precision": evidence_precision,
        "strong_evidence_workbook_precision": {
            "unique_strong_cells": len(all_unique_strong),
            "unique_strong_labeled_sources": len(all_unique_hits),
            "unique_labeled_sources": len(all_unique_sources),
            "precision": len(all_unique_hits) / len(all_unique_strong) if all_unique_strong else None,
            "source_recall": len(all_unique_hits) / len(all_unique_sources) if all_unique_sources else None,
            "workbooks_with_strong_cells": workbook_precision,
        },
        "strong_evidence_caveat": (
            "Precision is event-label overlap among strong cells in the same workbook output; "
            "events sharing a workbook are not independent precision samples."
        ),
        "events": events,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
