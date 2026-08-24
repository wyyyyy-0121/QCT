"""Requirement-by-requirement readiness audit before the V6-A large run."""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v6 import v6_default_parameters, v6_scores
from scripts.build_v6_dataset import clean_controls, enumerate_cases


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    required = [
        "formulaguard/v6.py", "formulaguard/api.py", "research/V6_METHOD_SPEC.md",
        "research/V6_FAILURE_HYPOTHESIS_AUDIT.json", "research/V6_THIRD_PARTY_PROTOCOL.md",
        "research/V6_THIRD_PARTY_CASE_MANIFEST_TEMPLATE.csv",
        "scripts/build_v6_dataset.py", "scripts/audit_v6_dataset.py",
        "scripts/run_v6_predictions.py", "scripts/score_v6_predictions.py",
        "scripts/run_v6_round.py", "scripts/run_v6_validation.py",
        "scripts/select_v6_variant.py", "scripts/freeze_v6_model.py",
        "scripts/run_v6_performance.py", "scripts/run_v6_blind_lock.py",
        "scripts/score_v6_blind.py", "run_v6_round.cmd", "run_v6_validation.cmd",
        "run_v6_freeze.cmd", "run_v6_performance.cmd", "run_v6_blind_lock.cmd",
        "run_v6_blind_score.cmd",
    ]
    missing = [relative for relative in required if not (ROOT / relative).is_file()]
    v4 = load(ROOT / "research/frozen_config_v4.json")
    v52 = load(ROOT / "research/frozen_config_v52.json")
    frozen_sources_unchanged = (
        sha256(ROOT / "formulaguard/localize.py") == v4["model_source_sha256"]["formulaguard/localize.py"]
        == v52["model_source_sha256"]["formulaguard/localize.py"]
        and sha256(ROOT / "formulaguard/v52.py") == v52["model_source_sha256"]["formulaguard/v52.py"]
    )
    profile_counts = {
        "development": len(enumerate_cases("development")),
        "validation": len(enumerate_cases("validation")),
        "redteam": len(enumerate_cases("redteam")),
        "clean": len(clean_controls()),
        "enron_retrospective": 30,
        "third_party_final": 600,
    }
    expected_counts = {
        "development": 1200, "validation": 360, "redteam": 360,
        "clean": 240, "enron_retrospective": 30, "third_party_final": 600,
    }
    worker_scripts = [
        "scripts/run_v6_round.py", "scripts/run_v6_validation.py",
        "scripts/run_v6_performance.py", "scripts/run_v6_blind_lock.py",
        "scripts/run_v6_predictions.py", "scripts/run_v6_enron.py",
    ]
    worker_defaults = {
        relative: bool(re.search(r'add_argument\("--workers"[^\n]*default=24', (ROOT / relative).read_text(encoding="utf-8")))
        for relative in worker_scripts
    }
    receipt_path = ROOT / "results/v6_short_test_receipt.json"
    smoke_path = ROOT / "results/v6_smoke_semantic_r3/completion_audit.json"
    metadata_path = ROOT / "results/v6_smoke_semantic_r3/predictions/prediction_metadata.json"
    receipt = load(receipt_path) if receipt_path.exists() else {}
    smoke = load(smoke_path) if smoke_path.exists() else {}
    metadata = load(metadata_path) if metadata_path.exists() else {}
    parameters = v6_default_parameters()
    checks = {
        "all_required_artifacts_exist": not missing,
        "frozen_v4_v52_sources_unchanged": frozen_sources_unchanged,
        "public_interface_exact_and_label_free": list(inspect.signature(v6_scores).parameters) == [
            "model", "variant", "base_candidate_limit", "semantic_candidate_limit"
        ],
        "all_preregistered_parameters_present": all(key in parameters for key in (
            "base_candidate_limit", "semantic_candidate_limit", "strong_support_min",
            "strong_semantic_min", "strong_margin_min", "strong_delta_min", "strong_irg_min",
            "moderate_support_min", "moderate_semantic_min", "side_effect_weight",
            "semantic_energy_weight", "promotion_limit_per_workbook",
        )),
        "all_dataset_layer_counts_match": profile_counts == expected_counts,
        "experimental_event_total_is_2790": sum(profile_counts.values()) == 2790,
        "all_large_worker_defaults_are_24": all(worker_defaults.values()),
        "short_tests_passed": receipt.get("passed") is True,
        "short_test_source_hash_is_current": receipt.get("v6_source_sha256") == sha256(ROOT / "formulaguard/v6.py"),
        "smoke_completion_audit_passed": smoke.get("passed") is True,
        "smoke_prediction_uses_current_v6_source": metadata.get("v6_source_sha256") == sha256(ROOT / "formulaguard/v6.py"),
        "third_party_final_mode_requires_external_case_manifest": "--case-manifest" in (ROOT / "scripts/build_v6_third_party_pack.py").read_text(encoding="utf-8"),
        "historical_100_is_marked_posthoc_only": load(ROOT / "research/V6_FAILURE_HYPOTHESIS_AUDIT.json").get("not_for_v6_model_selection") is True,
    }
    payload = {
        "protocol": "v6_implementation_readiness_before_large_development",
        "checks": checks,
        "passed": all(checks.values()),
        "missing_artifacts": missing,
        "profile_counts": profile_counts,
        "worker_defaults_24": worker_defaults,
        "v6_source_sha256": sha256(ROOT / "formulaguard/v6.py"),
        "method_spec_sha256": sha256(ROOT / "research/V6_METHOD_SPEC.md"),
        "short_test_receipt_sha256": sha256(receipt_path) if receipt_path.exists() else None,
        "smoke_audit_sha256": sha256(smoke_path) if smoke_path.exists() else None,
        "status_if_passed": "ready_for_user_to_run_v6_a; not frozen; no paper performance claim",
    }
    output = ROOT / "research/V6_IMPLEMENTATION_READINESS.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    if not payload["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
