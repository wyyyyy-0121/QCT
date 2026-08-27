"""Write the immutable V5-Core configuration after locked validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v5_core import v5_core_default_parameters


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_path(path: Path) -> Path:
    """Resolve CLI paths against the repository, not the caller's shell."""
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def manifest_key(path: Path) -> str:
    """Use stable repository-relative keys for every frozen artifact."""
    return repo_path(path).relative_to(ROOT.resolve()).as_posix()


def git(*args: str) -> str:
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe"
    executable = "git" if subprocess.run(["where", "git"], capture_output=True).returncode == 0 else str(bundled)
    return subprocess.check_output([executable, *args], cwd=ROOT, text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, default=Path("results/v5_core_validation/selection_audit.json"))
    parser.add_argument("--rule-config", type=Path, default=Path("results/v5_core_development/config/v5_core_rule_config.json"))
    parser.add_argument("--learned-config", type=Path, default=Path("results/v5_core_development/config/v5_core_learned_config.json"))
    parser.add_argument("--development-audit", type=Path, default=Path("results/v5_core_development/development_audit.json"))
    parser.add_argument("--validation-root", type=Path, default=Path("results/v5_core_validation"))
    parser.add_argument("--output", type=Path, default=Path("research/frozen_config_v5_core.json"))
    args = parser.parse_args()
    if git("status", "--porcelain"):
        raise SystemExit("Freeze refused: commit all V5-Core changes first")

    selection_path = repo_path(args.selection)
    rule_path = repo_path(args.rule_config)
    learned_path = repo_path(args.learned_config)
    development_audit_path = repo_path(args.development_audit)
    validation_root = repo_path(args.validation_root)
    output_path = repo_path(args.output)

    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selected = selection.get("selected_head")
    if not selected:
        raise SystemExit("Freeze refused: locked validation did not promote V5")
    if selection.get("no_parameter_changes_after_this_receipt") is not True:
        raise SystemExit("Freeze refused: selection receipt lacks the no-retuning commitment")
    rule = json.loads(rule_path.read_text(encoding="utf-8"))
    learned = json.loads(learned_path.read_text(encoding="utf-8"))
    source_paths = [
        ROOT / "formulaguard/v5_core.py",
        ROOT / "formulaguard/api.py",
        ROOT / "formulaguard/formula.py",
        ROOT / "formulaguard/workbook.py",
        ROOT / "formulaguard/localize.py",
        ROOT / "scripts/run_v5_core_predictions.py",
        ROOT / "scripts/score_v5_core_predictions.py",
        ROOT / "scripts/audit_v5_core_validation.py",
        ROOT / "research/V5_CORE_METHOD_SPEC.md",
    ]
    historical_paths = [
        ROOT / "formulaguard/v5.py",
        ROOT / "formulaguard/v52.py",
        ROOT / "formulaguard/v6.py",
    ]
    data_paths = [
        ROOT / "data/v5_core_development/dataset_manifest.json",
        ROOT / "data/v5_core_development/dataset_build_complete.json",
        ROOT / "data/v5_core_redteam/dataset_manifest.json",
        ROOT / "data/v5_core_redteam/dataset_build_complete.json",
        ROOT / "data/v5_core_clean/dataset_manifest.json",
        ROOT / "data/v5_core_clean/dataset_build_complete.json",
        ROOT / "data/v5_core_validation/dataset_manifest.json",
        ROOT / "data/v5_core_validation/dataset_build_complete.json",
    ]
    evidence_paths = [
        development_audit_path,
        ROOT / "results/v5_core_dataset_audit.json",
        ROOT / "results/v5_core_development/config/training_audit.json",
        ROOT / "results/v5_core_development/enron/enron_summary.json",
        validation_root / "public_input_audit.json",
        validation_root / "prediction_lock.json",
        validation_root / "dataset_audit.json",
        validation_root / "summary.json",
        validation_root / "selection_audit.json",
    ]
    required = [*source_paths, *historical_paths, *data_paths, *evidence_paths]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"Freeze refused: required evidence is missing: {missing[:5]}")
    if selection_path != (validation_root / "selection_audit.json").resolve():
        raise SystemExit("Freeze refused: selection must belong to the supplied validation root")
    payload = {
        "protocol": "v5_core_immutable_freeze_v2",
        "model_version": "v5-core-r1",
        "selected_head": selected,
        "selected_config": learned if selected == "v5_learned" else rule,
        "rule_config": rule,
        "learned_config": learned,
        "selection_receipt": manifest_key(selection_path),
        "selection_sha256": sha256(selection_path),
        "parameters": v5_core_default_parameters(),
        "source_sha256": {manifest_key(path): sha256(path) for path in source_paths},
        "historical_source_sha256": {
            manifest_key(path): sha256(path) for path in historical_paths
        },
        "data_manifest_sha256": {
            manifest_key(path): sha256(path) for path in data_paths
        },
        "evidence_sha256": {
            manifest_key(path): sha256(path) for path in evidence_paths
        },
        "git_commit": git("rev-parse", "HEAD"),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "default_workers": 24,
            "random_seed": 20260827,
        },
        "historical_models_modified": False,
        "third_party_results_seen": False,
        "post_validation_retuning_allowed": False,
        "tag_to_create": "v5-core-lock",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
