#!/usr/bin/env python3
"""Continue the prelocked experiment after preserving a worker-1 timeout."""
from __future__ import annotations

import datetime as dt
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
EVIDENCE = ROOT / "source_evidence/raw/spreadsheetbench2"
INPUT_LOCK = EVIDENCE / "input_model_lock.json"
PILOT_MANIFEST = EVIDENCE / "manifests/pilot_workers_1.jsonl"
RUNNER = ROOT / "tools/batch_runner.py"
PREDICTOR = ROOT / "tools/predict_workbook.py"
FROZEN_MODEL = ROOT.parent / "followup_20261014/baseline/source/HybridGuard_V5_handoff_20260904"


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()
                       and "__pycache__" not in p.parts and p.suffix != ".pyc"):
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def safe_id(archive_path: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(archive_path).stem).strip("_.")
    return f"{base[:72]}_{hashlib.sha256(archive_path.encode()).hexdigest()[:10]}"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def load_manifest(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run_batch(manifest: Path, label: str, workers: int) -> dict:
    target = EVIDENCE / "runs" / label
    if target.exists():
        runtime_path = target / "runtime.json"
        if not runtime_path.is_file():
            raise SystemExit(f"Existing batch is unfinished; preserve and wait: {target}")
        result = json.loads(runtime_path.read_text())
        if result["manifest_sha256"] != sha256(manifest) or result["worker_count"] != workers:
            raise SystemExit(f"Existing batch manifest or worker count differs: {target}")
        validate_runtime(result, manifest)
        return result
    subprocess.run([sys.executable, str(RUNNER), "--manifest", str(manifest),
                    "--output-dir", str(target), "--workers", str(workers),
                    "--worker-memory-mib", "1024", "--timeout", "900"],
                   cwd=ROOT, check=False)
    result = json.loads((target / "runtime.json").read_text())
    validate_runtime(result, manifest)
    return result


def validate_runtime(runtime: dict, manifest: Path) -> None:
    rows = load_manifest(manifest)
    tasks = runtime["tasks"]
    if len(tasks) != len(rows) or {t["id"] for t in tasks} != {r["id"] for r in rows}:
        raise SystemExit("Runtime lacks exactly one terminal record per manifest task")
    for task in tasks:
        if task["status"] not in {"complete", "timeout", "failed"}:
            raise SystemExit("Runtime contains a nonterminal task")
        output = Path(task.get("cwd", "")) / "prediction.json"
        if task["status"] == "complete":
            if task["returncode"] != 0 or not output.is_file() or sha256(output) != task["output_sha256"].get("prediction.json"):
                raise SystemExit("Complete prediction is missing or differs from recorded hash")
        elif output.exists():
            raise SystemExit("Failed task has an ambiguous prediction file; do not score")


def verify_frozen(lock: dict) -> None:
    if lock.get("model_tree_sha256") != tree_sha256(FROZEN_MODEL):
        raise SystemExit("Frozen paper model tree changed after the input lock")
    for relative, expected in lock["inference_source_sha256"].items():
        source = REPO / relative
        if not source.is_file() or sha256(source) != expected:
            raise SystemExit(f"Frozen inference source changed after the input lock: {relative}")
    if any(not Path(row["local_path"]).is_file() or
           sha256(Path(row["local_path"])) != row["sha256"] for row in lock["inputs"]):
        raise SystemExit("An input is missing or differs from its prelocked SHA-256")


def task_signature(runtime: dict) -> dict[str, tuple]:
    return {task["id"]: (task["status"], task["returncode"],
                          task["output_sha256"].get("prediction.json"))
            for task in runtime["tasks"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="Verify locks without starting a batch")
    args = parser.parse_args()
    if not INPUT_LOCK.is_file() or not PILOT_MANIFEST.is_file():
        raise SystemExit("Prelocked input/model lock or worker-1 manifest is missing")
    lock = json.loads(INPUT_LOCK.read_text())
    expected_python = load_manifest(PILOT_MANIFEST)[0]["argv"][0]
    if sys.executable != expected_python or sys.version != lock["runtime"]["python"]:
        raise SystemExit(f"Use the original locked interpreter: {expected_python}")
    base = json.loads((EVIDENCE / "runs/pilot_workers_1/runtime.json").read_text())
    if lock.get("input_count") != 100 or len(lock.get("inputs", [])) != 100:
        raise SystemExit("The frozen input lock does not contain exactly 100 inputs")
    verify_frozen(lock)
    first_by_group = {}
    for row in sorted(lock["inputs"], key=lambda item: (item["group"], item["archive_path"])):
        first_by_group.setdefault(row["group"], row)
    expected_pilot = [safe_id(row["archive_path"])
                      for _, row in sorted(first_by_group.items())]
    manifest_ids = [row["id"] for row in load_manifest(PILOT_MANIFEST)]
    if manifest_ids != expected_pilot or len(expected_pilot) != 10 or manifest_ids != lock["pilot_ids"]:
        raise SystemExit("Pilot manifest differs from the prelocked one-per-group selection")
    input_by_id = {safe_id(row["archive_path"]): row for row in lock["inputs"]}
    if len(input_by_id) != 100:
        raise SystemExit("Input task IDs are not unique")
    for row in load_manifest(PILOT_MANIFEST):
        expected_argv = [expected_python, str(PREDICTOR), input_by_id[row["id"]]["local_path"],
                         "--output", "prediction.json"]
        if row != {"id": row["id"], "argv": expected_argv, "timeout_seconds": 900,
                   "outputs": ["prediction.json"]}:
            raise SystemExit("Pilot command or timeout differs from the locked execution policy")
    if base["all_tasks_complete"]:
        raise SystemExit("This continuation is only for a pilot containing an explicit failed task")
    validate_runtime(base, PILOT_MANIFEST)
    if args.check_only:
        print("Preflight passed: original Python, frozen model/source, 100 inputs, pilot manifest and worker-1 outputs")
        return

    pilot4 = run_batch(PILOT_MANIFEST, "pilot_workers_4_retry", 4)
    pilot8 = run_batch(PILOT_MANIFEST, "pilot_workers_8", 8)
    signatures = {"1": task_signature(base), "4": task_signature(pilot4),
                  "8": task_signature(pilot8)}
    pilot_consistent = signatures["1"] == signatures["4"] == signatures["8"]
    pilot_record = {"schema": "spreadsheetbench2-pilot-amendment-v1",
                    "amendment": "SPREADSHEETBENCH2_EXECUTION_AMENDMENT.md",
                    "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "task_status_and_success_hashes_identical_1_4_8": pilot_consistent,
                    "worker_1_runtime": base, "worker_4_runtime": pilot4,
                    "worker_8_runtime": pilot8,
                    "task_signatures": {w: {k: list(v) for k, v in rows.items()}
                                        for w, rows in signatures.items()},
                    "full_run_started": False}
    write_json(EVIDENCE / "pilot_comparison_amended.json", pilot_record)
    if not pilot_consistent:
        raise SystemExit("Pilot terminal states or successful output hashes differ; full run stopped")

    verify_frozen(lock)

    rows = lock["inputs"]
    manifest = EVIDENCE / "manifests/full_workers_8.jsonl"
    if manifest.exists():
        raise SystemExit(f"Preserving existing evidence: {manifest}")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("".join(json.dumps({
        "id": safe_id(row["archive_path"]),
        "argv": [sys.executable, str(PREDICTOR), row["local_path"],
                 "--output", "prediction.json"],
        "timeout_seconds": 900,
        "outputs": ["prediction.json"],
    }, ensure_ascii=False) + "\n" for row in rows))
    full = run_batch(manifest, "full_workers_8", 8)
    verify_frozen(lock)
    current_inputs_match = all(sha256(Path(row["local_path"])) == row["sha256"]
                               for row in rows)
    if not current_inputs_match:
        raise SystemExit("An input hash changed after inference; do not score")
    allowed = {"complete", "timeout", "failed"}
    if any(task["status"] not in allowed for task in full["tasks"]):
        raise SystemExit("A task lacks an explicit terminal status; do not score")
    predictions = []
    for task in full["tasks"]:
        input_row = input_by_id[task["id"]]
        output_path = Path(task.get("cwd", "")) / "prediction.json"
        predictions.append({"id": task["id"], "status": task["status"],
                            "returncode": task["returncode"],
                            "input_sha256": input_row["sha256"],
                            "prediction_sha256": sha256(output_path) if task["status"] == "complete" else None,
                            "wall_seconds": task["wall_seconds"],
                            "child_cpu_seconds": task["child_cpu_seconds"]})
    write_json(EVIDENCE / "prediction_lock.json", {
        "schema": "spreadsheetbench2-prediction-lock-v1",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "amendment": "SPREADSHEETBENCH2_EXECUTION_AMENDMENT.md",
        "input_model_lock_sha256": sha256(INPUT_LOCK),
        "inference_source_sha256_from_prelock": lock["inference_source_sha256"],
        "continuation_source_sha256": sha256(Path(__file__)),
        "execution_amendment_sha256": sha256(ROOT / "SPREADSHEETBENCH2_EXECUTION_AMENDMENT.md"),
        "runtime_python": sys.version,
        "runtime_executable": sys.executable,
        "model_tree_sha256_verified_after_inference": lock["model_tree_sha256"],
        "pilot_comparison_sha256": sha256(EVIDENCE / "pilot_comparison_amended.json"),
        "pilot_status_and_success_hashes_identical_1_4_8": True,
        "all_100_inputs_hashes_unchanged": True,
        "full_runtime": full,
        "predictions": predictions,
        "complete_prediction_count": sum(row["status"] == "complete" for row in predictions),
        "timeout_count": sum(row["status"] == "timeout" for row in predictions),
        "failed_count": sum(row["status"] == "failed" for row in predictions),
        "scoring_files_read_before_lock": [],
        "scoring_may_begin": True,
    })
    print(json.dumps({"pilot_status_and_success_hashes_identical_1_4_8": True,
                      "full_tasks": full["task_count"],
                      "complete": sum(row["status"] == "complete" for row in predictions),
                      "timeout": sum(row["status"] == "timeout" for row in predictions),
                      "failed": sum(row["status"] == "failed" for row in predictions),
                      "wall_seconds": full["wall_seconds"],
                      "cpu_seconds": full["child_cpu_seconds"],
                      "sampled_peak_aggregate_rss_bytes": full["aggregate_peak_rss_bytes_sampled"],
                      "prediction_lock": str(EVIDENCE / "prediction_lock.json")}, indent=2))


if __name__ == "__main__":
    main()
