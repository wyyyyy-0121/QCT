"""Read-only post-hoc audit of the already revealed 100-case V4 result."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def rows(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def mean(values):
    return sum(values) / len(values) if values else 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, default=Path(r"D:\FormulaGuard_Blind_Labels_100\v4_v52_labels.csv"))
    parser.add_argument("--events", type=Path, default=Path("results/v4_v52_independent_100_scored/independent_scored_events.csv"))
    parser.add_argument("--rankings", type=Path, default=Path("results/v4_v52_independent_100_locked/v4_full_rankings.csv"))
    parser.add_argument("--output", type=Path, default=Path("results/v6_hypothesis_audit"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    labels = {row["instance_id"]: row for row in rows(args.labels)}
    events = {row["instance_id"]: row for row in rows(args.events)}
    rankings = rows(args.rankings)
    source_rows = {}
    for row in rankings:
        label = labels.get(row["instance_id"])
        if label and row["cell"] == label["source_cell"]:
            source_rows[row["instance_id"]] = row

    detail = []
    grouped = defaultdict(list)
    for instance_id, label in labels.items():
        event = events[instance_id]
        rank = int(event["v4_rank"])
        evidence = source_rows.get(instance_id, {})
        row = {
            "instance_id": instance_id,
            "cohort": event["evidence_cohort"],
            "error_type": label["error_type"],
            "source_cell": label["source_cell"],
            "formula_count": int(event["formula_count"]),
            "v4_rank": rank,
            "top5": int(rank <= 5),
            "candidate_formula": evidence.get("candidate_formula", ""),
            "diagnostic_status": evidence.get("diagnostic_status", ""),
            "candidate_delta": evidence.get("candidate_delta", ""),
            "irg": evidence.get("intervention_responsibility_gain", ""),
            "candidate_support": evidence.get("candidate_support", ""),
            "candidate_source": evidence.get("candidate_source", ""),
            "historical_only": 1,
        }
        detail.append(row)
        grouped[label["error_type"]].append(row)

    summary = []
    for error_type, items in sorted(grouped.items()):
        cohort = [row for row in items if row["cohort"] == "new_independent"]
        target = cohort or items
        summary.append({
            "error_type": error_type,
            "events": len(target),
            "top5": mean([row["top5"] for row in target]),
            "mrr": mean([1 / row["v4_rank"] for row in target]),
            "median_rank": sorted(row["v4_rank"] for row in target)[len(target) // 2],
            "scope": "new_85" if cohort else "all_100",
        })

    with (args.output / "v6_failure_details.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(detail[0]))
        writer.writeheader(); writer.writerows(detail)
    with (args.output / "v6_failure_by_type.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader(); writer.writerows(summary)
    payload = {
        "protocol": "v6_posthoc_failure_hypothesis_audit",
        "not_for_v6_model_selection": True,
        "revealed_events": len(detail),
        "new_independent_events": sum(row["cohort"] == "new_independent" for row in detail),
        "by_error_type": summary,
        "hypothesis": "formula-family and range-boundary semantics may address repeated V4 failures",
        "claim_boundary": "These labels motivated V6 but cannot validate or tune V6.",
    }
    (args.output / "v6_failure_hypothesis.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output / "v6_failure_hypothesis.json")


if __name__ == "__main__":
    main()
