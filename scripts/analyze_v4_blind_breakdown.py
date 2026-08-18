"""Produce preregistered error/depth breakdowns from locked blind scores."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summarize(
    scored: list[dict[str, str]], ledger: dict[str, dict[str, str]], field: str,
) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in scored:
        groups[(ledger[row["instance_id"]][field], row["method"])].append(row)
    rows: list[dict[str, object]] = []
    for (segment, method), values in sorted(groups.items()):
        rows.append({
            field: segment,
            "method": method,
            "events": len(values),
            "top1": statistics.fmean(float(row["top1"]) for row in values),
            "top3": statistics.fmean(float(row["top3"]) for row in values),
            "top5": statistics.fmean(float(row["top5"]) for row in values),
            "mrr": statistics.fmean(float(row["mrr"]) for row in values),
            "exam": statistics.fmean(float(row["exam"]) for row in values),
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze v4 blind scores by registered strata")
    parser.add_argument("--scored", type=Path, required=True)
    parser.add_argument("--rankings", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    scored = read_csv(args.scored)
    rankings = read_csv(args.rankings)
    ledger = {row["instance_id"]: row for row in read_csv(args.ledger)}
    if {row["instance_id"] for row in scored} != set(ledger):
        raise SystemExit("Scored events and evidence ledger IDs differ")
    args.output.mkdir(parents=True, exist_ok=True)
    by_error = summarize(scored, ledger, "error_type")
    by_depth = summarize(scored, ledger, "expected_depth")
    write_csv(args.output / "blind_by_error.csv", by_error)
    write_csv(args.output / "blind_by_depth.csv", by_depth)

    labels = {instance_id: row["source_cell"] for instance_id, row in ledger.items()}
    source_rows = [
        row for row in rankings
        if row["method"] == "formulaguard_v4" and row["cell"] == labels[row["instance_id"]]
    ]
    diagnostics: list[dict[str, object]] = []
    for row in sorted(source_rows, key=lambda item: item["instance_id"]):
        meta = ledger[row["instance_id"]]
        diagnostics.append({
            "instance_id": row["instance_id"],
            "error_type": meta["error_type"],
            "expected_depth": meta["expected_depth"],
            "source_cell": meta["source_cell"],
            "v4_rank": int(row["rank"]),
            "diagnostic_status": row["diagnostic_status"],
            "intervention_selected": row["intervention_selected"],
            "candidate_count": row["candidate_count"],
            "candidate_delta": row["candidate_delta"],
            "intervention_responsibility_gain": row["intervention_responsibility_gain"],
            "promotion_cap": row["promotion_cap"],
        })
    write_csv(args.output / "blind_v4_source_diagnostics.csv", diagnostics)
    status_counts: dict[str, int] = defaultdict(int)
    for row in diagnostics:
        status_counts[str(row["diagnostic_status"])] += 1
    payload = {
        "scope": "independent_synthetic_blind_set_after_prediction_lock",
        "events": len(ledger),
        "scored_rows": len(scored),
        "expected_scored_rows": len(ledger) * len({row["method"] for row in scored}),
        "v4_source_rows": len(diagnostics),
        "v4_source_status_counts": dict(sorted(status_counts.items())),
        "error_types": sorted({row["error_type"] for row in ledger.values()}),
        "expected_depths": sorted({row["expected_depth"] for row in ledger.values()}),
    }
    (args.output / "blind_breakdown_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(args.output / "blind_breakdown_audit.json")


if __name__ == "__main__":
    main()
