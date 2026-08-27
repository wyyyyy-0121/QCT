"""Apply preregistered V5-Core validation gates and select a head."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def comparison(payload: dict, left: str, right: str) -> dict | None:
    return next((
        row for row in payload.get("paired_bootstrap", [])
        if row["left"] == left and row["right"] == right
    ), None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--dataset-audit", type=Path, required=True)
    parser.add_argument("--training-audit", type=Path, required=True)
    parser.add_argument("--enron", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.summary.read_text(encoding="utf-8"))
    dataset = json.loads(args.dataset_audit.read_text(encoding="utf-8"))
    training = json.loads(args.training_audit.read_text(encoding="utf-8"))
    enron = json.loads(args.enron.read_text(encoding="utf-8"))
    summaries = payload["summary"]
    clean = payload.get("clean", {})
    baseline = summaries.get("v4", {})
    strong_types = {"operator", "copy_offset", "absolute_reference", "reference_shift"}
    eligibility = {}
    for method in ("v5_rule", "v5_learned"):
        metrics = summaries.get(method)
        if not metrics:
            eligibility[method] = {"eligible": False, "reasons": ["missing method"]}
            continue
        reasons = []
        if not dataset.get("hard_gate_passed"):
            reasons.append("dataset audit failed")
        if metrics["candidate_coverage_32"] < 0.95:
            reasons.append("candidate coverage below 95%")
        if metrics["macro_top5"] < 0.80:
            reasons.append("macro Top-5 below 80%")
        if metrics["weakest_type_top5"] < 0.70:
            reasons.append("weakest type Top-5 below 70%")
        for error_type in ("function_replacement", "range_boundary"):
            if metrics["by_type_top5"].get(error_type, 0.0) < 0.75:
                reasons.append(f"{error_type} Top-5 below 75%")
        if metrics["exact_repair"] < 0.75:
            reasons.append("exact repair below 75%")
        clean_metrics = clean.get(method, {})
        if clean_metrics.get("false_alarm_rate", 1.0) > 0.10:
            reasons.append("clean false alarm above 10%")
        if clean_metrics.get("legitimate_exception_false_alarm_rate", 1.0) > 0.15:
            reasons.append("legitimate-exception false alarm above 15%")
        for error_type in strong_types:
            if metrics["by_type_top5"].get(error_type, 0.0) + 0.05 < baseline.get("by_type_top5", {}).get(error_type, 0.0):
                reasons.append(f"{error_type} regressed more than 5 points")
        versus_v4 = comparison(payload, method, "v4")
        if not versus_v4:
            reasons.append("missing paired V4 comparison")
        else:
            if versus_v4["mrr_ci95"][0] <= 0:
                reasons.append("MRR improvement CI crosses zero")
            if versus_v4["macro_top5_ci95"][0] <= 0:
                reasons.append("macro Top-5 improvement CI crosses zero")
        baseline_seconds = float(baseline.get("median_localization_seconds", 0.0))
        if baseline_seconds <= 0:
            reasons.append("missing V4 validation runtime")
        elif metrics.get("median_localization_seconds", float("inf")) > 2.0 * baseline_seconds:
            reasons.append("median localization runtime exceeds 2x V4")
        improved_regimes = [
            regime for regime, top5 in metrics.get("by_regime_top5", {}).items()
            if top5 > baseline.get("by_regime_top5", {}).get(regime, 0.0) + 1e-12
        ]
        if len(improved_regimes) < 3:
            reasons.append("Top-5 improvement appears in fewer than 3 of 4 regimes")
        strong_mrr_gains = [
            error_type for error_type in strong_types
            if metrics.get("by_type_mrr", {}).get(error_type, 0.0)
            > baseline.get("by_type_mrr", {}).get(error_type, 0.0) + 1e-12
        ]
        if not strong_mrr_gains:
            reasons.append("improvement is confined to function/range types")
        enron_key = "rule_mrr_not_below_v4_by_more_than_001" if method == "v5_rule" else "learned_mrr_not_below_v4_by_more_than_001"
        if not enron.get(enron_key, False):
            reasons.append("Enron MRR safety gate failed")
        if method == "v5_learned":
            if not training.get("positive_weight_constraints_passed") or not training.get("negative_weight_constraints_passed"):
                reasons.append("learned weight sign constraints failed")
            cross_validation = training.get("cross_validation", [])
            selected_regularization = training.get("selected_regularization")
            selected_cv = next((row for row in cross_validation if row.get("regularization") == selected_regularization), None)
            if not selected_cv or any(score <= 0.5 for score in selected_cv.get("fold_pair_accuracy", [])):
                reasons.append("learned head is not stable across all template folds")
        eligibility[method] = {
            "eligible": not reasons,
            "reasons": reasons,
            "metrics": metrics,
            "clean": clean_metrics,
            "versus_v4": versus_v4,
            "improved_regimes": improved_regimes,
            "strong_type_mrr_gains": strong_mrr_gains,
        }

    eligible = [method for method, row in eligibility.items() if row["eligible"]]
    selected = None
    if "v5_rule" in eligible:
        selected = "v5_rule"
    if "v5_learned" in eligible:
        learned_vs_rule = comparison(payload, "v5_learned", "v5_rule")
        credible = bool(
            learned_vs_rule
            and learned_vs_rule["mrr_ci95"][0] > 0
            and learned_vs_rule["macro_top5_ci95"][0] > 0
        )
        if selected is None or credible:
            selected = "v5_learned"

    ablation_failures = []
    if selected:
        full_macro = summaries[selected]["macro_top5"]
        for method, metrics in summaries.items():
            if method.startswith(f"{selected}_ablation_") and metrics["macro_top5"] > full_macro + 0.02:
                ablation_failures.append({"method": method, "advantage": metrics["macro_top5"] - full_macro})
        if ablation_failures:
            eligibility[selected]["eligible"] = False
            eligibility[selected]["reasons"].append("key ablation exceeds full model by >0.02")
            selected = None

    result = {
        "protocol": "v5_core_locked_validation_selection_v1",
        "eligibility": eligibility,
        "ablation_failures": ablation_failures,
        "selected_head": selected,
        "v5_promoted_over_v4": selected is not None,
        "validation_runtime_gate_included": True,
        "enron_safety_gate_included": True,
        "no_parameter_changes_after_this_receipt": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    if selected is None:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
