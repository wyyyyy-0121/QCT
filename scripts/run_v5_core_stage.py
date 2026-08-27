"""Orchestrate V5-Core smoke, pilot, development, and locked validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ABLATIONS = (
    "no_regime", "no_exception", "no_structure", "no_causal",
    "no_graph", "no_replication", "no_harm", "weighted_sum",
)


def run(*parts: object, allow_gate_failure: bool = False) -> None:
    command = [sys.executable, *map(str, parts)]
    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode and not (allow_gate_failure and completed.returncode == 2):
        raise SystemExit(completed.returncode)


def node_executable() -> str:
    bundled = (
        Path.home() / ".cache/codex-runtimes/codex-primary-runtime"
        / "dependencies/node/bin/node.exe"
    )
    if bundled.exists():
        return str(bundled)
    resolved = shutil.which("node")
    if resolved:
        return resolved
    raise SystemExit("Node.js is required to build the V5-Core evidence workbook")


def build_outputs(results: Path, *, title: str, filename: str) -> None:
    run("scripts/build_v5_core_report.py", "--results", results, "--title", title)
    completed = subprocess.run(
        [
            node_executable(), "scripts/build_v5_core_results_workbook.mjs",
            "--results", str(results), "--output", str(Path("outputs") / filename),
        ],
        cwd=ROOT,
    )
    if completed.returncode:
        raise SystemExit(completed.returncode)


def ensure_dataset(profile: str, path: Path, *, limit: int | None = None) -> None:
    if (path / "dataset_build_complete.json").exists():
        return
    parts: list[object] = ["scripts/build_v5_core_dataset.py", "--profile", profile, "--output", path]
    if limit is not None:
        parts.extend(["--limit", limit])
    run(*parts)


def predict(benchmark: Path, output: Path, workers: int, *extra: object, resume: bool = False) -> None:
    parts: list[object] = [
        "scripts/run_v5_core_predictions.py", "--benchmark", benchmark,
        "--output", output, "--workers", workers, *extra,
    ]
    if resume:
        parts.append("--resume")
    run(*parts)


def materialize(source: Path, output: Path, config_root: Path) -> None:
    run(
        "scripts/materialize_v5_core_learned.py",
        "--input", source,
        "--config", config_root / "v5_core_learned_config.json",
        "--rule-config", config_root / "v5_core_rule_config.json",
        "--output", output,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("smoke", "pilot", "development", "validation_lock", "validation_score"))
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")

    if args.stage == "smoke":
        data = Path("data/v5_core_smoke")
        clean = Path("data/v5_core_smoke_clean")
        ensure_dataset("smoke", data)
        ensure_dataset("clean", clean, limit=24)
        root = Path("results/v5_core_smoke")
        run(
            "scripts/audit_v5_core_dataset.py", data, clean,
            "--output", root / "dataset_audit.json",
        )
        predict(data, root / "raw_predictions", args.workers, "--baselines", resume=args.resume)
        predict(clean, root / "raw_clean_predictions", args.workers, "--clean", resume=args.resume)
        config = root / "config"
        run(
            "scripts/train_v5_core_ranker.py", "--benchmark", data,
            "--predictions", root / "raw_predictions",
            "--clean-predictions", root / "raw_clean_predictions", "--output", config,
        )
        config_args = (
            "--rule-config", config / "v5_core_rule_config.json",
            "--learned-config", config / "v5_core_learned_config.json",
        )
        predict(data, root / "predictions", args.workers, "--baselines", *config_args, resume=args.resume)
        predict(clean, root / "clean_predictions", args.workers, "--clean", *config_args, resume=args.resume)
        run(
            "scripts/score_v5_core_predictions.py", "--benchmark", data,
            "--predictions", root / "predictions",
            "--clean-predictions", root / "clean_predictions", "--output", root,
        )
        build_outputs(
            root, title="FormulaGuard V5-Core 24-case engineering smoke",
            filename="FormulaGuard_v5_core_smoke_results.xlsx",
        )
        print(f"V5-Core smoke finished: {root}")
        return

    if args.stage == "pilot":
        data = Path("data/v5_core_pilot")
        clean = Path("data/v5_core_pilot_clean")
        ensure_dataset("pilot", data)
        ensure_dataset("clean", clean, limit=48)
        root = Path("results/v5_core_pilot")
        run(
            "scripts/audit_v5_core_dataset.py", data, clean,
            "--output", root / "dataset_audit.json",
        )
        predict(data, root / "raw_predictions", args.workers, "--baselines", resume=args.resume)
        predict(clean, root / "raw_clean_predictions", args.workers, "--clean", resume=args.resume)
        config = root / "config"
        run(
            "scripts/train_v5_core_ranker.py", "--benchmark", data,
            "--predictions", root / "raw_predictions",
            "--clean-predictions", root / "raw_clean_predictions", "--output", config,
        )
        config_args = (
            "--rule-config", config / "v5_core_rule_config.json",
            "--learned-config", config / "v5_core_learned_config.json",
        )
        predict(data, root / "predictions", args.workers, "--baselines", *config_args, resume=args.resume)
        predict(clean, root / "clean_predictions", args.workers, "--clean", *config_args, resume=args.resume)
        run(
            "scripts/score_v5_core_predictions.py", "--benchmark", data,
            "--predictions", root / "predictions", "--clean-predictions", root / "clean_predictions",
            "--output", root,
        )
        build_outputs(
            root, title="FormulaGuard V5-Core 240-case mechanism pilot",
            filename="FormulaGuard_v5_core_pilot_results.xlsx",
        )
        print(f"V5-Core 240-case pilot finished: {root}")
        return

    development = Path("data/v5_core_development")
    redteam = Path("data/v5_core_redteam")
    clean = Path("data/v5_core_clean")
    ensure_dataset("development", development)
    ensure_dataset("redteam", redteam)
    ensure_dataset("clean", clean)
    dataset_audit = Path("results/v5_core_dataset_audit.json")
    run(
        "scripts/audit_v5_core_dataset.py", development, redteam, clean,
        "--output", dataset_audit,
    )

    if args.stage == "development":
        root = Path("results/v5_core_development")
        predict(development, root / "raw_development", args.workers, "--baselines", resume=args.resume)
        predict(redteam, root / "raw_redteam", args.workers, "--baselines", resume=args.resume)
        predict(clean, root / "raw_clean", args.workers, "--clean", "--limit", 240, resume=args.resume)
        config = root / "config"
        run(
            "scripts/train_v5_core_ranker.py", "--benchmark", development,
            "--predictions", root / "raw_development", "--clean-predictions", root / "raw_clean",
            "--output", config,
        )
        config_args = (
            "--rule-config", config / "v5_core_rule_config.json",
            "--learned-config", config / "v5_core_learned_config.json",
        )
        predict(
            development, root / "development_predictions", args.workers,
            "--baselines", *config_args, "--ablations", *ABLATIONS,
            resume=args.resume,
        )
        predict(
            redteam, root / "redteam_predictions", args.workers,
            "--baselines", *config_args, "--ablations", *ABLATIONS,
            resume=args.resume,
        )
        predict(
            clean, root / "clean_predictions", args.workers,
            "--clean", "--limit", 240, *config_args, resume=args.resume,
        )
        run(
            "scripts/score_v5_core_predictions.py", "--benchmark", development,
            "--predictions", root / "development_predictions",
            "--clean-predictions", root / "clean_predictions", "--output", root / "development",
        )
        run(
            "scripts/score_v5_core_predictions.py", "--benchmark", redteam,
            "--predictions", root / "redteam_predictions", "--output", root / "redteam",
        )
        build_outputs(
            root / "development", title="FormulaGuard V5-Core development evidence",
            filename="FormulaGuard_v5_core_development_results.xlsx",
        )
        run(
            "scripts/run_v5_core_enron.py",
            "--rule-config", config / "v5_core_rule_config.json",
            "--learned-config", config / "v5_core_learned_config.json",
            "--output", root / "enron", "--workers", args.workers,
            *(["--resume"] if args.resume else []),
        )
        run(
            "scripts/audit_v5_core_development.py", "--root", root,
            "--dataset-audit", dataset_audit,
            allow_gate_failure=True,
        )
        print(f"V5-Core development finished: {root}")
        return

    # Locked validation: all heads and ablations are generated before labels are read.
    validation = Path("data/v5_core_validation")
    ensure_dataset("validation", validation)
    validation_dataset_audit = Path("results/v5_core_validation/dataset_audit.json")
    config = Path("results/v5_core_development/config")
    if not (config / "v5_core_learned_config.json").exists():
        raise SystemExit("Run the development stage before locked validation")
    root = Path("results/v5_core_validation")
    config_args = (
        "--rule-config", config / "v5_core_rule_config.json",
        "--learned-config", config / "v5_core_learned_config.json",
    )
    if args.stage == "validation_lock":
        public_audit = root / "public_input_audit.json"
        run(
            "scripts/audit_v5_core_public_inputs.py", validation, clean,
            "--output", public_audit,
        )
        predict(
            validation, root / "predictions", args.workers,
            "--baselines", *config_args, "--ablations", *ABLATIONS,
            resume=args.resume,
        )
        predict(
            clean, root / "clean_predictions", args.workers,
            "--clean", "--offset", 240, "--limit", 120, *config_args,
            resume=args.resume,
        )
        locked_files = [
            root / "predictions/prediction_complete.json",
            root / "predictions/prediction_metadata.json",
            root / "clean_predictions/prediction_complete.json",
            root / "clean_predictions/prediction_metadata.json",
            public_audit,
            config / "v5_core_rule_config.json",
            config / "v5_core_learned_config.json",
        ]
        receipt = {
            "protocol": "v5_core_internal_validation_prediction_lock_v1",
            "labels_read": [],
            "hashes": {
                str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in locked_files
            },
            "labels_may_now_be_read_by_separate_score_command": True,
        }
        (root / "prediction_lock.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(f"V5-Core locked predictions written: {root / 'prediction_lock.json'}")
        return
    if not (root / "prediction_lock.json").exists():
        raise SystemExit("Scoring refused: run validation_lock successfully first")
    lock_receipt = json.loads((root / "prediction_lock.json").read_text(encoding="utf-8"))
    for locked_path, expected_hash in lock_receipt.get("hashes", {}).items():
        path = Path(locked_path)
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            raise SystemExit(f"Scoring refused: locked input changed: {path}")
    run(
        "scripts/audit_v5_core_dataset.py", development, redteam, clean, validation,
        "--output", validation_dataset_audit,
    )
    run(
        "scripts/score_v5_core_predictions.py", "--benchmark", validation,
        "--predictions", root / "predictions", "--clean-predictions", root / "clean_predictions",
        "--output", root,
    )
    run(
        "scripts/audit_v5_core_validation.py", "--summary", root / "summary.json",
        "--dataset-audit", validation_dataset_audit,
        "--training-audit", config / "training_audit.json",
        "--enron", Path("results/v5_core_development/enron/enron_summary.json"),
        "--output", root / "selection_audit.json",
        allow_gate_failure=True,
    )
    build_outputs(
        root, title="FormulaGuard V5-Core locked internal validation",
        filename="FormulaGuard_v5_core_validation_results.xlsx",
    )
    print(f"V5-Core locked validation scored: {root}")


if __name__ == "__main__":
    main()
