"""Summarize the evidence state of the full V5-Core R2 protocol.

This auditor never runs a model and never converts development evidence into
independent evidence.  It distinguishes a terminal negative result from a
successful promotion so that a partial receipt cannot be presented as project
completion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def git_executable() -> str | None:
    bundled = (
        Path.home()
        / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe"
    )
    return shutil.which("git") or (str(bundled) if bundled.is_file() else None)


def tag_exists(tag: str) -> bool:
    executable = git_executable()
    if executable is None:
        return False
    completed = subprocess.run(
        [executable, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"],
        cwd=ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0


def valid_development_receipt(value: dict | None) -> bool:
    if not value:
        return False
    gates = value.get("gates", {})
    return (
        value.get("protocol") == "v5_core_r2_retrospective_audit_v2"
        and value.get("development_only") is True
        and value.get("independent_evidence") is False
        and int(value.get("errors", -1)) == 480
        and int(value.get("clean", -1)) == 360
        and int(value.get("workers", -1)) == 24
        and gates.get("hard_gate_passed") is False
        and gates.get("failed_gates") == ["improvement_spans_at_least_four_error_types"]
    )


def valid_pressure_receipt(value: dict | None) -> bool:
    if not value:
        return False
    return (
        value.get("protocol") == "v5_core_r2_r1_pressure_safety_decision_v1"
        and value.get("development_only") is True
        and value.get("independent_evidence") is False
        and isinstance(value.get("gates"), dict)
        and isinstance(value.get("pressure_safety_passed"), bool)
        and isinstance(value.get("eligible_for_new_independent_confirmation"), bool)
    )


def valid_freeze(value: dict | None, pressure: dict | None, path: Path) -> bool:
    if not value or not pressure:
        return False
    return (
        value.get("protocol") == "v5_core_r2_immutable_freeze_v1"
        and value.get("pressure_safety_passed") is True
        and value.get("confirmation_results_seen") is False
        and value.get("post_confirmation_retuning_allowed") is False
        and pressure.get("eligible_for_new_independent_confirmation") is True
        and path.is_file()
        and tag_exists("v5-core-r2-lock")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--development",
        type=Path,
        default=Path("results/v5_core_r2_r1_retrospective_full/r2_retrospective_audit.json"),
    )
    parser.add_argument(
        "--pressure",
        type=Path,
        default=Path("results/v5_core_r2_r1_pressure/pressure_safety_audit.json"),
    )
    parser.add_argument(
        "--freeze",
        type=Path,
        default=Path("research/frozen_config_v5_core_r2.json"),
    )
    parser.add_argument(
        "--third-party-precommit",
        type=Path,
        default=Path(r"D:\FormulaGuard_R2_ThirdParty\third_party_precommit.json"),
    )
    parser.add_argument(
        "--prediction-lock",
        type=Path,
        default=Path("results/v5_core_r2_confirmation_locked/prediction_lock.json"),
    )
    parser.add_argument(
        "--confirmation-score",
        type=Path,
        default=Path("results/v5_core_r2_confirmation_scored/confirmation_summary.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/v5_core_r2_completion_audit.json"),
    )
    args = parser.parse_args()

    development = read_json(args.development)
    pressure = read_json(args.pressure)
    freeze = read_json(args.freeze)
    precommit = read_json(args.third_party_precommit)
    prediction_lock = read_json(args.prediction_lock)
    score = read_json(args.confirmation_score)

    checks = {
        "development_receipt_valid": valid_development_receipt(development),
        "pressure_receipt_valid": valid_pressure_receipt(pressure),
        "pressure_eligible_for_confirmation": bool(
            pressure and pressure.get("eligible_for_new_independent_confirmation") is True
        ),
        "immutable_freeze_and_tag_valid": valid_freeze(freeze, pressure, args.freeze),
        "third_party_precommit_valid": bool(
            precommit
            and precommit.get("protocol") == "v5_core_r2_third_party_precommit_v1"
            and int(precommit.get("total_cases", -1)) == 780
            and int(precommit.get("error_cases", -1)) == 600
            and int(precommit.get("clean_cases", -1)) == 180
            and precommit.get("model_was_run") is False
            and precommit.get("development_overlap_audit_passed") is True
            and precommit.get("single_injection_and_propagation_audit_passed") is True
        ),
        "prediction_lock_valid": bool(
            prediction_lock
            and prediction_lock.get("protocol")
            == "v5_core_r2_confirmation_prediction_lock_v1"
            and int(prediction_lock.get("cases", -1)) == 780
            and prediction_lock.get("labels_read") == []
            and prediction_lock.get("labels_may_now_be_released") is True
        ),
        "confirmation_score_valid": bool(
            score
            and score.get("protocol") == "v5_core_r2_independent_confirmation_score_v1"
            and score.get("independent_evidence") is True
            and int(score.get("events", -1)) == 600
            and int(score.get("clean_controls", -1)) == 180
            and score.get("secret_precommit_verified") is True
            and isinstance(score.get("final_promotion_passed"), bool)
        ),
    }

    pressure_terminal_failure = bool(
        checks["pressure_receipt_valid"]
        and pressure
        and pressure.get("eligible_for_new_independent_confirmation") is False
    )
    confirmation_complete = checks["confirmation_score_valid"]
    protocol_terminal = pressure_terminal_failure or confirmation_complete
    if pressure_terminal_failure:
        stage = "terminal_negative_pressure"
    elif confirmation_complete:
        stage = "independent_confirmation_complete"
    elif checks["prediction_lock_valid"]:
        stage = "predictions_locked_waiting_for_secret"
    elif checks["third_party_precommit_valid"] and checks["immutable_freeze_and_tag_valid"]:
        stage = "ready_for_label_free_prediction_lock"
    elif checks["immutable_freeze_and_tag_valid"]:
        stage = "frozen_waiting_for_third_party_public_pack"
    elif checks["pressure_eligible_for_confirmation"]:
        stage = "pressure_passed_ready_to_freeze"
    elif checks["development_receipt_valid"]:
        stage = "waiting_for_pressure_safety"
    else:
        stage = "development_evidence_incomplete"

    promotion = bool(score and score.get("final_promotion_passed") is True)
    payload = {
        "protocol": "v5_core_r2_completion_audit_v1",
        "stage": stage,
        "checks": checks,
        "protocol_terminal": protocol_terminal,
        "terminal_outcome": (
            "promoted" if promotion else
            "not_promoted_after_independent_confirmation" if confirmation_complete else
            "stopped_after_pressure_failure" if pressure_terminal_failure else
            None
        ),
        "promoted_to_main_model": promotion,
        "development_failure_preserved": bool(
            development
            and development.get("gates", {}).get("failed_gates")
            == ["improvement_spans_at_least_four_error_types"]
        ),
        "evidence_paths": {
            "development": str(args.development),
            "pressure": str(args.pressure),
            "freeze": str(args.freeze),
            "third_party_precommit": str(args.third_party_precommit),
            "prediction_lock": str(args.prediction_lock),
            "confirmation_score": str(args.confirmation_score),
        },
        "evidence_sha256": {
            name: sha256(path)
            for name, path in {
                "development": args.development,
                "pressure": args.pressure,
                "freeze": args.freeze,
                "third_party_precommit": args.third_party_precommit,
                "prediction_lock": args.prediction_lock,
                "confirmation_score": args.confirmation_score,
            }.items()
            if path.is_file()
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    print(f"R2 protocol stage: {stage}")
    print(f"R2 protocol terminal: {protocol_terminal}")
    print(f"R2 promoted to main model: {promotion}")


if __name__ == "__main__":
    main()
