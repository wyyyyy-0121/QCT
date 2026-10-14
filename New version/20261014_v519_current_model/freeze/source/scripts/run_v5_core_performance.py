"""Measure isolated latency and 24-process throughput for frozen V5-Core."""

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
from formulaguard.v5_core import v5_core_scores
from formulaguard.workbook import WorkbookModel


def evaluate(payload):
    path_text, method, head, config, repeat, mode = payload
    path = Path(path_text)
    model = WorkbookModel.from_xlsx(path)
    tracemalloc.start()
    started = time.perf_counter()
    if method == "v4":
        v4_scores(model, candidate_limit=15)
    else:
        v5_core_scores(model, head=head, config=config)
    seconds = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    return {
        "workbook": path.name,
        "size": int(path.stem.split("_")[-1]),
        "method": method,
        "repeat": repeat,
        "mode": mode,
        "seconds": seconds,
        "python_peak_memory_mb": peak / (1024 * 1024),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("research/frozen_config_v5_core.json"))
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("results/v5_core_performance"))
    args = parser.parse_args()
    frozen = json.loads(args.config.read_text(encoding="utf-8"))
    selected = frozen["selected_head"]
    head = "learned" if selected == "v5_learned" else "rule"
    config = frozen["selected_config"]
    files = [ROOT / f"data/scaling/scale_{size}.xlsx" for size in (100, 500, 1000, 5000)]
    if any(not path.exists() for path in files):
        raise SystemExit("Scaling workbooks are missing")
    args.output.mkdir(parents=True, exist_ok=True)
    latency_tasks = [
        (str(path), method, head, config, repeat, "latency")
        for path in files for method in ("v4", "v5_core") for repeat in range(1, args.repeats + 1)
    ]
    latency = []
    for index, task_row in enumerate(latency_tasks, 1):
        latency.append(evaluate(task_row))
        print(f"[{index}/{len(latency_tasks)}] latency size={latency[-1]['size']} {latency[-1]['method']}", flush=True)
    throughput_tasks = [
        (str(path), "v5_core", head, config, repeat, "throughput")
        for path in files for repeat in range(1, args.repeats + 1)
    ]
    throughput = []
    workers = min(args.workers, len(throughput_tasks))
    wall_started = time.perf_counter()
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        for index, result in enumerate(executor.map(evaluate, throughput_tasks, chunksize=1), 1):
            throughput.append(result)
            print(f"[{index}/{len(throughput_tasks)}] throughput size={result['size']}", flush=True)
    wall = time.perf_counter() - wall_started
    rows = latency + throughput
    with (args.output / "performance.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    summary = []
    ratios = []
    for size in (100, 500, 1000, 5000):
        medians = {}
        for method in ("v4", "v5_core"):
            group = [row for row in latency if row["size"] == size and row["method"] == method]
            medians[method] = statistics.median(row["seconds"] for row in group)
            summary.append({
                "size": size, "method": method,
                "median_seconds": medians[method],
                "p95_seconds": max(row["seconds"] for row in group),
                "median_python_peak_memory_mb": statistics.median(row["python_peak_memory_mb"] for row in group),
            })
        ratios.append({"size": size, "v5_over_v4": medians["v5_core"] / max(1e-9, medians["v4"])})
    payload = {
        "selected_head": selected,
        "workers_requested": args.workers,
        "workers_used": workers,
        "throughput_wall_seconds": wall,
        "summary": summary,
        "ratios": ratios,
        "median_runtime_gate_at_most_2x": all(row["v5_over_v4"] <= 2.0 for row in ratios),
    }
    output = args.output / "performance_summary.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
