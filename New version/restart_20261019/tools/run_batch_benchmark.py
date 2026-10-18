#!/usr/bin/env python3
"""Run and compare the deterministic 1/4/8-worker resource smoke test."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools/batch_runner.py"
MANIFEST = ROOT / "tools/benchmark_manifest.jsonl"
OUT = ROOT / "benchmark_runs_v2"
if OUT.exists():
    raise SystemExit(f"Preserving existing benchmark evidence: {OUT}")
OUT.mkdir()
results = {}
for workers in (1, 4, 8):
    target = OUT / f"workers_{workers}"
    subprocess.run([sys.executable, str(RUNNER), "--manifest", str(MANIFEST),
                    "--output-dir", str(target), "--workers", str(workers)],
                   cwd=ROOT, check=True)
    results[workers] = json.loads((target / "runtime.json").read_text())

hashes = {
    workers: {task["id"]: task["output_sha256"] for task in result["tasks"]}
    for workers, result in results.items()
}
consistent = hashes[1] == hashes[4] == hashes[8]
baseline = results[1]["wall_seconds"]
summary = {
    "schema": "hybridguard-batch-benchmark-v1",
    "manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
    "output_hashes_identical_1_4_8": consistent,
    "workers": {
        str(count): {
            "wall_seconds": result["wall_seconds"],
            "child_cpu_seconds": result["child_cpu_seconds"],
            "sampled_peak_aggregate_rss_bytes": result["aggregate_peak_rss_bytes_sampled"],
            "throughput_tasks_per_second": result["throughput_tasks_per_second"],
            "speedup_vs_one_worker": baseline / result["wall_seconds"],
            "all_tasks_complete": result["all_tasks_complete"],
        }
        for count, result in results.items()
    },
}
(OUT / "comparison.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
if not consistent or not all(item["all_tasks_complete"] for item in results.values()):
    raise SystemExit(1)
