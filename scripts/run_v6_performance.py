"""Measure frozen V4/V6 latency and 24-worker throughput on 100-5000 formulas."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.localize import v4_scores
from formulaguard.v6 import v6_scores
from formulaguard.workbook import WorkbookModel
from scripts.verify_v6_freeze import verify


def evaluate(payload):
    path_text, method, variant, repeat, mode = payload
    model = WorkbookModel.from_xlsx(path_text)
    tracemalloc.start()
    started = time.perf_counter()
    if method == "v4":
        v4_scores(model, candidate_limit=15)
    else:
        v6_scores(model, variant=variant)
    seconds = time.perf_counter() - started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "workbook": Path(path_text).name,
        "size": int(Path(path_text).stem.split("_")[-1]),
        "method": method,
        "repeat": repeat,
        "mode": mode,
        "seconds": seconds,
        "python_peak_memory_mb": peak_bytes / (1024 * 1024),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("results/v6_performance"))
    args = parser.parse_args()
    if args.workers < 1 or args.repeats < 1:
        parser.error("--workers and --repeats must be positive")
    config = verify()
    variant = config["selected_variant"]
    files = [ROOT / f"data/scaling/scale_{size}.xlsx" for size in (100, 500, 1000, 5000)]
    if any(not path.exists() for path in files):
        raise SystemExit("Scaling workbooks missing; run the existing scaling benchmark builder")
    args.output.mkdir(parents=True, exist_ok=True)
    latency_tasks = [(str(path), method, variant, repeat, "latency") for path in files for method in ("v4", "v6") for repeat in range(1, args.repeats + 1)]
    latency = []
    for index, task_row in enumerate(latency_tasks, 1):
        latency.append(evaluate(task_row)); print(f"[{index}/{len(latency_tasks)}] latency {task_row[0]} {task_row[1]}", flush=True)
    throughput_tasks = [(str(path), "v6", variant, repeat, "throughput") for path in files for repeat in range(1, args.repeats + 1)]
    throughput = []
    workers = min(args.workers, len(throughput_tasks))
    started = time.perf_counter()
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        for index, result in enumerate(executor.map(evaluate, throughput_tasks, chunksize=1), 1):
            throughput.append(result); print(f"[{index}/{len(throughput_tasks)}] throughput size={result['size']}", flush=True)
    wall = time.perf_counter() - started
    rows = latency + throughput
    with (args.output / "performance_v6.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    summary = []
    for size in (100, 500, 1000, 5000):
        for method in ("v4", "v6"):
            values = [row["seconds"] for row in latency if row["size"] == size and row["method"] == method]
            memory = [row["python_peak_memory_mb"] for row in latency if row["size"] == size and row["method"] == method]
            summary.append({
                "size": size, "method": method,
                "median_seconds": statistics.median(values), "p95_seconds": sorted(values)[-1],
                "median_python_peak_memory_mb": statistics.median(memory),
                "max_python_peak_memory_mb": max(memory),
            })
    payload = {
        "selected_variant": variant,
        "workers_requested": args.workers,
        "workers_used": workers,
        "throughput_wall_seconds": wall,
        "memory_measurement": "Python allocations measured independently per call with tracemalloc; native library/RSS memory is not included",
        "summary": summary,
    }
    (args.output / "performance_v6_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output / "performance_v6_summary.json")


if __name__ == "__main__":
    main()
