"""Evaluate preregistered V5 joint-confirmation alarms on clean workbooks."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.v5 import v5_default_parameters, v5_scores
from formulaguard.workbook import WorkbookModel
from scripts.run_external_evaluation import sha256_file


def evaluate_clean(task: tuple[str, dict[str, object], int]) -> dict[str, object]:
    benchmark_text, record, candidate_limit = task
    benchmark = Path(benchmark_text)
    workbook = (benchmark / str(record["path"])).resolve()
    if not workbook.is_file():
        raise FileNotFoundError(workbook)
    expected_hash = str(record.get("sha256", ""))
    actual_hash = sha256_file(workbook)
    if expected_hash and actual_hash != expected_hash:
        raise ValueError(f"Clean workbook hash mismatch: {workbook}")
    model = WorkbookModel.from_xlsx(workbook)
    results = v5_scores(model, candidate_limit=candidate_limit)
    joint = [result for result in results if int(result.evidence.get("joint_confirmed", 0))]
    joint_count = int(results[0].evidence.get("joint_candidate_count", 0)) if results else 0
    gate_active = int(results[0].evidence.get("joint_gate_active", 0)) if results else 0
    return {
        "clean_id": record["cleanId"],
        "family": record.get("family", ""),
        "topology_id": record.get("topology_id", ""),
        "formula_count": len(model.formulas),
        "manifest_formula_count": int(record.get("formula_count", 0)),
        "sha256": actual_hash,
        "joint_candidate_count": joint_count,
        "joint_gate_active": gate_active,
        "joint_confirmed_count": len(joint),
        "joint_confirmed_cells": ";".join(result.cell_label for result in joint),
        "alarm": int(bool(joint)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run V5 clean-workbook confirmation controls")
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-limit", type=int, default=15)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0, help="Engineering smoke only; 0 uses all")
    args = parser.parse_args()
    manifest_path = args.benchmark / "clean_manifest.json"
    records = json.loads(manifest_path.read_text(encoding="utf-8"))
    if args.limit:
        records = records[:args.limit]
    if not records:
        raise SystemExit("No clean workbooks registered")
    tasks = [(str(args.benchmark.resolve()), record, args.candidate_limit) for record in records]
    auto_workers = min(16, max(1, (os.cpu_count() or 2) // 2), len(tasks))
    workers = auto_workers if args.workers == 0 else max(1, min(args.workers, len(tasks)))
    rows: list[dict[str, object]] = []
    print(f"[scheduler] clean_workbooks={len(tasks)} workers={workers}", flush=True)
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(evaluate_clean, task) for task in tasks]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            row = future.result()
            rows.append(row)
            print(f"[{index}/{len(tasks)}] clean {row['clean_id']}", flush=True)
    rows.sort(key=lambda row: str(row["clean_id"]))
    args.output.mkdir(parents=True, exist_ok=True)
    csv_path = args.output / "v5_clean_controls.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    by_family: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        by_family[str(row["family"])].append(int(row["alarm"]))
    alarm_rate = statistics.fmean(int(row["alarm"]) for row in rows)
    summary = {
        "scope": "synthetic_clean_confirmation_control",
        "clean_workbooks": len(rows),
        "candidate_limit": args.candidate_limit,
        "worker_processes": workers,
        "engineering_limit": args.limit,
        "alarm_definition": "at_least_one_joint_confirmed_formula",
        "alarm_workbooks": sum(int(row["alarm"]) for row in rows),
        "alarm_rate": alarm_rate,
        "maximum_alarm_rate": 0.25,
        "target_alarm_rate": 0.20,
        "gate_passed": len(rows) == 48 and alarm_rate <= 0.25,
        "by_family_alarm_rate": {
            family: statistics.fmean(values) for family, values in sorted(by_family.items())
        },
        "v5_parameters": v5_default_parameters(),
        "manifest_sha256": sha256_file(manifest_path),
        "results_sha256": sha256_file(csv_path),
        "source_sha256": {
            "formulaguard/v5.py": sha256_file(
                Path(__file__).resolve().parents[1] / "formulaguard" / "v5.py"
            ),
            "formulaguard/localize.py": sha256_file(
                Path(__file__).resolve().parents[1] / "formulaguard" / "localize.py"
            ),
            "scripts/run_v5_clean_controls.py": sha256_file(Path(__file__).resolve()),
        },
        "warning": "Synthetic clean controls are not a production false-positive estimate.",
    }
    summary_path = args.output / "v5_clean_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary_path)


if __name__ == "__main__":
    main()
