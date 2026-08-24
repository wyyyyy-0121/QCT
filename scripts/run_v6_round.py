"""Orchestrate one full V6 A/B/C development round."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*parts, allow_gate_failure=False):
    command = [sys.executable, *map(str, parts)]
    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode and not (allow_gate_failure and completed.returncode == 2):
        raise SystemExit(completed.returncode)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("round", choices=("a", "b", "c"))
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    datasets = {
        "development": Path("data/v6_development"),
        "redteam": Path("data/v6_redteam"),
        "clean": Path("data/v6_clean"),
    }
    for profile, path in datasets.items():
        if not (path / "dataset_manifest.json").exists():
            run("scripts/build_v6_dataset.py", "--profile", profile, "--output", path)
    run("scripts/audit_v6_dataset.py", *datasets.values())
    root = Path(f"results/v6_development_{args.round}")
    resume = ["--resume"] if args.resume else []
    for layer in ("development", "redteam"):
        predictions = root / layer / "predictions"
        run("scripts/run_v6_predictions.py", "--benchmark", datasets[layer], "--output", predictions,
            "--variants", args.round, "--workers", args.workers, *resume)
        run("scripts/score_v6_predictions.py", "--benchmark", datasets[layer], "--predictions", predictions,
            "--output", root / layer)
        run("scripts/build_v6_report.py", "--results", root / layer, "--title", f"FormulaGuard V6-{args.round.upper()} {layer}")
    clean_predictions = root / "clean/predictions"
    run("scripts/run_v6_predictions.py", "--benchmark", datasets["clean"], "--output", clean_predictions,
        "--variants", args.round, "--workers", args.workers, "--clean", *resume)
    run("scripts/score_v6_clean.py", "--predictions", clean_predictions, "--output", root / "clean")
    run("scripts/run_v6_enron.py", "--variant", args.round, "--workers", args.workers,
        "--output", root / "enron", *resume)
    run("scripts/audit_v6_round.py", "--round", args.round, "--root", root, "--workers", args.workers,
        allow_gate_failure=True)
    print(f"V6-{args.round.upper()} development round finished: {root}")


if __name__ == "__main__":
    main()
