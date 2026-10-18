#!/usr/bin/env python3
"""Lock, resource-test, and run frozen paper inference on SpreadsheetBench 2."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
ARCHIVE = ROOT / "source_evidence/raw/spreadsheetbench2-09-10.zip"
EVIDENCE = ROOT / "source_evidence/raw/spreadsheetbench2"
INPUT_ROOT = EVIDENCE / "inputs"
MANIFEST_ROOT = EVIDENCE / "manifests"
RUN_ROOT = EVIDENCE / "runs"
PREDICTOR = ROOT / "tools/predict_workbook.py"
RUNNER = ROOT / "tools/batch_runner.py"
LEGACY = ROOT.parent / "followup_20261014"
MODEL_ROOT = LEGACY / "baseline/source/HybridGuard_V5_handoff_20260904"
EXPECTED_ARCHIVE_SHA256 = "52699c974c30aced7125f3d12cdaabbbcbba8db804373d7397a5d3bdf68e5b3e"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()
                       and "__pycache__" not in p.parts and p.suffix != ".pyc"):
        rel = path.relative_to(root).as_posix().encode()
        digest.update(len(rel).to_bytes(4, "big"))
        digest.update(rel)
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def safe_id(path: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(path).stem).strip("_.")
    return f"{base[:72]}_{hashlib.sha256(path.encode()).hexdigest()[:10]}"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    if EVIDENCE.exists():
        raise SystemExit(f"Refusing to overwrite existing evidence: {EVIDENCE}")
    if not ARCHIVE.is_file() or sha256_file(ARCHIVE) != EXPECTED_ARCHIVE_SHA256:
        raise SystemExit("Archive is missing or its SHA-256 does not match the preregistered LFS OID")

    prefix = "spreadsheetbench-v2/Debugging/spreadsheet/"
    with zipfile.ZipFile(ARCHIVE) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise SystemExit(f"ZIP integrity failure: {bad}")
        members = archive.namelist()
        input_members = sorted(name for name in members if name.startswith(prefix)
                               and name.endswith("_input.xlsx"))
        golden_members = sorted(name for name in members if name.startswith(prefix)
                                and name.endswith("_golden.xlsx"))
        groups = {Path(name).parts[3] for name in input_members}
        if len(input_members) != 100 or len(golden_members) != 10 or len(groups) != 10:
            raise SystemExit("Unexpected Debugging inventory; expected 100 inputs, 10 goldens, 10 groups")

        input_rows = []
        for name in input_members:
            target = INPUT_ROOT / Path(*Path(name).parts[2:])
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, target.open("xb") as output:
                while block := source.read(1024 * 1024):
                    output.write(block)
            input_rows.append({"archive_path": name, "local_path": str(target),
                               "sha256": sha256_file(target), "bytes": target.stat().st_size,
                               "group": Path(name).parts[3]})

        golden_rows = []
        for name in golden_members:
            digest = hashlib.sha256()
            size = 0
            with archive.open(name) as handle:
                while block := handle.read(1024 * 1024):
                    digest.update(block)
                    size += len(block)
            golden_rows.append({"archive_path": name, "sha256": digest.hexdigest(), "bytes": size})

    inputs_by_group: dict[str, list[dict]] = {}
    for row in input_rows:
        inputs_by_group.setdefault(row["group"], []).append(row)
    pilot_rows = [rows[0] for _, rows in sorted(inputs_by_group.items())]
    tool_files = [PREDICTOR, RUNNER, Path(__file__),
                  LEGACY / "baseline/scripts/predict.py",
                  LEGACY / "scripts/selector_dev2.py", LEGACY / "scripts/selector_dev4.py",
                  LEGACY / "scripts/selector_dev6.py", LEGACY / "scripts/selector_dev11.py"]
    missing = [str(path) for path in tool_files if not path.is_file()]
    if missing or not MODEL_ROOT.is_dir():
        raise SystemExit("Missing frozen inference dependency: " + ", ".join(missing or [str(MODEL_ROOT)]))
    source_lock = {str(path.relative_to(REPO)): sha256_file(path) for path in tool_files}
    pre_lock = {
        "schema": "spreadsheetbench2-input-lock-v1",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "archive": {"path": str(ARCHIVE), "sha256": sha256_file(ARCHIVE),
                    "bytes": ARCHIVE.stat().st_size,
                    "mirror_revision": "5a2215ed4121945ab09d8723df2995602090b042"},
        "scope": "all Debugging input workbooks only; no dataset.json or workbook contents inspected",
        "group_count": len(groups), "input_count": len(input_rows), "golden_count": len(golden_rows),
        "inputs": input_rows, "goldens_hash_only": golden_rows,
        "model_tree_sha256": sha256_tree(MODEL_ROOT), "model_root": str(MODEL_ROOT),
        "inference_source_sha256": source_lock,
        "runtime": {"python": sys.version, "platform": platform.platform(),
                    "processor": platform.processor(), "logical_cpus": os.cpu_count()},
        "pilot_ids": [safe_id(row["archive_path"]) for row in pilot_rows],
        "pilot_rule": "first lexically sorted input in each of 10 task directories",
        "workers": [1, 4, 8], "per_worker_memory_admission_estimate_mib": 1024,
        "full_run_workers": 8,
        "prediction_policy": "paper output only; no parallel_sheets; no labels or golden files read",
    }
    write_json(EVIDENCE / "input_model_lock.json", pre_lock)

    def run_batch(rows: list[dict], label: str, workers: int) -> dict:
        manifest = MANIFEST_ROOT / f"{label}.jsonl"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for row in rows:
            identifier = safe_id(row["archive_path"])
            lines.append(json.dumps({
                "id": identifier,
                "argv": [sys.executable, str(PREDICTOR), row["local_path"],
                         "--output", "prediction.json"],
                "timeout_seconds": args.timeout,
                "outputs": ["prediction.json"],
            }, ensure_ascii=False))
        manifest.write_text("\n".join(lines) + "\n")
        destination = RUN_ROOT / label
        subprocess.run([sys.executable, str(RUNNER), "--manifest", str(manifest),
                        "--output-dir", str(destination), "--workers", str(workers),
                        "--worker-memory-mib", "1024", "--timeout", str(args.timeout)],
                       cwd=ROOT, check=True)
        return json.loads((destination / "runtime.json").read_text())

    pilot_runtime = {str(count): run_batch(pilot_rows, f"pilot_workers_{count}", count)
                     for count in (1, 4, 8)}
    pilot_hashes = {count: {task["id"]: task["output_sha256"].get("prediction.json")
                            for task in result["tasks"]}
                    for count, result in pilot_runtime.items()}
    pilot_consistent = pilot_hashes["1"] == pilot_hashes["4"] == pilot_hashes["8"]
    if not pilot_consistent or not all(result["all_tasks_complete"]
                                       for result in pilot_runtime.values()):
        write_json(EVIDENCE / "pilot_result.json", {
            "output_hashes_identical_1_4_8": pilot_consistent,
            "runtime": pilot_runtime, "hashes": pilot_hashes,
            "full_run_started": False,
        })
        raise SystemExit("Pilot failed or output hashes diverged; full run stopped")

    full_runtime = run_batch(input_rows, "full_workers_8", 8)
    if not full_runtime["all_tasks_complete"]:
        write_json(EVIDENCE / "full_run_incomplete.json", full_runtime)
        raise SystemExit("Full run has failed or timed-out tasks; scoring lock not created")

    prediction_rows = []
    for task in full_runtime["tasks"]:
        prediction_path = Path(task["cwd"]) / "prediction.json"
        prediction_rows.append({"id": task["id"], "status": task["status"],
                                "input_sha256": next(row["sha256"] for row in input_rows
                                    if safe_id(row["archive_path"]) == task["id"]),
                                "prediction_sha256": sha256_file(prediction_path)})
    post_lock = {
        "schema": "spreadsheetbench2-prediction-lock-v1",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "input_model_lock_sha256": sha256_file(EVIDENCE / "input_model_lock.json"),
        "pilot_output_hashes_identical_1_4_8": True,
        "pilot_runtime": pilot_runtime, "full_runtime": full_runtime,
        "prediction_sha256": prediction_rows,
        "all_predictions_complete": True,
        "scoring_files_read_before_lock": [],
        "golden_files_extracted": False,
        "scoring_may_begin": True,
    }
    write_json(EVIDENCE / "prediction_lock.json", post_lock)
    print(json.dumps({"pilot_output_hashes_identical_1_4_8": True,
                      "full_tasks": full_runtime["task_count"],
                      "full_wall_seconds": full_runtime["wall_seconds"],
                      "full_cpu_seconds": full_runtime["child_cpu_seconds"],
                      "full_sampled_peak_aggregate_rss_bytes": full_runtime["aggregate_peak_rss_bytes_sampled"],
                      "full_throughput_tasks_per_second": full_runtime["throughput_tasks_per_second"],
                      "prediction_lock": str(EVIDENCE / "prediction_lock.json")}, indent=2))


if __name__ == "__main__":
    main()
