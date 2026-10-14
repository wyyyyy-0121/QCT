from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

CORE_HASH_PREFIXES = ("formulaguard/",)
CORE_HASH_FILES = {
    "scripts/build_benchmarks.mjs",
    "scripts/build_benchmarks_v2.mjs",
    "scripts/audit_structural_diversity.py",
    "scripts/run_experiments.py",
    "scripts/run_clean_evaluation.py",
    "scripts/run_sensitivity.py",
    "scripts/validate_benchmark.py",
}


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser(description="Freeze an eligible quick configuration before full evaluation")
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model-version", choices=("v2", "v3"), default="v2")
    args = parser.parse_args()

    output = args.output or args.results / ("frozen_config_v3.json" if args.model_version == "v3" else "frozen_config.json")
    summary = read_csv(args.results / "summary.csv")
    by_family = read_csv(args.results / "by_family.csv")
    sensitivity_path = args.results / "sensitivity_summary.csv"
    sensitivity = read_csv(sensitivity_path) if sensitivity_path.is_file() else []
    clean = json.loads((args.results / "clean_summary.json").read_text(encoding="utf-8"))
    quality = json.loads((args.validation / "dataset_quality.json").read_text(encoding="utf-8"))
    environment = json.loads((args.results / "environment.json").read_text(encoding="utf-8"))

    summary_map = {row["method"]: row for row in summary}
    primary_method = "formulaguard_v3" if args.model_version == "v3" else "formulaguard"
    formulaguard = summary_map[primary_method]
    no_oracle = [
        row for row in summary
        if row["method"] not in {"formulaguard", "formulaguard_v3", "sfl_oracle"}
        and not row["method"].startswith("ablate_")
        and not row["method"].startswith("v3_ablate_")
    ]
    strongest = max(no_oracle, key=lambda row: float(row["mrr"]))

    families = sorted({row["template_family"] for row in by_family})
    family_wins = 0
    for family in families:
        indexed = {
            row["method"]: float(row["mrr"])
            for row in by_family if row["template_family"] == family
        }
        if indexed.get(primary_method, 0.0) >= indexed.get(strongest["method"], float("inf")):
            family_wins += 1

    ablation_prefix = "v3_ablate_" if args.model_version == "v3" else "ablate_"
    ablation_mrr = [float(row["mrr"]) for row in summary if row["method"].startswith(ablation_prefix)]
    max_ablation_advantage = max(ablation_mrr, default=0.0) - float(formulaguard["mrr"])
    eligible_profiles = [
        row for row in sensitivity
        if int(row["candidate_limit"]) == 15
        and int(row["threshold_gate_passed"]) == 1
    ]
    selected_profile = max(
        eligible_profiles,
        key=lambda row: (float(row["mrr"]), -float(row["runtime_median"])),
        default=None,
    )
    if args.model_version == "v3":
        # v3 sensitivity is a robustness analysis, not a model-selection
        # search.  The preregistered CAR weights and candidate limit stay fixed.
        selected_profile = None

    v3_comparison_path = args.results / "v3_vs_v2.json"
    v3_comparison = json.loads(v3_comparison_path.read_text(encoding="utf-8")) if v3_comparison_path.is_file() else {}
    gates = {
        "validation_rate_at_least_95_percent": float(quality["valid_rate"]) >= 0.95,
        "candidate_coverage_at_15_at_least_90_percent": float(formulaguard["candidate_coverage_at_15"]) >= 0.90,
        "clean_alarm_within_preregistered_limit": float(clean["calibration_clean_alarm_rate"]) <= (0.20 if args.model_version == "v3" else 0.25),
        "mutant_recall_at_least_80_percent": float(clean["calibration_mutant_recall"]) >= 0.80,
        "mrr_not_below_strongest_baseline": float(formulaguard["mrr"]) >= float(strongest["mrr"]),
        "at_least_three_of_four_families_not_below_baseline": len(families) >= 4 and family_wins >= 3,
        "no_ablation_advantage_above_0_02": max_ablation_advantage <= 0.02 + 1e-12,
        "eligible_preregistered_profile_exists": selected_profile is not None or args.model_version == "v3",
    }
    if args.model_version == "v3":
        gates["v3_mrr_not_below_v2"] = float(v3_comparison.get("mean_mrr_difference_v3_minus_v2", -1.0)) >= -1e-12
        gates["source_first_metric_present"] = "source_first_in_causal_cone" in formulaguard
    assessment = {
        "generated_at": datetime.now(UTC).isoformat(),
        "eligible": all(gates.values()),
        "gates": gates,
        "strongest_no_oracle_baseline": strongest["method"],
        "family_count": len(families),
        "families_not_below_baseline": family_wins,
        "max_ablation_advantage": max_ablation_advantage,
    }
    (args.results / "freeze_assessment.json").write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not assessment["eligible"]:
        failed = ", ".join(name for name, passed in gates.items() if not passed)
        raise SystemExit(f"Quick results are not eligible for freezing: {failed}")

    if args.model_version == "v2":
        assert selected_profile is not None
    core_hashes = {
        row["path"]: row["sha256"]
        for row in environment.get("source_files", [])
        if row["path"].startswith(CORE_HASH_PREFIXES) or row["path"] in CORE_HASH_FILES
    }
    config = {
        "schema_version": 2 if args.model_version == "v3" else 1,
        "model_version": args.model_version,
        "created_at": datetime.now(UTC).isoformat(),
        "source_mode": "quick",
        "benchmark_name": args.validation.parent.name,
        "profile": selected_profile["profile"] if selected_profile else "v3_preregistered_car",
        "gir_weights": json.loads(selected_profile["gir_weights"]) if selected_profile else [0.35, 0.50, 0.10, 0.05],
        "car_weights": [0.20, 0.60, 0.10, 0.10],
        "candidate_limit": 15,
        "alarm_threshold": float(selected_profile["selected_threshold"]) if selected_profile else float(clean["selected_threshold"]),
        "calibration_mutant_recall": float(selected_profile["calibration_mutant_recall"]) if selected_profile else float(clean["calibration_mutant_recall"]),
        "calibration_clean_alarm_rate": float(selected_profile["calibration_clean_alarm_rate"]) if selected_profile else float(clean["calibration_clean_alarm_rate"]),
        "quick_mrr": float(selected_profile["mrr"]) if selected_profile else float(formulaguard["mrr"]),
        "git_commit": environment["git_commit"],
        "core_source_hashes": core_hashes,
        "freeze_assessment": assessment,
    }
    output.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
