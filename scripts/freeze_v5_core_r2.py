"""Write the immutable R2-R1 configuration after pressure-safety approval."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v5_core_r2 import v5_core_r2_default_parameters


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_executable() -> str:
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe"
    executable = shutil.which("git") or (str(bundled) if bundled.is_file() else None)
    if executable is None:
        raise SystemExit("Freeze refused: Git executable is unavailable")
    return executable


def git(*arguments: str) -> str:
    return subprocess.check_output([git_executable(), *arguments], cwd=ROOT, text=True).strip()


def repo_path(path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def key(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--development-audit", type=Path,
        default=Path("results/v5_core_r2_r1_retrospective_full/r2_retrospective_audit.json"),
    )
    parser.add_argument(
        "--pressure-audit", type=Path,
        default=Path("results/v5_core_r2_r1_pressure/pressure_safety_audit.json"),
    )
    parser.add_argument("--base-config", type=Path, default=Path("research/V5_CORE_R2_R1_CONFIG.json"))
    parser.add_argument("--output", type=Path, default=Path("research/frozen_config_v5_core_r2.json"))
    args = parser.parse_args()
    if git("status", "--porcelain"):
        raise SystemExit("Freeze refused: commit all R2 implementation and protocol changes first")

    development_path = repo_path(args.development_audit)
    pressure_path = repo_path(args.pressure_audit)
    base_config_path = repo_path(args.base_config)
    output_path = repo_path(args.output)
    for path in (development_path, pressure_path, base_config_path):
        if not path.is_file():
            raise SystemExit(f"Freeze refused: required evidence is missing: {path}")
    development = json.loads(development_path.read_text(encoding="utf-8"))
    pressure = json.loads(pressure_path.read_text(encoding="utf-8"))
    base_config = json.loads(base_config_path.read_text(encoding="utf-8"))
    if pressure.get("pressure_safety_passed") is not True:
        raise SystemExit("Freeze refused: R2-R1 pressure safety did not pass")
    if pressure.get("eligible_for_new_independent_confirmation") is not True:
        raise SystemExit("Freeze refused: pressure receipt does not permit independent confirmation")
    if pressure.get("independent_evidence") is not False:
        raise SystemExit("Freeze refused: pressure receipt misstates its evidence tier")
    workbook_null = development.get("cross_workbook_null", {})
    selected_name = workbook_null.get("selected")
    selected = workbook_null.get("variants", {}).get(selected_name, {})
    clean_null_scores = selected.get("clean_null_scores", [])
    if not selected_name or len(clean_null_scores) != 360:
        raise SystemExit("Freeze refused: selected 360-workbook clean null is incomplete")
    if selected.get("clean_false_alarm_rate", 1.0) > 0.10:
        raise SystemExit("Freeze refused: selected clean-null false-positive rate exceeds 10%")
    if selected.get("error_alarm_recall", 0.0) < 0.80:
        raise SystemExit("Freeze refused: selected clean-null error recall is below 80%")

    frozen_runtime = {
        **v5_core_r2_default_parameters(),
        **base_config,
        "model_version": "v5-core-r2-r1-frozen",
        "wcn_variant": selected["config_name"],
        "clean_null_tail": float(selected.get("tail_threshold", 0.10)),
        "clean_null_scores": [float(value) for value in clean_null_scores],
    }
    source_paths = [
        ROOT / "formulaguard/v5_core_r2.py",
        ROOT / "formulaguard/api.py",
        ROOT / "scripts/run_v5_core_r2_retrospective.py",
        ROOT / "scripts/run_v5_core_r2_pressure.py",
        ROOT / "scripts/audit_v5_core_r2_pressure.py",
        ROOT / "scripts/run_v5_core_r2_predictions.py",
        ROOT / "scripts/prepare_v5_core_r2_confirmation_pack.py",
        ROOT / "scripts/freeze_v5_core_r2.py",
        ROOT / "scripts/lock_v5_core_r2_confirmation.py",
        ROOT / "scripts/score_v5_core_r2_confirmation.py",
        ROOT / "scripts/run_v5_core_r2_performance.py",
        ROOT / "research/V5_CORE_R2_METHOD_SPEC.md",
        ROOT / "research/V5_CORE_R2_NOVELTY_AUDIT.md",
        ROOT / "research/R2_RELATED_WORK_EVIDENCE.md",
        ROOT / "research/REFERENCES_R2.bib",
        ROOT / "research/V5_CORE_R2_R1_GATE_INTERPRETATION.md",
        ROOT / "research/V5_CORE_R2_CONFIRMATION_PROTOCOL.md",
    ]
    data_paths = [
        ROOT / "data/v5_core_validation/dataset_manifest.json",
        ROOT / "data/v5_core_clean/dataset_manifest.json",
    ]
    evidence_paths = [
        development_path,
        pressure_path,
        base_config_path,
        ROOT / "results/v5_core_r2_r1_pressure/historical_100/pressure_summary.json",
        ROOT / "results/v5_core_r2_r1_pressure/enron/pressure_summary.json",
    ]
    required = [*source_paths, *data_paths, *evidence_paths]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"Freeze refused: required source/data/evidence is missing: {missing[:5]}")
    payload = {
        "protocol": "v5_core_r2_immutable_freeze_v1",
        "model_version": "v5-core-r2-r1",
        "architecture": "dual_null_causal_attribution_with_adaptive_exception_release",
        "runtime_config": frozen_runtime,
        "selected_clean_null": {
            "variant": selected_name,
            "config_name": selected["config_name"],
            "formula": selected["formula"],
            "clean_false_alarm_rate": selected["clean_false_alarm_rate"],
            "error_alarm_recall": selected["error_alarm_recall"],
            "calibration_events": len(clean_null_scores),
        },
        "original_preregistered_gate_passed": bool(
            development.get("gates", {}).get("hard_gate_passed", False)
        ),
        "original_failed_gates_preserved": development.get("gates", {}).get("failed_gates", []),
        "pressure_safety_passed": True,
        "source_sha256": {key(path): sha256(path) for path in source_paths},
        "data_manifest_sha256": {key(path): sha256(path) for path in data_paths},
        "evidence_sha256": {key(path): sha256(path) for path in evidence_paths},
        "git_commit": git("rev-parse", "HEAD"),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "default_workers": 24,
            "bootstrap_seed": 20260827,
        },
        "historical_models_modified": False,
        "confirmation_results_seen": False,
        "post_confirmation_retuning_allowed": False,
        "tag_to_create": "v5-core-r2-lock",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_path)
    print("Commit this file, create tag v5-core-r2-lock, and push the branch and tag before PUBLIC release.")


if __name__ == "__main__":
    main()
