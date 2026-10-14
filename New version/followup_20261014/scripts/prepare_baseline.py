"""Create an isolated rerun of the unmodified paper model; never touch old runs."""
from pathlib import Path
import datetime
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OLD = REPO / "workspace/paper_experiments_202609"
RUN = ROOT / "baseline"
ZIP = Path("/mnt/c/Users/hiuni/Desktop/Ayaka/jzib/qct/HybridGuard_V5_交接完整包_20260904(1).zip")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    if RUN.exists():
        raise SystemExit("Baseline directory already exists; refusing to overwrite evidence.")
    original = OLD / "source/HybridGuard_V5_handoff_20260904"
    manifest = json.loads((original / "handoff_manifest.json").read_text())
    assert manifest["version"] == "0.3.0" and manifest["file_count"] == 119
    checks = []
    with zipfile.ZipFile(ZIP) as archive:
        for entry in manifest["files"]:
            relative = entry["path"]
            local = original / relative
            zipped = archive.read("HybridGuard_V5_handoff_20260904/" + relative)
            assert sha(local) == entry["sha256"], relative
            assert hashlib.sha256(zipped).hexdigest() == entry["sha256"], relative
            checks.append({"path": relative, "sha256": entry["sha256"], "zip_and_local_match": True})
    old_locks = {}
    for name in ("source_lock.json", "prediction_lock.json"):
        lock_path = OLD / "protocol" / name
        lock = json.loads(lock_path.read_text())
        for relative, expected in lock["files"].items():
            assert sha(OLD / relative) == expected, (name, relative)
        old_locks[name] = {"sha256": sha(lock_path), "verified_files": len(lock["files"])}
    RUN.mkdir(parents=True)
    for name in ("source", "data"):
        shutil.copytree(OLD / name, RUN / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("scripts", "protocol", "results", "predictions", "qa", "logs"):
        (RUN / name).mkdir()
    for name in ("prepare.py", "freeze.py", "predict.py", "score.py", "validate_inputs.py"):
        shutil.copy2(OLD / "scripts" / name, RUN / "scripts" / name)
    for name in ("PROTOCOL.md", "data_manifest.json"):
        shutil.copy2(OLD / "protocol" / name, RUN / "protocol" / name)
    save(RUN / "qa/ORIGINAL_INTEGRITY.json", {
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "zip_path": str(ZIP), "zip_sha256": sha(ZIP),
        "handoff_file_count": len(checks), "checks": checks,
        "historical_locks_verified": old_locks,
        "old_git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
    })
    save(RUN / "qa/ENVIRONMENT.json", {
        "python": sys.version, "executable": sys.executable,
        "platform": platform.platform(), "processor": platform.processor(),
        "packages": subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True).splitlines(),
        "workers": 4, "baseline": "HybridGuard 0.3.0 / 20260904 handoff",
        "data_role": "previously revealed development/regression, not final validation",
    })
    result = subprocess.run([sys.executable, "scripts/freeze.py"], cwd=RUN, check=True, capture_output=True, text=True)
    (RUN / "logs/freeze.log").write_text(result.stdout + result.stderr)
    print("Verified 119 handoff files and historical locks; new baseline frozen:", RUN)
    print(result.stdout, end="")


if __name__ == "__main__":
    main()
