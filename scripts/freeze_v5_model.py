"""Freeze V5 only after every preregistered development gate passes."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.v5 import v5_default_parameters
from scripts.run_external_evaluation import sha256_file
from scripts.verify_v5_prerequisites import verify as verify_prerequisites


MODEL_FILES = (
    "formulaguard/v5.py",
    "formulaguard/cli.py",
    "scripts/run_v5_external_evaluation.py",
    "scripts/merge_v5_development_results.py",
    "scripts/run_v5_clean_controls.py",
    "scripts/audit_v5_development.py",
    "scripts/verify_v5_prerequisites.py",
    "scripts/freeze_v5_model.py",
    "research/V5_METHOD_SPEC.md",
    "research/V5_METHOD_SPEC_AMENDMENT_1.md",
    "research/V5_REFERENCE_RECEIPT.json",
    "data/v5_development/manifest.csv",
    "run_v5_development.cmd",
    "run_v5_freeze.cmd",
)


def _git_executable() -> str:
    if executable := shutil.which("git"):
        return executable
    bundled = (
        Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime"
        / "dependencies" / "native" / "git" / "cmd" / "git.exe"
    )
    if bundled.is_file():
        return str(bundled)
    raise ValueError("Git executable is unavailable; V5 freeze needs a recorded source commit")


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        [_git_executable(), *args], cwd=root, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_metadata(metadata: dict[str, object], root: Path) -> None:
    if metadata.get("v5_parameters") != v5_default_parameters():
        raise ValueError("V5 run parameters differ from the preregistered implementation")
    if int(metadata.get("candidate_limit", 0)) != 15:
        raise ValueError("V5 candidate limit is not 15")
    if int(metadata.get("engineering_limit", -1)) != 0:
        raise ValueError("Engineering-limited output cannot be frozen")
    recorded = metadata.get("source_sha256")
    if not isinstance(recorded, dict) or not recorded:
        raise ValueError("V5 metadata has no source hashes")
    for relative, expected in recorded.items():
        path = root / str(relative)
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"V5 source changed after development execution: {relative}")


def build_config(args: argparse.Namespace, root: Path) -> dict[str, object]:
    audit = _load(args.audit)
    prerequisite = _load(args.prerequisite_audit)
    if audit.get("freeze_permitted") is not True:
        raise ValueError("Preregistered V5 gates did not all pass")
    if prerequisite.get("passed") is not True:
        raise ValueError("V5 prerequisite integrity audit failed")
    current_prerequisite = verify_prerequisites(
        root, root / "research" / "V5_REFERENCE_RECEIPT.json"
    )
    if current_prerequisite.get("passed") is not True:
        raise ValueError("Frozen V4 or locked V5 reference inputs changed")

    synthetic_metadata = _load(args.synthetic / "v5_run_metadata.json")
    enron_metadata = _load(args.enron / "v5_run_metadata.json")
    clean_summary = _load(args.clean / "v5_clean_summary.json")
    _verify_metadata(synthetic_metadata, root)
    _verify_metadata(enron_metadata, root)
    if clean_summary.get("v5_parameters") != v5_default_parameters():
        raise ValueError("Clean-control parameters differ from V5")
    if int(clean_summary.get("engineering_limit", -1)) != 0:
        raise ValueError("Limited clean-control output cannot be frozen")
    if sha256_file(args.clean / "v5_clean_controls.csv") != clean_summary.get("results_sha256"):
        raise ValueError("Clean-control CSV changed after summary creation")

    result_files = [
        args.synthetic / "v5_raw.csv",
        args.synthetic / "v5_summary.csv",
        args.synthetic / "v5_run_metadata.json",
        args.synthetic / "external_raw.csv",
        args.synthetic / "external_raw_merge_receipt.json",
        args.enron / "v5_raw.csv",
        args.enron / "v5_summary.csv",
        args.enron / "v5_run_metadata.json",
        args.enron / "external_raw.csv",
        args.enron / "external_raw_merge_receipt.json",
        args.clean / "v5_clean_controls.csv",
        args.clean / "v5_clean_summary.json",
        args.prerequisite_audit,
        args.audit,
    ]
    missing = [str(path) for path in result_files if not path.is_file()]
    if missing:
        raise ValueError("Missing V5 evidence files: " + ", ".join(missing))

    for directory in (args.synthetic, args.enron):
        receipt = _load(directory / "external_raw_merge_receipt.json")
        if receipt.get("reference_rows_recomputed") is not False:
            raise ValueError(f"Reference rows were not locked in {directory}")
        if sha256_file(directory / "external_raw.csv") != receipt.get("combined_sha256"):
            raise ValueError(f"Merged result changed after receipt creation: {directory}")

    status = _git(root, "status", "--porcelain", "--", *MODEL_FILES)
    if status:
        raise ValueError("V5 source/protocol files must be committed before freezing: " + status)
    commit = _git(root, "rev-parse", "HEAD")
    return {
        "model_version": "v5",
        "implementation_version": "v5-pcg-r1",
        "freeze_policy": "single_preregistered_development_run_then_new_independent_validation",
        "candidate_limit": 15,
        "v5_parameters": v5_default_parameters(),
        "base_frozen_config_sha256": sha256_file(root / "research/frozen_config_v4.json"),
        "method_spec_sha256": sha256_file(root / "research/V5_METHOD_SPEC.md"),
        "method_spec_amendment_sha256": sha256_file(
            root / "research/V5_METHOD_SPEC_AMENDMENT_1.md"
        ),
        "reference_receipt_sha256": sha256_file(root / "research/V5_REFERENCE_RECEIPT.json"),
        "source_sha256": {
            relative: sha256_file(root / relative) for relative in MODEL_FILES
        },
        "development_result_sha256": {
            str(path.relative_to(root)).replace("\\", "/"): sha256_file(path)
            for path in result_files
        },
        "git_commit": commit,
        "development_identity": "retrospective_and_safety_regression_not_confirmatory",
        "confirmatory_validation_pending": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze FormulaGuard V5")
    parser.add_argument("--synthetic", type=Path, required=True)
    parser.add_argument("--enron", type=Path, required=True)
    parser.add_argument("--clean", type=Path, required=True)
    parser.add_argument("--prerequisite-audit", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.output.exists():
        raise SystemExit(f"V5 freeze refused: output already exists: {args.output}")
    try:
        config = build_config(args, root)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"V5 freeze refused: {exc}") from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
