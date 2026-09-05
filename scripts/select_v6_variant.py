"""Apply the preregistered V6 gates and deterministic variant ordering."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

STRONG_TYPES = ("reference_shift", "operator", "absolute_reference", "copy_offset")
ABLATIONS = (
    "no_ffc", "no_bss", "no_d", "no_irg", "no_side_effect",
    "no_uniqueness", "v4_only", "semantics_only",
)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/v6_validation_locked"))
    parser.add_argument("--dataset", type=Path, default=Path("data/v6_validation"))
    args = parser.parse_args()
    results = load(args.root / "summary.json")
    clean = load(args.root / "clean/v6_clean_summary.json")
    quality = load(args.dataset / "validation/dataset_quality.json")
    leakage = load(args.dataset / "validation/leakage_audit.json")
    metadata = load(args.root / "predictions/prediction_metadata.json")
    completion = load(args.root / "predictions/prediction_complete.json")
    round_audits = {letter: load(Path(f"results/v6_development_{letter}/v6_round_audit.json")) for letter in "abc"}
    enron = {letter: load(args.root / f"enron_{letter}/enron_summary.json") for letter in "abc"}
    enron_completion = {
        letter: load(args.root / f"enron_{letter}/enron_prediction_complete.json") for letter in "abc"
    }
    summaries = results["summaries"]
    v4 = summaries["v4"]
    assessments = {}
    for letter in "abc":
        method = f"v6_{letter}"
        row = summaries[method]
        by_error = row["by_error"]
        strong_declines = {
            error: v4["by_error"][error]["top5"] - by_error[error]["top5"]
            for error in STRONG_TYPES
        }
        clean_rate = clean["variants"][method]["false_alarm_rate"]
        ablation_methods = [f"v6_{letter}_ablation_{name}" for name in ABLATIONS]
        missing_ablations = [name for name in ablation_methods if name not in summaries]
        max_ablation_macro = max(
            (summaries[name]["macro_top5"] for name in ablation_methods if name in summaries),
            default=float("inf"),
        )
        gates = {
            "data_validity_at_least_98_percent": quality["valid_rate"] >= 0.98,
            "cross_split_leakage_audit": leakage["cross_split_passed"],
            "all_360_predictions_complete": (
                results["events"] == 360 and completion["complete"]
                and completion.get("full_ranking_audit_passed", False)
            ),
            "all_variants_predicted_before_scoring": metadata["variants"] == ["a", "b", "c"],
            "traceability_complete": results["traceability_complete"],
            "candidate_coverage_at_25_at_least_95_percent": row["candidate_coverage_at_25"] >= 0.95,
            "macro_top5_at_least_80_percent": row["macro_top5"] >= 0.80,
            "worst_type_top5_at_least_70_percent": row["worst_type_top5"] >= 0.70,
            "function_replacement_top5_at_least_75_percent": by_error["function_replacement"]["top5"] >= 0.75,
            "range_boundary_top5_at_least_75_percent": by_error["range_boundary"]["top5"] >= 0.75,
            "repair_exact_at_least_75_percent": row["repair_exact"] >= 0.75,
            "clean_false_alarm_at_most_10_percent": clean_rate <= 0.10,
            "strong_types_decline_at_most_5_points": max(strong_declines.values()) <= 0.05,
            "enron_mrr_not_below_v4": enron[letter]["v6_mrr_not_below_v4"],
            "enron_full_ranking_audit_passed": enron_completion[letter].get("full_ranking_audit_passed", False),
            "all_variant_matched_ablations_present": not missing_ablations,
            "not_outperformed_by_key_ablation_over_0_02": (
                not missing_ablations and max_ablation_macro <= row["macro_top5"] + 0.02
            ),
            "median_runtime_at_most_1_5x_v4": row["runtime_median"] <= 1.5 * v4["runtime_median"],
        }
        assessments[letter] = {
            "method": method,
            # Development rounds diagnose the three fixed mechanisms.  The
            # preregistered method specification selects only after the
            # one-shot 360-event locked validation has all A/B/C predictions on disk;
            # a development diagnostic is therefore recorded, not promoted
            # into an unregistered selection gate.
            "development_round_passed_diagnostic": round_audits[letter].get("round_passed", False),
            "development_round_failed_gates": [
                name for name, passed in round_audits[letter].get("gates", {}).items() if not passed
            ],
            "metrics": row,
            "clean_false_alarm_rate": clean_rate,
            "strong_type_declines": strong_declines,
            "variant_matched_ablations": ablation_methods,
            "max_ablation_macro_top5": max_ablation_macro if not missing_ablations else None,
            "enron": enron[letter]["summary"],
            "gates": gates,
            "passed": all(gates.values()),
        }
    candidates = [letter for letter in "abc" if assessments[letter]["passed"]]
    candidates.sort(key=lambda letter: (
        -assessments[letter]["metrics"]["macro_top5"],
        -assessments[letter]["metrics"]["worst_type_top5"],
        -assessments[letter]["metrics"]["mrr"],
        assessments[letter]["clean_false_alarm_rate"],
        assessments[letter]["metrics"]["runtime_median"],
        "abc".index(letter),
    ))
    selected = candidates[0] if candidates else None
    receipt = {
        "protocol": "v6_preregistered_variant_selection",
        "selection_rule_order": [
            "macro_top5_desc", "worst_type_top5_desc", "mrr_desc",
            "clean_false_alarm_asc", "runtime_median_asc", "simpler_a_b_c",
        ],
        "assessments": assessments,
        "selected_variant": selected,
        "freeze_allowed": selected is not None,
        "no_v7_if_none_pass": selected is None,
    }
    output = args.root / "v6_selection_receipt.json"
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    if selected is None:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
