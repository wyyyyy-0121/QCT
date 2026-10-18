#!/usr/bin/env python3
"""Run the unchanged read-only interface with periodic Python stack traces.

Pass the normal predict_workbook.py arguments. Use batch_runner.py to bound
runtime and capture stacks. This diagnoses execution, not formula accuracy.
"""
import faulthandler
import json
from pathlib import Path
import runpy
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "source_evidence/raw/spreadsheetbench2"
REPO = ROOT.parents[1]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: profile_frozen_workbook.py INPUT.xlsx")
    source = Path(sys.argv[1]).resolve()
    lock = json.loads((EVIDENCE / "input_model_lock.json").read_text())
    match = next((row for row in lock["inputs"] if Path(row["local_path"]).resolve() == source), None)
    if match is None:
        raise SystemExit("Input is not present in the pre-run input lock")
    manifest = EVIDENCE / "diagnosis" / "diagnosis_manifest.jsonl"
    result_dir = EVIDENCE / "diagnosis" / "run"
    if manifest.exists() or result_dir.exists():
        raise SystemExit("Preserving existing diagnostic evidence")
    task = {"id": "timed_out_input", "argv": [sys.executable, str(Path(__file__).resolve()),
             "--profile", str(source), "--output", "profiled_prediction.json"],
            "timeout_seconds": 60, "outputs": ["profiled_prediction.json"]}
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(task) + "\n")
    subprocess.run([sys.executable, str(ROOT / "tools/batch_runner.py"),
                    "--manifest", str(manifest), "--output-dir", str(result_dir),
                    "--workers", "1", "--worker-memory-mib", "1024", "--timeout", "60"],
                   cwd=ROOT, check=False)
    runtime = json.loads((result_dir / "runtime.json").read_text())
    log = result_dir / "tasks/timed_out_input/combined.log"
    (EVIDENCE / "diagnosis" / "diagnosis_summary.json").write_text(json.dumps({
        "input_sha256": match["sha256"], "input_lock_sha256": __import__("hashlib").sha256(
            (EVIDENCE / "input_model_lock.json").read_bytes()).hexdigest(),
        "profile_script_sha256": __import__("hashlib").sha256(Path(__file__).read_bytes()).hexdigest(),
        "status": runtime["tasks"][0]["status"],
        "wall_seconds": runtime["tasks"][0]["wall_seconds"],
        "runtime_json": runtime, "stack_log_sha256": __import__("hashlib").sha256(log.read_bytes()).hexdigest(),
        "purpose": "Execution diagnosis only; no scoring files read",
    }, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__" and len(sys.argv) >= 2 and sys.argv[1] == "--profile":
    entry = Path(__file__).with_name("predict_workbook.py")
    sys.argv = [str(entry), *sys.argv[2:]]
    faulthandler.enable()
    faulthandler.dump_traceback_later(15, repeat=True)
    try:
        runpy.run_path(str(entry), run_name="__main__")
    finally:
        faulthandler.cancel_dump_traceback_later()
elif __name__ == "__main__":
    main()
