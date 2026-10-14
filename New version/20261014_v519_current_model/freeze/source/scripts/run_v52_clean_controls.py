"""Measure V5.2 rescue activation on the 48 registered clean workbooks."""

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

from formulaguard.v52 import v52_default_parameters, v52_scores
from formulaguard.workbook import WorkbookModel
from scripts.run_external_evaluation import sha256_file


def _evaluate(task: tuple[str, dict[str, object], str, int]) -> dict[str, object]:
    benchmark_text, record, variant, candidate_limit = task
    benchmark = Path(benchmark_text)
    workbook = (benchmark / str(record["path"])).resolve()
    expected_hash = str(record.get("sha256", ""))
    actual_hash = sha256_file(workbook)
    if expected_hash and actual_hash != expected_hash:
        raise ValueError(f"Clean workbook hash mismatch: {workbook}")
    model = WorkbookModel.from_xlsx(workbook)
    decision = v52_scores(model, variant=variant, candidate_limit=candidate_limit)
    rescue = decision.rescue
    return {
        "clean_id": record["cleanId"],
        "family": record.get("family", ""),
        "topology_id": record.get("topology_id", ""),
        "formula_count": len(decision.core_ranking),
        "sha256": actual_hash,
        "variant": variant,
        "core_top5_cells": ";".join(item.cell_label for item in decision.core_top5),
        "eligible_candidate_count": len(decision.eligible),
        "rescue_status": decision.status,
        "rescue_reason": decision.reason,
        "rescue_cell": rescue.result.cell_label if rescue else "",
        "rescue_alarm": int(rescue is not None),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run V5.2 clean controls")
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", choices=("a", "b", "c"), required=True)
    parser.add_argument("--candidate-limit", type=int, default=15)
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    manifest = args.benchmark / "clean_manifest.json"
    records = json.loads(manifest.read_text(encoding="utf-8"))
    if args.limit:
        records = records[:args.limit]
    if not records:
        raise SystemExit("No clean controls registered")
    tasks = [
        (str(args.benchmark.resolve()), record, args.variant, args.candidate_limit)
        for record in records
    ]
    workers = max(1, min(args.workers or min(24, os.cpu_count() or 1), len(tasks)))
    rows: list[dict[str, object]] = []
    print(f"[scheduler] clean={len(tasks)} variant={args.variant} workers={workers}", flush=True)
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_evaluate, task) for task in tasks]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            row = future.result()
            rows.append(row)
            print(f"[{index}/{len(tasks)}] clean {row['clean_id']}", flush=True)
    rows.sort(key=lambda row: str(row["clean_id"]))
    args.output.mkdir(parents=True, exist_ok=True)
    raw_path = args.output / "v52_clean_controls.csv"
    with raw_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    by_family: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        by_family[str(row["family"])].append(int(row["rescue_alarm"]))
    alarm_rate = statistics.fmean(int(row["rescue_alarm"]) for row in rows)
    summary = {
        "scope": "synthetic_clean_v52_rescue_control",
        "variant": args.variant,
        "clean_workbooks": len(rows),
        "rescue_activations": sum(int(row["rescue_alarm"]) for row in rows),
        "rescue_activation_rate": alarm_rate,
        "maximum_rescue_activation_rate": 0.10,
        "gate_passed": len(rows) == 48 and alarm_rate <= 0.10,
        "worker_processes": workers,
        "engineering_limit": args.limit,
        "by_family_rescue_activation_rate": {
            family: statistics.fmean(values) for family, values in sorted(by_family.items())
        },
        "v52_parameters": v52_default_parameters(args.variant),
        "manifest_sha256": sha256_file(manifest),
        "raw_sha256": sha256_file(raw_path),
        "warning": "Synthetic clean controls are not a production false-positive estimate.",
    }
    path = args.output / "v52_clean_summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
