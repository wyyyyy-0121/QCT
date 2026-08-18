"""Freeze v4-r1 only after the one permitted retrospective revision run."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.localize import v4_default_parameters
from scripts.run_external_evaluation import sha256_file


REQUIRED_RESULT_FILES = (
    "external_raw.csv",
    "external_summary.csv",
    "external_analysis.json",
    "external_dataset_audit.json",
    "external_run_metadata.json",
    "external_exclusions.csv",
    "v4_development_audit.json",
    "v4_revision_comparison.json",
)


def verify_model_source_hashes(metadata: dict[str, object], repository_root: Path) -> None:
    recorded = metadata.get("source_sha256")
    if not isinstance(recorded, dict) or not recorded:
        raise ValueError("Run metadata has no model source hashes")
    for relative, expected in recorded.items():
        path = repository_root / str(relative)
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"Model source changed after the revision run: {relative}")


def build_frozen_config(results: Path, repository_root: Path) -> dict[str, object]:
    missing = [name for name in REQUIRED_RESULT_FILES if not (results / name).is_file()]
    if missing:
        raise ValueError("Missing revision result files: " + ", ".join(missing))
    metadata = json.loads((results / "external_run_metadata.json").read_text(encoding="utf-8"))
    audit = json.loads((results / "v4_development_audit.json").read_text(encoding="utf-8"))
    dataset_audit = json.loads((results / "external_dataset_audit.json").read_text(encoding="utf-8"))
    if metadata.get("v4_parameters") != v4_default_parameters():
        raise ValueError("Revision run parameters do not match the current v4-r1 implementation")
    if audit.get("evaluated_events") != 30 or audit.get("row_count") != 150:
        raise ValueError("Revision result matrix is not the expected 30 events x 5 methods")
    if not audit.get("development_decision_ready"):
        raise ValueError("Revision development audit is not decision-ready")
    if dataset_audit.get("methods") != [
        "graph", "pattern", "formulaguard", "formulaguard_v3", "formulaguard_v4"
    ]:
        raise ValueError("Revision method set differs from the registered comparison")
    verify_model_source_hashes(metadata, repository_root)
    with (results / "external_raw.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 150 or len({(row["instance_id"], row["method"]) for row in rows}) != 150:
        raise ValueError("Revision raw matrix has missing or duplicate event-method rows")
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repository_root,
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"Unable to record Git commit: {exc}") from exc
    return {
        "model_version": "v4",
        "implementation_version": "v4-dev-r1",
        "freeze_policy": "one_retrospective_revision_then_independent_blind_validation",
        "candidate_limit": int(metadata["candidate_limit"]),
        "v4_parameters": metadata["v4_parameters"],
        "manifest_sha256": metadata["manifest_sha256"],
        "model_source_sha256": metadata["source_sha256"],
        "development_result_sha256": {
            name: sha256_file(results / name) for name in REQUIRED_RESULT_FILES
        },
        "git_commit": commit,
        "retrospective_only": True,
        "blind_labels_seen": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze the FormulaGuard-v4-r1 model")
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[1]
    try:
        config = build_frozen_config(args.results.resolve(), repository_root)
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"V4 freeze refused: {exc}") from exc
    if args.output.exists():
        raise SystemExit(f"V4 freeze refused: output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
