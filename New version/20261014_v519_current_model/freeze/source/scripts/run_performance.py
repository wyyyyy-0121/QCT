"""Measure FormulaGuard scaling performance without conflating two metrics.

``latency`` is deliberately serial: it measures one workbook in isolation.
``throughput`` runs independent workbook/repeat jobs in separate processes and
measures aggregate machine throughput.  Their timing values are not comparable.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.localize import localize
from formulaguard.workbook import WorkbookModel


def parse_sizes(raw: str | None) -> set[int] | None:
    if raw is None:
        return None
    values = {int(item.strip()) for item in raw.split(",") if item.strip()}
    if not values:
        raise ValueError("--sizes must contain at least one integer")
    return values


def run_one_job(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Run one independent workbook/repeat task (safe to send to a process)."""
    started = time.perf_counter()
    model = WorkbookModel.from_xlsx(Path(job["workbook_path"]))
    parse_seconds = time.perf_counter() - started
    rows: list[dict[str, Any]] = []
    for method in job["methods"]:
        method_started = time.perf_counter()
        results = localize(model, method, candidate_limit=job["candidate_limit"])
        rows.append({
            "target_formula_count": job["target_formula_count"],
            "actual_formula_count": len(model.formulas),
            "repeat": job["repeat"],
            "method": method,
            "parse_seconds": parse_seconds,
            "localization_seconds": time.perf_counter() - method_started,
            "returned_cells": len(results),
            "measurement_mode": job["measurement_mode"],
            "worker_count": job["worker_count"],
        })
    return rows


def percentile95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, int(0.95 * len(ordered) + 0.999999) - 1)]


def write_outputs(rows: list[dict[str, Any]], args: argparse.Namespace, wall_seconds: float, job_count: int) -> None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "target_formula_count", "actual_formula_count", "repeat", "method",
        "parse_seconds", "localization_seconds", "returned_cells",
        "measurement_mode", "worker_count",
    ]
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    summary_path = args.output.with_name(args.output.stem + "_summary.csv")
    summary_fields = [
        "target_formula_count", "method", "samples", "measurement_mode", "worker_count",
        "parse_median", "localization_median", "localization_p95",
    ]
    with summary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields)
        writer.writeheader()
        for size in sorted({row["target_formula_count"] for row in rows}):
            for method in sorted({row["method"] for row in rows}):
                group = [row for row in rows if row["target_formula_count"] == size and row["method"] == method]
                if not group:
                    continue
                timings = [float(row["localization_seconds"]) for row in group]
                writer.writerow({
                    "target_formula_count": size,
                    "method": method,
                    "samples": len(group),
                    "measurement_mode": args.mode,
                    "worker_count": args.workers,
                    "parse_median": statistics.median(float(row["parse_seconds"]) for row in group),
                    "localization_median": statistics.median(timings),
                    "localization_p95": percentile95(timings),
                })

    metadata_path = args.output.with_name(args.output.stem + "_metadata.json")
    metadata_path.write_text(json.dumps({
        "measurement_mode": args.mode,
        "workers": args.workers,
        "repeats": args.repeats,
        "jobs": job_count,
        "methods": [item.strip() for item in args.methods.split(",") if item.strip()],
        "candidate_limit": args.candidate_limit,
        "sizes": sorted({int(row["target_formula_count"]) for row in rows}),
        "batch_wall_seconds": wall_seconds,
        "jobs_per_second": job_count / wall_seconds if wall_seconds else None,
        "interpretation": (
            "Per-workbook isolated latency; run serially to avoid CPU contention."
            if args.mode == "latency" else
            "Aggregate multi-process throughput; individual timings include contention and are not latency estimates."
        ),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {args.output}")
    print(f"Summary: {summary_path}")
    print(f"Metadata: {metadata_path}")
    print(f"Batch wall time: {wall_seconds:.2f}s; jobs: {job_count}; workers: {args.workers}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure FormulaGuard isolated latency or batch throughput")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--methods", default="pattern,graph,formulaguard")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--candidate-limit", type=int, default=5)
    parser.add_argument("--mode", choices=("latency", "throughput"), default="latency")
    parser.add_argument("--workers", type=int, default=1, help="Processes; only >1 in throughput mode")
    parser.add_argument("--sizes", help="Optional comma-separated target formula counts, e.g. 100,500")
    args = parser.parse_args()
    if args.repeats < 1:
        raise SystemExit("--repeats must be at least 1")
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    if args.mode == "latency" and args.workers != 1:
        raise SystemExit("Latency must use --workers 1. Use --mode throughput for parallel batch work.")

    methods = [item.strip() for item in args.methods.split(",") if item.strip()]
    if not methods:
        raise SystemExit("At least one method is required")
    manifest = json.loads((args.input / "scaling_manifest.json").read_text(encoding="utf-8"))
    selected_sizes = parse_sizes(args.sizes)
    records = [record for record in manifest.get("records", []) if selected_sizes is None or record["target_formula_count"] in selected_sizes]
    if not records:
        raise SystemExit("No scaling records match the requested input/sizes")

    # Start long workbooks first to reduce the idle tail in a process pool.
    records.sort(key=lambda record: int(record["target_formula_count"]), reverse=args.mode == "throughput")
    jobs = [{
        "workbook_path": str(args.input / record["workbook"]),
        "target_formula_count": record["target_formula_count"],
        "repeat": repeat + 1,
        "methods": methods,
        "candidate_limit": args.candidate_limit,
        "measurement_mode": args.mode,
        "worker_count": args.workers,
    } for record in records for repeat in range(args.repeats)]

    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    if args.mode == "latency":
        for completed, job in enumerate(jobs, start=1):
            rows.extend(run_one_job(job))
            print(f"[{completed}/{len(jobs)}] latency size={job['target_formula_count']} repeat={job['repeat']}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(run_one_job, job): job for job in jobs}
            for completed, future in enumerate(as_completed(futures), start=1):
                job = futures[future]
                rows.extend(future.result())
                print(f"[{completed}/{len(jobs)}] throughput size={job['target_formula_count']} repeat={job['repeat']}", flush=True)
    write_outputs(rows, args, time.perf_counter() - started, len(jobs))


if __name__ == "__main__":
    main()
