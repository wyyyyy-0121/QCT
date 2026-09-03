"""Score already-frozen blind predictions only after an independent label file is unsealed."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.benchmark import parse_cell_label
from formulaguard.formula import normalized_formula


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def cell_key(sheet: str, address: str) -> tuple[str, str]:
    return sheet, address.replace("$", "").upper()


def source_keys(row: dict[str, str]) -> set[tuple[str, str]]:
    raw = row.get("source_cells", "") or row.get("source_cell", "")
    return {cell_key(*parse_cell_label(item.strip())) for item in raw.split(";") if item.strip()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit private labels against immutable unlabeled blind predictions")
    parser.add_argument("--predictions", type=Path, required=True, help="Directory produced by run_unlabeled_blind.py")
    parser.add_argument("--labels", type=Path, required=True, help="Private CSV: instance_id,source_cell[,correct_formula]")
    parser.add_argument("--negative-labels", type=Path, help="Optional private CSV: instance_id,correct_exception_cell[,rationale]")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prediction_path = args.predictions / "predictions.csv"
    freeze_path = args.predictions / "prediction_manifest.json"
    if not prediction_path.is_file() or not freeze_path.is_file():
        raise SystemExit("Predictions directory must contain predictions.csv and prediction_manifest.json")
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if freeze.get("predictions_sha256") != sha256(prediction_path):
        raise SystemExit("predictions.csv hash differs from its frozen prediction manifest; refuse post-hoc scoring")
    with args.labels.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        labels = list(reader)
        fields = set(reader.fieldnames or [])
    if not labels or "instance_id" not in fields or not ({"source_cell", "source_cells"} & fields):
        raise SystemExit("Private labels must contain instance_id and source_cell or source_cells")
    if len({row["instance_id"] for row in labels}) != len(labels):
        raise SystemExit("Private labels have duplicate instance_id values")
    with prediction_path.open("r", encoding="utf-8-sig", newline="") as handle:
        predictions = list(csv.DictReader(handle))
    indexed: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in predictions:
        indexed.setdefault((row["instance_id"], row["method"]), []).append(row)
    for rows in indexed.values():
        rows.sort(key=lambda row: int(row["rank"]))
    detailed: list[dict[str, Any]] = []
    for label in labels:
        sources = source_keys(label)
        for method in freeze["methods"]:
            ranked = indexed.get((label["instance_id"], method), [])
            hits = [row for row in ranked if cell_key(row["sheet"], row["address"]) in sources]
            if not hits:
                continue
            hit = min(hits, key=lambda row: int(row["rank"]))
            correct = label.get("correct_formula", "")
            candidate = hit.get("candidate_formula", "")
            detailed.append({
                "instance_id": label["instance_id"], "method": method,
                "formula_count": int(hit["formula_count"]), "rank": int(hit["rank"]),
                "top1": int(int(hit["rank"]) <= 1), "top5": int(int(hit["rank"]) <= 5),
                "mrr": 1 / int(hit["rank"]), "exam": int(hit["rank"]) / max(1, int(hit["formula_count"])),
                "source_cell": ";".join(f"{sheet}!{address}" for sheet, address in sorted(sources)),
                "candidate_formula": candidate,
                "repair_evaluable": int(bool(correct)),
                "repair_exact": int(bool(correct and candidate and normalized_formula(correct) == normalized_formula(candidate))),
            })
    if not detailed:
        raise SystemExit("No private labels matched frozen predictions")
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "blind_detail.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(detailed[0]))
        writer.writeheader()
        writer.writerows(detailed)
    summary: list[dict[str, Any]] = []
    for method in freeze["methods"]:
        group = [row for row in detailed if row["method"] == method]
        if not group:
            continue
        evaluable = [row for row in group if row["repair_evaluable"]]
        summary.append({
            "method": method, "instances": len(group), "top1": statistics.fmean(row["top1"] for row in group),
            "top5": statistics.fmean(row["top5"] for row in group), "mrr": statistics.fmean(row["mrr"] for row in group),
            "exam": statistics.fmean(row["exam"] for row in group), "repair_evaluable": len(evaluable),
            "repair_exact": statistics.fmean(row["repair_exact"] for row in evaluable) if evaluable else "",
        })
    with (args.output / "blind_summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    negative_rows: list[dict[str, Any]] = []
    if args.negative_labels:
        with args.negative_labels.open("r", encoding="utf-8-sig", newline="") as handle:
            negatives = list(csv.DictReader(handle))
        for negative in negatives:
            key = cell_key(*parse_cell_label(negative["correct_exception_cell"]))
            for method in freeze["methods"]:
                ranked = indexed.get((negative["instance_id"], method), [])
                hit = next((row for row in ranked if cell_key(row["sheet"], row["address"]) == key), None)
                if hit:
                    negative_rows.append({"instance_id": negative["instance_id"], "method": method, "correct_exception_cell": negative["correct_exception_cell"], "rank": int(hit["rank"]), "top5_review_exposure": int(int(hit["rank"]) <= 5), "rationale": negative.get("rationale", "")})
        if negative_rows:
            with (args.output / "negative_exposure.csv").open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(negative_rows[0]))
                writer.writeheader()
                writer.writerows(negative_rows)
    payload = {
        "schema_version": 1, "generated_at": datetime.now(UTC).isoformat(),
        "prediction_manifest_sha256": sha256(freeze_path), "predictions_sha256": sha256(prediction_path),
        "private_labels_sha256": sha256(args.labels), "instances_scored": len({row["instance_id"] for row in detailed}),
        "methods": freeze["methods"], "negative_exception_rows": len(negative_rows),
        "reporting_rule": "This is a small independent blind case study. Do not combine it with Enron or synthetic metrics, and preserve every case.",
    }
    (args.output / "blind_audit.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
