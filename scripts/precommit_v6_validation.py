"""Create and verify the label-separation receipt for V6 internal validation.

`prepare` is run once after dataset construction and label-aware quality audit,
but before any validation prediction.  The prediction orchestrator subsequently
uses `verify-public`, which never opens the label file.  Only after all complete
rankings are on disk may it call `verify-secret` and then score the labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data/v6_validation"
DEFAULT_RECEIPT = ROOT / "research/V6_VALIDATION_PRECOMMIT.json"
PUBLIC_FILES = (
    "instances.jsonl",
    "clean_manifest.json",
    "dataset_manifest.json",
    "dataset_summary.csv",
    "dataset_build_complete.json",
    "validation/dataset_quality.json",
    "validation/structural_diversity.json",
    "validation/leakage_audit.json",
)
SECRET_FILE = "evaluation_labels.jsonl"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(dataset: Path) -> dict:
    paths = sorted(dataset.rglob("*.xlsx"), key=lambda item: item.relative_to(dataset).as_posix())
    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(dataset).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256(path).encode("ascii"))
        digest.update(b"\n")
    return {"count": len(paths), "aggregate_sha256": digest.hexdigest()}


def git_commit() -> str:
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe"
    executable = shutil.which("git") or (str(bundled) if bundled.is_file() else None)
    if executable is None:
        return "unavailable"
    completed = subprocess.run(
        [executable, "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True,
    )
    if completed.returncode:
        return "unavailable"
    return completed.stdout.strip()


def public_hashes(dataset: Path) -> dict[str, str]:
    missing = [name for name in PUBLIC_FILES if not (dataset / name).is_file()]
    if missing:
        raise SystemExit(f"V6 validation precommit refused; missing public/audit files: {missing}")
    return {name: sha256(dataset / name) for name in PUBLIC_FILES}


def prepare(dataset: Path, receipt_path: Path) -> dict:
    label_path = dataset / SECRET_FILE
    if not label_path.is_file():
        raise SystemExit(f"V6 validation precommit refused; missing label file: {label_path}")
    quality = json.loads((dataset / "validation/dataset_quality.json").read_text(encoding="utf-8"))
    leakage = json.loads((dataset / "validation/leakage_audit.json").read_text(encoding="utf-8"))
    if not quality.get("hard_gate_passed") or not leakage.get("cross_split_passed"):
        raise SystemExit("V6 validation precommit refused; data-quality or leakage audit failed")
    receipt = {
        "protocol": "v6_locked_internal_validation_precommit_v1",
        "purpose": "freeze validation inputs before prediction; labels remain unread by localization",
        "dataset": dataset.relative_to(ROOT).as_posix(),
        "expected_events": 360,
        "expected_workbook_files": 720,
        "public_file_sha256": public_hashes(dataset),
        "workbook_inventory": inventory(dataset),
        "secret_label_file": SECRET_FILE,
        "secret_label_sha256": sha256(label_path),
        "v6_source_sha256": sha256(ROOT / "formulaguard/v6.py"),
        "v4_source_sha256": sha256(ROOT / "formulaguard/localize.py"),
        "method_spec_sha256": sha256(ROOT / "research/V6_METHOD_SPEC.md"),
        "git_commit_at_precommit": git_commit(),
        "predictions_present_at_precommit": (ROOT / "results/v6_validation_locked/predictions").exists(),
        "labels_semantically_inspected_by_precommit_script": False,
    }
    if receipt["predictions_present_at_precommit"]:
        raise SystemExit("V6 validation precommit refused; predictions already exist")
    public_rows = sum(1 for line in (dataset / "instances.jsonl").read_text(encoding="utf-8").splitlines() if line.strip())
    if public_rows != receipt["expected_events"] or receipt["workbook_inventory"]["count"] != receipt["expected_workbook_files"]:
        raise SystemExit("V6 validation precommit refused; expected 360 events and 720 clean/mutant workbook files")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return receipt


def verify_public(dataset: Path, receipt: dict) -> None:
    if public_hashes(dataset) != receipt["public_file_sha256"]:
        raise SystemExit("V6 validation public verification failed: public/audit file hash changed")
    if inventory(dataset) != receipt["workbook_inventory"]:
        raise SystemExit("V6 validation public verification failed: workbook inventory changed")
    checks = {
        "v6_source_sha256": ROOT / "formulaguard/v6.py",
        "v4_source_sha256": ROOT / "formulaguard/localize.py",
        "method_spec_sha256": ROOT / "research/V6_METHOD_SPEC.md",
    }
    for field, path in checks.items():
        if sha256(path) != receipt[field]:
            raise SystemExit(f"V6 validation public verification failed: {field} changed")


def verify_secret(dataset: Path, receipt: dict, prediction_root: Path) -> None:
    completion_path = prediction_root / "prediction_complete.json"
    if not completion_path.is_file():
        raise SystemExit("V6 validation label release refused: prediction completion is missing")
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    if not completion.get("complete") or not completion.get("full_ranking_audit_passed"):
        raise SystemExit("V6 validation label release refused: complete-ranking audit failed")
    if completion.get("instances") != 360:
        raise SystemExit("V6 validation label release refused: prediction count is not 360")
    if sha256(dataset / receipt["secret_label_file"]) != receipt["secret_label_sha256"]:
        raise SystemExit("V6 validation label release refused: secret label hash changed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "verify-public", "verify-secret"))
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--predictions", type=Path, default=ROOT / "results/v6_validation_locked/predictions")
    args = parser.parse_args()
    dataset, receipt_path = args.dataset.resolve(), args.receipt.resolve()
    if args.phase == "prepare":
        receipt = prepare(dataset, receipt_path)
    else:
        if not receipt_path.is_file():
            raise SystemExit("V6 validation precommit receipt is missing")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if args.phase == "verify-public":
            verify_public(dataset, receipt)
        else:
            verify_secret(dataset, receipt, args.predictions.resolve())
    print(receipt_path)
    print(f"V6 validation precommit phase passed: {args.phase}")


if __name__ == "__main__":
    main()
