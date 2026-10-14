"""Verify a blind prediction lock, then reveal labels and score all methods."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.benchmark import parse_cell_label
from scripts.analyze_external_results import bootstrap_mean_difference
from scripts.run_external_evaluation import sha256_file


def verify_prediction_lock(lock_path: Path) -> tuple[Path, Path, dict[str, object]]:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    rankings = lock_path.parent / str(lock["rankings_file"])
    metadata = lock_path.parent / str(lock["metadata_file"])
    if sha256_file(rankings) != lock["rankings_sha256"]:
        raise ValueError("Blind rankings hash mismatch; predictions changed after freezing")
    if sha256_file(metadata) != lock["metadata_sha256"]:
        raise ValueError("Blind metadata hash mismatch; run context changed after freezing")
    return rankings, metadata, lock


def parse_sources(row: dict[str, str]) -> set[str]:
    raw = row.get("source_cells", "") or row.get("source_cell", "")
    sources = set()
    for value in raw.split(";"):
        if not value.strip():
            continue
        sheet, address = parse_cell_label(value.strip())
        sources.add(f"{sheet}!{address.upper()}")
    if not sources:
        raise ValueError(f"No source label for instance {row.get('instance_id', '')}")
    return sources


def score_rankings(
    ranking_rows: list[dict[str, str]], label_rows: list[dict[str, str]]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    by_key: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in ranking_rows:
        by_key[(row["instance_id"], row["method"])].append(row)
    label_ids = [row.get("instance_id", "") for row in label_rows]
    if any(not value for value in label_ids) or len(label_ids) != len(set(label_ids)):
        raise ValueError("Label instance_id values must be non-empty and unique")
    labels = {row["instance_id"]: parse_sources(row) for row in label_rows}
    prediction_ids = {key[0] for key in by_key}
    if prediction_ids != set(labels):
        raise ValueError("Prediction and label instance_id sets differ")

    scored: list[dict[str, object]] = []
    for (instance_id, method), rows in sorted(by_key.items()):
        rows.sort(key=lambda row: int(row["rank"]))
        total = int(rows[0]["formula_count"])
        ranks = [int(row["rank"]) for row in rows]
        cells = [row["cell"] for row in rows]
        if ranks != list(range(1, total + 1)) or len(cells) != len(set(cells)):
            raise ValueError(f"Incomplete or duplicate ranking for {instance_id}/{method}")
        if any(int(row["formula_count"]) != total for row in rows):
            raise ValueError(f"Inconsistent formula_count for {instance_id}/{method}")
        matching = [int(row["rank"]) for row in rows if row["cell"] in labels[instance_id]]
        rank = min(matching, default=total + 1)
        scored.append({
            "instance_id": instance_id,
            "method": method,
            "formula_count": total,
            "rank": rank,
            "top1": int(rank <= 1),
            "top3": int(rank <= 3),
            "top5": int(rank <= 5),
            "mrr": 1.0 / rank,
            "exam": rank / max(1, total),
            "source_found_in_ranking": int(bool(matching)),
        })
    summaries = []
    methods = sorted({row["method"] for row in scored})
    for method in methods:
        group = [row for row in scored if row["method"] == method]
        summaries.append({
            "method": method,
            "events": len(group),
            "top1": statistics.fmean(float(row["top1"]) for row in group),
            "top3": statistics.fmean(float(row["top3"]) for row in group),
            "top5": statistics.fmean(float(row["top5"]) for row in group),
            "mrr": statistics.fmean(float(row["mrr"]) for row in group),
            "exam": statistics.fmean(float(row["exam"]) for row in group),
        })
    return scored, summaries


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score hash-locked v4 blind predictions")
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty blind score directory: {args.output}")
    try:
        rankings_path, metadata_path, lock = verify_prediction_lock(args.lock)
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Prediction lock verification failed: {exc}") from exc

    with rankings_path.open("r", encoding="utf-8-sig", newline="") as handle:
        ranking_rows = list(csv.DictReader(handle))
    with args.labels.open("r", encoding="utf-8-sig", newline="") as handle:
        label_rows = list(csv.DictReader(handle))
    scored, summaries = score_rankings(ranking_rows, label_rows)
    args.output.mkdir(parents=True, exist_ok=True)
    _write_csv(args.output / "blind_scored_events.csv", scored)
    _write_csv(args.output / "blind_summary.csv", summaries)

    by_instance: dict[str, dict[str, float]] = defaultdict(dict)
    for row in scored:
        by_instance[str(row["instance_id"])][str(row["method"])] = float(row["mrr"])
    comparisons = {}
    for reference in ("graph", "pattern", "formulaguard", "formulaguard_v3"):
        differences = [
            methods["formulaguard_v4"] - methods[reference]
            for methods in by_instance.values()
            if "formulaguard_v4" in methods and reference in methods
        ]
        comparisons[f"v4_minus_{reference}"] = {
            "events": len(differences),
            "mean_mrr_difference": statistics.fmean(differences) if differences else None,
            "bootstrap_95_ci": bootstrap_mean_difference(differences),
            "better_events": sum(value > 0 for value in differences),
            "equal_events": sum(value == 0 for value in differences),
            "worse_events": sum(value < 0 for value in differences),
        }
    report = {
        "prediction_lock_verified": True,
        "prediction_lock": lock,
        "prediction_metadata_sha256": sha256_file(metadata_path),
        "labels_file": str(args.labels.resolve()),
        "labels_sha256": sha256_file(args.labels),
        "events": len(label_rows),
        "quantitative_claim_limit": (
            "Exploratory case study only" if len(label_rows) < 15 else "Quantitative reporting permitted"
        ),
        "paired_comparisons": comparisons,
    }
    (args.output / "blind_score_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(args.output / "blind_score_report.json")


if __name__ == "__main__":
    main()
