"""Measure frozen R2 latency, throughput, and Python allocation peaks.

Latency is serial, throughput uses independent workbook/repeat processes, and
memory is measured in a separate serial pass so ``tracemalloc`` overhead is not
silently mixed into the latency numbers.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
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
from formulaguard.v5_core_r2 import v5_core_r2_scores
from formulaguard.workbook import WorkbookModel


METHODS = ("v4", "r2_source", "r2_full")
MODES = ("latency", "throughput", "memory")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_sizes(value: str) -> tuple[int, ...]:
    sizes = tuple(sorted({int(item.strip()) for item in value.split(",") if item.strip()}))
    if not sizes or any(size <= 0 for size in sizes):
        raise ValueError("--sizes must contain positive integers")
    return sizes


def percentile95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, int(0.95 * len(ordered) + 0.999999) - 1)]


def evaluate(payload: tuple[str, int, str, int, str, dict]) -> dict:
    workbook_text, target_size, method, repeat, mode, config = payload
    model = WorkbookModel.from_xlsx(Path(workbook_text))
    if mode == "memory":
        tracemalloc.start()
    started = time.perf_counter()
    if method == "v4":
        results = v4_scores(model, candidate_limit=15)
    elif method == "r2_source":
        results = v5_core_r2_scores(model, stage="source", config=config)
    elif method == "r2_full":
        results = v5_core_r2_scores(model, stage="full", config=config)
    else:
        raise ValueError(f"Unknown performance method: {method}")
    elapsed = time.perf_counter() - started
    peak = None
    if mode == "memory":
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak = peak_bytes / (1024 * 1024)
    return {
        "task_id": f"{mode}-{target_size}-{method}-{repeat}",
        "mode": mode,
        "target_formula_count": target_size,
        "actual_formula_count": len(model.formulas),
        "method": method,
        "repeat": repeat,
        "seconds": elapsed,
        "python_peak_memory_mb": peak,
        "returned_cells": len(results),
    }


def write_json_atomic(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_manifest(root: Path, sizes: tuple[int, ...]) -> list[dict]:
    path = root / "scaling_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    records = [
        row for row in manifest.get("records", [])
        if int(row.get("target_formula_count", -1)) in sizes
    ]
    by_size = {int(row["target_formula_count"]): row for row in records}
    if set(by_size) != set(sizes):
        raise SystemExit("Scaling manifest does not contain every requested size")
    for row in records:
        workbook = root / row["workbook"]
        if not workbook.is_file():
            raise SystemExit(f"Scaling workbook is missing: {workbook}")
    return sorted(records, key=lambda row: int(row["target_formula_count"]))


def summarize(rows: list[dict]) -> list[dict]:
    output = []
    keys = sorted({(row["mode"], row["target_formula_count"], row["method"]) for row in rows})
    for mode, size, method in keys:
        group = [
            row for row in rows
            if row["mode"] == mode
            and row["target_formula_count"] == size
            and row["method"] == method
        ]
        timings = [float(row["seconds"]) for row in group]
        memory = [float(row["python_peak_memory_mb"]) for row in group if row["python_peak_memory_mb"] is not None]
        output.append({
            "mode": mode,
            "target_formula_count": size,
            "method": method,
            "samples": len(group),
            "median_seconds": statistics.median(timings),
            "p95_seconds": percentile95(timings),
            "median_python_peak_memory_mb": statistics.median(memory) if memory else None,
        })
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", type=Path, default=Path("research/frozen_config_v5_core_r2.json"),
    )
    parser.add_argument("--input", type=Path, default=Path("data/scaling"))
    parser.add_argument("--output", type=Path, default=Path("results/v5_core_r2_performance"))
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--sizes", default="100,500,1000,5000")
    parser.add_argument("--mode", choices=(*MODES, "all"), default="all")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.workers < 1 or args.repeats < 1:
        parser.error("--workers and --repeats must be positive")
    sizes = parse_sizes(args.sizes)
    frozen = json.loads(args.config.read_text(encoding="utf-8"))
    if frozen.get("protocol") != "v5_core_r2_immutable_freeze_v1":
        raise SystemExit("R2 performance requires the immutable frozen R2 configuration")
    config = frozen["runtime_config"]
    records = load_manifest(args.input, sizes)
    modes = MODES if args.mode == "all" else (args.mode,)
    args.output.mkdir(parents=True, exist_ok=True)
    shard_root = args.output / "shards"
    shard_root.mkdir(exist_ok=True)
    metadata = {
        "protocol": "v5_core_r2_performance_v1",
        "measurement_separation": {
            "latency": "serial isolated timing without tracemalloc",
            "throughput": "independent jobs in a process pool; timings include contention",
            "memory": "serial tracemalloc pass; timing is not a latency estimate",
        },
        "workers_requested": args.workers,
        "repeats": args.repeats,
        "sizes": list(sizes),
        "modes": list(modes),
        "methods": list(METHODS),
        "frozen_config_sha256": sha256(args.config),
        "model_source_sha256": sha256(ROOT / "formulaguard/v5_core_r2.py"),
        "runner_source_sha256": sha256(Path(__file__)),
        "input_sha256": {
            row["workbook"]: sha256(args.input / row["workbook"]) for row in records
        },
    }
    metadata_path = args.output / "performance_metadata.json"
    if metadata_path.exists():
        if json.loads(metadata_path.read_text(encoding="utf-8")) != metadata:
            raise SystemExit("Performance resume refused: configuration, source, inputs, or protocol changed")
        if not args.resume:
            raise SystemExit("Performance output exists; pass --resume to verify and continue")
    else:
        write_json_atomic(metadata_path, metadata)

    tasks = []
    for mode in modes:
        repeats = 1 if mode == "memory" else args.repeats
        methods = METHODS if mode != "throughput" else ("r2_full",)
        for row in records:
            size = int(row["target_formula_count"])
            for method in methods:
                for repeat in range(1, repeats + 1):
                    tasks.append((str(args.input / row["workbook"]), size, method, repeat, mode, config))

    existing: dict[str, dict] = {}
    for shard in shard_root.glob("*.json"):
        record = json.loads(shard.read_text(encoding="utf-8"))
        if shard.stem != record.get("task_id"):
            raise SystemExit(f"Invalid performance shard: {shard}")
        existing[record["task_id"]] = record
    expected_ids = {f"{task[4]}-{task[1]}-{task[2]}-{task[3]}" for task in tasks}
    if not set(existing) <= expected_ids:
        raise SystemExit("Performance output contains unexpected task shards")
    pending = [task for task in tasks if f"{task[4]}-{task[1]}-{task[2]}-{task[3]}" not in existing]

    serial = [task for task in pending if task[4] in {"latency", "memory"}]
    parallel = [task for task in pending if task[4] == "throughput"]
    total = len(pending)
    completed = 0
    for task in serial:
        result = evaluate(task)
        write_json_atomic(shard_root / f"{result['task_id']}.json", result)
        completed += 1
        print(f"[{completed}/{total}] {result['task_id']}", flush=True)
    if parallel:
        workers = min(args.workers, len(parallel))
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(evaluate, task) for task in parallel]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                write_json_atomic(shard_root / f"{result['task_id']}.json", result)
                completed += 1
                print(f"[{completed}/{total}] {result['task_id']}", flush=True)

    shards = sorted(shard_root.glob("*.json"))
    observed = {path.stem for path in shards}
    if observed != expected_ids:
        raise SystemExit(
            f"Performance merge incomplete: missing={len(expected_ids-observed)}, "
            f"extra={len(observed-expected_ids)}"
        )
    rows = [json.loads(path.read_text(encoding="utf-8")) for path in shards]
    csv_path = args.output / "performance.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = summarize(rows)
    summary_csv = args.output / "performance_summary.csv"
    with summary_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    receipt = {
        "protocol": "v5_core_r2_performance_completion_v1",
        "complete": True,
        "tasks": len(rows),
        "workers_requested": args.workers,
        "latency_is_serial": True,
        "throughput_is_parallel": True,
        "memory_measured_separately": True,
        "metadata_sha256": sha256(metadata_path),
        "raw_csv_sha256": sha256(csv_path),
        "summary_csv_sha256": sha256(summary_csv),
    }
    receipt_path = args.output / "performance_complete.json"
    write_json_atomic(receipt_path, receipt)
    print(receipt_path)


if __name__ == "__main__":
    main()
