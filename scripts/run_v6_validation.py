"""Run the one-shot, all-variant locked internal V6 validation."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ABLATIONS = ["no_ffc", "no_bss", "no_d", "no_irg", "no_side_effect", "no_uniqueness", "v4_only", "semantics_only"]


def run(*parts, allow_selection_failure=False):
    completed = subprocess.run([sys.executable, *map(str, parts)], cwd=ROOT)
    if completed.returncode and not (allow_selection_failure and completed.returncode == 2):
        raise SystemExit(completed.returncode)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    for letter in "abc":
        if not Path(f"results/v6_development_{letter}/v6_round_audit.json").exists():
            raise SystemExit(f"Validation refused: V6-{letter.upper()} round audit is missing")
    datasets = {
        "development": Path("data/v6_development"),
        "validation": Path("data/v6_validation"),
        "redteam": Path("data/v6_redteam"),
        "clean": Path("data/v6_clean"),
    }
    if not (datasets["validation"] / "dataset_manifest.json").exists():
        raise SystemExit(
            "Validation refused: the precommitted validation dataset is missing; "
            "do not build labels inside the prediction command"
        )
    # This phase hashes only public manifests/audit receipts and workbooks.  It
    # deliberately does not open evaluation_labels.jsonl.
    run("scripts/precommit_v6_validation.py", "verify-public", "--dataset", datasets["validation"])
    root = Path("results/v6_validation_locked")
    resume = ["--resume"] if args.resume else []
    run("scripts/run_v6_predictions.py", "--benchmark", datasets["validation"], "--output", root / "predictions",
        "--variants", "a", "b", "c", "--ablations", *ABLATIONS, "--workers", args.workers, *resume)
    # Only a complete, audited 360-workbook ranking unlocks the precommitted
    # label hash and permits the scoring process to read labels.
    run("scripts/precommit_v6_validation.py", "verify-secret", "--dataset", datasets["validation"],
        "--predictions", root / "predictions")
    run("scripts/score_v6_predictions.py", "--benchmark", datasets["validation"], "--predictions", root / "predictions", "--output", root)
    run("scripts/build_v6_report.py", "--results", root, "--title", "FormulaGuard V6 Locked Internal Validation")
    run("scripts/run_v6_predictions.py", "--benchmark", datasets["clean"], "--output", root / "clean/predictions",
        "--variants", "a", "b", "c", "--workers", args.workers, "--clean", *resume)
    run("scripts/score_v6_clean.py", "--predictions", root / "clean/predictions", "--output", root / "clean")
    for letter in "abc":
        run("scripts/run_v6_enron.py", "--variant", letter, "--workers", args.workers,
            "--output", root / f"enron_{letter}", *resume)
    run("scripts/select_v6_variant.py", "--root", root, "--dataset", datasets["validation"], allow_selection_failure=True)
    print(f"V6 locked internal validation finished: {root}")


if __name__ == "__main__":
    main()
