#!/usr/bin/env python3
"""Compare read-only full paper/dev11 inference on eight revealed workbooks."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT.parent / "followup_20261014/development/crossdomain_dev1"
OUT = ROOT / "workbook_benchmark_v3"
if OUT.exists():
    raise SystemExit(f"Preserve existing evidence: {OUT}")
OUT.mkdir()
index = json.loads((DATA / "public_index.json").read_text())[:8]
manifest = OUT / "manifest.jsonl"
rows = []
for item in index:
    path = DATA / item["input"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    rows.append({"id": item["id"], "argv": [sys.executable,
        str(ROOT / "tools/predict_workbook.py"), str(path), "--output", "prediction.json",
        "--parallel-sheets", *item["parallel_sheets"]], "outputs": ["prediction.json"]})
manifest.write_text("".join(json.dumps(row) + "\n" for row in rows))
results = {}
for workers in (1, 4, 8):
    target = OUT / f"workers_{workers}"
    subprocess.run([sys.executable, str(ROOT / "tools/batch_runner.py"),
                    "--manifest", str(manifest), "--output-dir", str(target),
                    "--workers", str(workers)], check=True)
    results[workers] = json.loads((target / "runtime.json").read_text())
hashes = {count: {task["id"]: task["output_sha256"] for task in result["tasks"]}
          for count, result in results.items()}
consistent = hashes[1] == hashes[4] == hashes[8]
summary = {"output_hashes_identical_1_4_8": consistent,
           "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in sorted((ROOT / 'tools').glob('*.py'))},
           "scope": "full paper SG/FG and dev11, eight revealed crossdomain workbooks; not accuracy validation",
           "source_inputs_unchanged": all(hashlib.sha256((DATA / i["input"]).read_bytes()).hexdigest()
                                          == i["sha256"] for i in index),
           "workers": {str(count): {**{key: result[key] for key in (
               "wall_seconds", "child_cpu_seconds", "aggregate_peak_rss_bytes_sampled",
               "throughput_tasks_per_second", "all_tasks_complete")},
               "speedup_vs_one_worker": results[1]["wall_seconds"] / result["wall_seconds"]}
                       for count, result in results.items()}}
(OUT / "comparison.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
if not consistent or not summary["source_inputs_unchanged"]:
    raise SystemExit(1)
