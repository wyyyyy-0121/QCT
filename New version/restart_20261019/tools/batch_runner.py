#!/usr/bin/env python3
"""Run independent per-workbook commands with bounded parallelism and logs.

Manifest: JSONL rows with `id`, `argv`, optional `cwd`, `timeout_seconds`,
and `outputs` (paths relative to cwd). Each task must own its output paths.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

RESOURCE_MARKER = "__HG_RESOURCE__"
_active: dict[str, subprocess.Popen] = {}
_active_lock = threading.Lock()
_peak_aggregate_rss = 0


def load_manifest(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    ids = [row.get("id") for row in rows]
    if not rows or any(not isinstance(value, str) or not value for value in ids):
        raise ValueError("manifest must contain tasks with non-empty string ids")
    if len(ids) != len(set(ids)):
        raise ValueError("task ids must be unique")
    if any(not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or value in (".", "..") for value in ids):
        raise ValueError("task ids must be safe single directory names")
    for row in rows:
        if not isinstance(row.get("argv"), list) or not row["argv"] or not all(
                isinstance(arg, str) for arg in row["argv"]):
            raise ValueError(f"{row['id']}: argv must be a non-empty string list")
    return rows


def process_tree_stats(root_pids: list[int]) -> tuple[float, int]:
    """Return sampled tree CPU seconds and resident bytes from Linux /proc."""
    parents: dict[int, int] = {}
    cpu: dict[int, float] = {}
    rss: dict[int, int] = {}
    ticks = os.sysconf("SC_CLK_TCK")
    page_size = os.sysconf("SC_PAGE_SIZE")
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text()
            fields = raw[raw.rfind(")") + 2:].split()
            pid = int(entry.name)
            parents[pid] = int(fields[1])
            cpu[pid] = (int(fields[11]) + int(fields[12])) / ticks
            resident_pages = int((entry / "statm").read_text().split()[1])
            rss[pid] = resident_pages * page_size
        except (OSError, ValueError, IndexError):
            continue
    descendants = set(root_pids)
    changed = True
    while changed:
        changed = False
        for pid, parent in parents.items():
            if parent in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    return sum(cpu.get(pid, 0.0) for pid in descendants), sum(rss.get(pid, 0) for pid in descendants)


def sample_active_rss() -> int:
    global _peak_aggregate_rss
    with _active_lock:
        pids = [proc.pid for proc in _active.values() if proc.poll() is None]
    rss = process_tree_stats(pids)[1] if pids else 0
    _peak_aggregate_rss = max(_peak_aggregate_rss, rss)
    return rss


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def execute(task: dict, default_cwd: Path | None, out_dir: Path, timeout: float,
            thread_limit: int) -> dict:
    task_id = task["id"]
    task_dir = out_dir / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=False)
    cwd = Path(task["cwd"]).resolve() if task.get("cwd") else (default_cwd or task_dir.resolve())
    log_path = task_dir / "combined.log"
    resource_path = task_dir / "gnu_time.txt"
    time_bin = shutil.which("/usr/bin/time")
    if not time_bin:
        raise RuntimeError("GNU /usr/bin/time is required for child CPU/RSS accounting")
    env = os.environ.copy()
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        env[name] = str(thread_limit)
    command = [time_bin, "-f", RESOURCE_MARKER + "%U %S %M", "-o", str(resource_path),
               *task["argv"]]
    started = time.monotonic()
    status, timed_out = None, False
    with log_path.open("wb") as log:
        proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
        with _active_lock:
            _active[task_id] = proc
        try:
            status = proc.wait(timeout=float(task.get("timeout_seconds", timeout)))
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, 15)
                proc.wait(timeout=3)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, 9)
                except ProcessLookupError:
                    pass
                proc.wait()
            status = proc.returncode
        finally:
            with _active_lock:
                _active.pop(task_id, None)
    wall = time.monotonic() - started
    measured_cpu = measured_peak = None
    if resource_path.exists():
        match = re.search(r"__HG_RESOURCE__(\S+)\s+(\S+)\s+(\d+)", resource_path.read_text())
        if match:
            measured_cpu = float(match.group(1)) + float(match.group(2))
            measured_peak = int(match.group(3)) * 1024
    output_hashes = {}
    for item in task.get("outputs", []):
        path = (cwd / item).resolve()
        output_hashes[item] = sha256(path) if path.is_file() else None
    return {"id": task_id, "argv": task["argv"], "cwd": str(cwd),
            "status": "timeout" if timed_out else ("complete" if status == 0 else "failed"),
            "returncode": status, "wall_seconds": wall, "child_cpu_seconds": measured_cpu,
            "child_peak_rss_bytes": measured_peak, "log": str(log_path),
            "output_sha256": output_hashes}


def run(args: argparse.Namespace) -> dict:
    global _peak_aggregate_rss
    _peak_aggregate_rss = 0
    manifest = Path(args.manifest).resolve()
    out_dir = Path(args.output_dir).resolve()
    tasks = load_manifest(manifest)
    requested_workers = args.workers
    available = next((int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()
                      if line.startswith('MemAvailable:')), 0)
    estimate = getattr(args, 'worker_memory_mib', None)
    memory_budget = int(available * 0.7)
    if estimate:
        if memory_budget < estimate * 1024 * 1024:
            raise SystemExit('Available memory budget is below the per-worker estimate')
        args.workers = min(args.workers, max(1, memory_budget // (estimate * 1024 * 1024)))
    if out_dir.exists():
        raise SystemExit(f"Refusing to overwrite existing output directory: {out_dir}")
    out_dir.mkdir(parents=True)
    cwd = Path(args.cwd).resolve() if args.cwd else None
    sampler_stop = threading.Event()

    def sample():
        while not sampler_stop.wait(0.05):
            sample_active_rss()

    sampler = threading.Thread(target=sample, name="memory-sampler", daemon=True)
    sampler.start()
    started = time.monotonic()
    results = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(execute, task, cwd, out_dir, args.timeout,
                                   args.thread_limit) for task in tasks]
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                except Exception as error:
                    task = tasks[futures.index(future)]
                    result = {"id": task["id"], "status": "failed", "returncode": None,
                              "error": type(error).__name__ + ": " + str(error),
                              "wall_seconds": 0.0, "child_cpu_seconds": None,
                              "child_peak_rss_bytes": None, "output_sha256": {}}
                results.append(result)
                print(result["id"], result["status"],
                      f"wall={result['wall_seconds']:.2f}s", flush=True)
    finally:
        sampler_stop.set()
        sampler.join()
    wall = time.monotonic() - started
    complete = [row for row in results if row["status"] == "complete"]
    payload = {"schema": "hybridguard-batch-runtime-v1",
               "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
               "manifest_sha256": sha256(manifest), "task_count": len(tasks),
               "worker_count": args.workers, "numeric_library_thread_limit": args.thread_limit,
               "requested_worker_count": requested_workers,
               "available_memory_bytes_at_start": available,
               "memory_budget_bytes_at_start": memory_budget,
               "estimated_worker_memory_mib": estimate,
               "memory_limit_note": "admission estimate, not a hard OS memory limit",
               "wall_seconds": wall,
               "child_cpu_seconds": (sum(row["child_cpu_seconds"] for row in results)
                                     if all(row["child_cpu_seconds"] is not None for row in results) else None),
               "cpu_accounting_complete": all(row["child_cpu_seconds"] is not None for row in results),
               "aggregate_peak_rss_bytes_sampled": _peak_aggregate_rss,
               "throughput_tasks_per_second": len(complete) / wall if wall else None,
               "speedup_vs_one_worker": None,
               "all_tasks_complete": len(complete) == len(tasks),
               "tasks": sorted(results, key=lambda row: row["id"])}
    (out_dir / "runtime.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({key: payload[key] for key in (
        "task_count", "worker_count", "wall_seconds", "child_cpu_seconds",
        "aggregate_peak_rss_bytes_sampled", "throughput_tasks_per_second",
        "all_tasks_complete")}, indent=2))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cwd", type=Path)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--thread-limit", type=int, default=1)
    parser.add_argument("--worker-memory-mib", type=int, default=1024,
                        help="estimated per-workbook peak memory; reduce admission using 70%% of MemAvailable")
    args = parser.parse_args()
    if args.workers < 1 or args.thread_limit < 1 or args.timeout <= 0 or args.worker_memory_mib <= 0:
        parser.error("workers, thread-limit, and timeout must be positive")
    payload = run(args)
    if not payload["all_tasks_complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
