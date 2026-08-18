"""Freeze the selected V5.2 variant after all three development rounds."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.v52 import v52_default_parameters
from scripts.run_external_evaluation import sha256_file


SOURCE_FILES = (
    "formulaguard/v52.py",
    "formulaguard/localize.py",
    "scripts/run_v52_labeled_development.py",
    "scripts/run_v52_clean_controls.py",
    "scripts/build_v52_redteam_manifest.py",
    "scripts/build_v52_stress_workbooks.py",
    "scripts/audit_v52_round.py",
    "scripts/select_v52_variant.py",
    "scripts/run_v4_v52_blind_lock.py",
    "scripts/score_v4_v52_blind.py",
    "scripts/v52_blind_protocol.py",
    "research/V52_METHOD_SPEC.md",
)


def _git_executable() -> str:
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe"
    return str(bundled) if bundled.is_file() else "git"


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze a selected V5.2 variant")
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"V5.2 freeze refused: output already exists: {args.output}")
    root = Path(__file__).resolve().parents[1]
    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    variant = selection.get("selected_variant")
    if selection.get("decision") != "v52_selected_for_freeze" or variant not in {"a", "b", "c"}:
        raise SystemExit("V5.2 freeze refused: no eligible variant was selected")
    missing = [relative for relative in SOURCE_FILES if not (root / relative).is_file()]
    if missing:
        raise SystemExit("V5.2 freeze refused: missing source files: " + ", ".join(missing))
    git = _git_executable()
    try:
        status = subprocess.run(
            [git, "status", "--porcelain", "--untracked-files=no"], cwd=root,
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        if status:
            raise ValueError("tracked worktree changes are present")
        commit = subprocess.run(
            [git, "rev-parse", "HEAD"], cwd=root, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        raise SystemExit(f"V5.2 freeze refused: {exc}") from exc
    config = {
        "model_version": "v5.2",
        "selected_variant": variant,
        "base_model": "frozen_v4_r1",
        "freeze_policy": "three_predeclared_development_rounds_then_joint_independent_lock",
        "candidate_limit": 15,
        "v52_parameters": v52_default_parameters(variant),
        "selection_receipt": str(args.selection.resolve()),
        "selection_receipt_sha256": sha256_file(args.selection),
        "round_audit_sha256": {
            key: value["audit_sha256"] for key, value in selection["rounds"].items()
        },
        "model_source_sha256": {
            relative: sha256_file(root / relative) for relative in SOURCE_FILES
        },
        "git_commit": commit,
        "independent_labels_seen": False,
        "independent_validation_required": True,
        "claim_boundary": "supplemental_review_slot_only_review6_is_not_top5",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
