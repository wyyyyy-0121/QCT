"""Apply the preregistered V5 StructuralGuard v2 acceptance gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ERROR_CONDITIONS = ("singleton", "coherent_block", "systematic_column")


def audit(payload: dict) -> dict:
    summaries = {row["method"]: row for row in payload.get("summaries", [])}
    v5 = summaries.get("v5_structural_guard", {})
    v4 = summaries.get("v4_r1", {})
    v5_conditions = v5.get("by_condition", {})
    v4_conditions = v4.get("by_condition", {})
    singleton = v5_conditions.get("singleton", {})
    clean = v5_conditions.get("clean", {})
    coherent = v5_conditions.get("coherent_block", {})
    systematic = v5_conditions.get("systematic_column", {})

    checks = {
        "dataset_is_corrected_v2": payload.get("dataset_protocol")
        == "structuralguard_standard_benchmark_v2",
        "only_v5_and_frozen_v4_r1_requested": set(payload.get("requested_methods") or ())
        == {"v5_structural_guard", "v4_r1"},
        "both_methods_complete": all(
            summaries.get(method, {}).get("status") == "ok"
            and summaries.get(method, {}).get("completed_cases") == 20
            for method in ("v5_structural_guard", "v4_r1")
        ),
        "singleton_ap_preserved": singleton.get("macro_average_precision") == 1.0,
        "singleton_exact_28_of_28": singleton.get("exact_repairs") == 28,
        "singleton_candidate_precision_at_least_90_percent": float(
            singleton.get("candidate_exact_precision") or 0.0
        )
        >= 0.90,
        "clean_has_zero_candidates": clean.get("candidate_count") == 0,
        "clean_has_zero_accepted_groups": clean.get("accepted_group_count") == 0,
        "coherent_ap_at_least_90_percent": float(
            coherent.get("macro_average_precision") or 0.0
        )
        >= 0.90,
        "coherent_exact_coverage_at_least_90_percent": float(
            coherent.get("candidate_exact_coverage") or 0.0
        )
        >= 0.90,
        "coherent_candidate_precision_at_least_90_percent": float(
            coherent.get("candidate_exact_precision") or 0.0
        )
        >= 0.90,
        "systematic_ap_preserved": systematic.get("macro_average_precision") == 1.0,
        "systematic_exact_at_least_846_of_940": int(systematic.get("exact_repairs") or 0)
        >= 846,
        "systematic_candidate_precision_at_least_90_percent": float(
            systematic.get("candidate_exact_precision") or 0.0
        )
        >= 0.90,
        "v5_not_below_v4_on_error_ap": all(
            float(v5_conditions.get(condition, {}).get("macro_average_precision") or 0.0)
            >= float(v4_conditions.get(condition, {}).get("macro_average_precision") or 0.0)
            for condition in ERROR_CONDITIONS
        ),
        "v5_not_below_v4_on_exact_coverage": all(
            float(v5_conditions.get(condition, {}).get("candidate_exact_coverage") or 0.0)
            >= float(v4_conditions.get(condition, {}).get("candidate_exact_coverage") or 0.0)
            for condition in ERROR_CONDITIONS
        ),
    }
    return {
        "protocol": "structuralguard_standard_v2_acceptance_v1",
        "gate_passed": all(checks.values()),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evaluation", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.evaluation.read_text(encoding="utf-8"))
    result = audit(payload)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
